"""
State manager: tracks translation progress per project + language.
Each language is persisted as data/input/<project>/states/<lang>.json
"""

import json
import time
from pathlib import Path


_STATES_DIR = "states"


def _lang_path(project_dir: str, lang_code: str) -> Path:
    return Path(project_dir) / _STATES_DIR / f"{lang_code}.json"


def _states_dir(project_dir: str) -> Path:
    return Path(project_dir) / _STATES_DIR


def _default_lang_state() -> dict:
    return {
        "status": "idle",
        "progress": {"done": 0, "total": 0},
        "translated": {},
        "last_updated": None,
        "error": None,
    }


def _load_lang_file(project_dir: str, lang_code: str) -> dict:
    p = _lang_path(project_dir, lang_code)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _default_lang_state()


def _save_lang_file(project_dir: str, lang_code: str, lang_state: dict) -> None:
    p = _lang_path(project_dir, lang_code)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(lang_state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API (unchanged signatures)
# ---------------------------------------------------------------------------

def get_lang_state(project_dir: str, lang_code: str) -> dict:
    """
    Returns state dict for a language. Structure:
    {
      "status": "idle" | "running" | "done" | "error",
      "progress": { "done": int, "total": int },
      "translated": { "dotted.key": "translated value", ... },
      "last_updated": timestamp,
      "error": "..." | null
    }
    """
    return _load_lang_file(project_dir, lang_code)


def update_lang_state(project_dir: str, lang_code: str, updates: dict) -> dict:
    lang_state = _load_lang_file(project_dir, lang_code)
    lang_state.update(updates)
    lang_state["last_updated"] = time.time()
    _save_lang_file(project_dir, lang_code, lang_state)
    return lang_state


def update_translated_keys(
    project_dir: str, lang_code: str, new_translations: dict[str, str]
) -> None:
    """Merge new_translations into the persisted translated dict."""
    lang_state = _load_lang_file(project_dir, lang_code)
    lang_state.setdefault("translated", {})
    lang_state["translated"].update(new_translations)
    lang_state["last_updated"] = time.time()
    _save_lang_file(project_dir, lang_code, lang_state)


def update_progress(project_dir: str, lang_code: str, done: int, total: int) -> None:
    lang_state = _load_lang_file(project_dir, lang_code)
    lang_state["progress"] = {"done": done, "total": total}
    lang_state["last_updated"] = time.time()
    _save_lang_file(project_dir, lang_code, lang_state)


def get_all_lang_states(project_dir: str) -> dict:
    """Return {lang_code: state} for every language that has a state file."""
    result = {}
    d = _states_dir(project_dir)
    if d.exists():
        for f in sorted(d.glob("*.json")):
            try:
                result[f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
    return result
