"""
Project configuration management.
Each project has a config at data/input/<project>/project.json
"""

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Language code → name lookup (ISO 639-1)
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).parent.parent / "data" / "databases" / "language-codes.json"
_LANG_CODES: dict[str, str] = {}


def _get_lang_codes() -> dict[str, str]:
    global _LANG_CODES
    if not _LANG_CODES:
        try:
            _LANG_CODES = json.loads(_DB_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _LANG_CODES

CONFIG_FILE = "project.json"
PROJECTS_ROOT = Path(__file__).parent.parent / "data" / "input"


def get_projects_root() -> Path:
    return PROJECTS_ROOT


def list_projects() -> list[dict]:
    """Return list of project summaries."""
    projects = []
    if not PROJECTS_ROOT.exists():
        return projects
    for d in sorted(PROJECTS_ROOT.iterdir()):
        if d.is_dir():
            cfg = load_project_config(d.name)
            projects.append({"name": d.name, "config": cfg})
    return projects


def load_project_config(project_name: str) -> dict:
    p = PROJECTS_ROOT / project_name / CONFIG_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Auto-detect config from directory contents
    return _auto_detect_config(project_name)


def save_project_config(project_name: str, config: dict) -> None:
    p = PROJECTS_ROOT / project_name / CONFIG_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _auto_detect_config(project_name: str) -> dict:
    """Build a best-guess config by scanning the project directory."""
    project_dir = PROJECTS_ROOT / project_name

    # Find language files
    lang_dir = None
    lang_files = []
    master_lang = None

    # Common patterns for language directories
    for candidate in ["languages", "lang", "locales", "i18n", "translations", "."]:
        d = project_dir / candidate
        if d.is_dir():
            files = [
                f for f in d.iterdir()
                if f.is_file() and f.suffix.lower() in (".ts", ".js", ".json", ".py")
                and not f.name.startswith(".")
            ]
            if files:
                lang_dir = candidate
                lang_files = sorted(files, key=lambda f: f.name)
                break

    if lang_files:
        # Guess master: prefer 'tr', then 'en', then first file
        codes = [f.stem for f in lang_files]
        for preferred in ("tr", "en"):
            if preferred in codes:
                master_lang = preferred
                break
        if not master_lang:
            master_lang = codes[0] if codes else None

    config = {
        "name": project_name,
        "languages_dir": lang_dir or "languages",
        "master_lang": master_lang or "tr",
        "source_lang_name": _lang_name(master_lang or "tr"),
        "ollama_url": "http://localhost:11434",
        "model": "gpt-oss:20b",
        "batch_size": 25,
        "skip_langs": [],
        "languages": {},
    }

    # Populate language entries
    for f in lang_files:
        code = f.stem
        config["languages"][code] = {
            "code": code,
            "name": _lang_name(code),
            "file": f.name,
            "is_master": code == master_lang,
        }

    return config


def get_project_dir(project_name: str) -> Path:
    return PROJECTS_ROOT / project_name


def get_languages_dir(project_name: str) -> Path:
    config = load_project_config(project_name)
    return PROJECTS_ROOT / project_name / config.get("languages_dir", "languages")


def get_master_file(project_name: str) -> Path | None:
    config = load_project_config(project_name)
    lang_dir = get_languages_dir(project_name)
    master = config.get("master_lang", "tr")
    langs = config.get("languages", {})

    if master in langs:
        return lang_dir / langs[master]["file"]

    # Fallback: scan for file with master stem
    for ext in (".ts", ".js", ".json", ".py"):
        candidate = lang_dir / f"{master}{ext}"
        if candidate.exists():
            return candidate

    return None


def get_lang_name(code: str) -> str:
    """Return a human-readable language name for a 2-letter ISO 639-1 code.
    Looks up data/databases/language-codes.json. Returns code.upper() if not found.
    """
    return _get_lang_codes().get(code.lower(), code.upper())


async def get_lang_name_async(code: str, ollama_url: str, model: str) -> str:
    """Like get_lang_name() but falls back to an Ollama call for unknown codes."""
    name = _get_lang_codes().get(code.lower())
    if name:
        return name
    # JSON miss → ask the model
    try:
        import httpx
        prompt = (
            f'What is the full English name of the language with ISO 639-1 code "{code}"? '
            f'Reply with ONLY the language name, nothing else.'
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{ollama_url.rstrip('/')}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0, "num_predict": 20}},
            )
            r.raise_for_status()
            result = r.json().get("response", "").strip().strip('"').strip("'")
            if result and len(result) < 60:
                return result
    except Exception:
        pass
    return code.upper()


def _lang_name(code: str) -> str:
    """Sync alias used during config auto-detection."""
    return get_lang_name(code)
