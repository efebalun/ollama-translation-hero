"""
FastAPI backend for TranslationHero.
Serves the web UI and exposes translation APIs.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from parsers import parse_file
from translator import translate_batch, check_ollama_connection
from state_manager import (
    get_lang_state,
    get_all_lang_states,
    update_lang_state,
    update_translated_keys,
    update_progress,
)
from project_config import (
    list_projects,
    load_project_config,
    save_project_config,
    get_project_dir,
    get_languages_dir,
    get_master_file,
    get_lang_name,
    get_lang_name_async,
)
from writer import write_output_file

app = FastAPI(title="TranslationHero", version="1.0.0")

# Track active translation tasks  {project_lang_key: asyncio.Task}
_active_tasks: dict[str, asyncio.Task] = {}


@app.on_event("startup")
async def _auto_create_project_configs() -> None:
    """Create project.json for any project folder that doesn't have one yet."""
    from project_config import PROJECTS_ROOT
    if not PROJECTS_ROOT.exists():
        return
    for d in sorted(PROJECTS_ROOT.iterdir()):
        if not d.is_dir():
            continue
        config_path = d / "project.json"
        if not config_path.exists():
            cfg = load_project_config(d.name)  # triggers auto-detect
            save_project_config(d.name, cfg)


# ---------------------------------------------------------------------------
# Project endpoints
# ---------------------------------------------------------------------------

@app.get("/api/projects")
async def api_list_projects():
    return list_projects()


@app.get("/api/projects/{project_name}")
async def api_get_project(project_name: str):
    cfg = load_project_config(project_name)
    states = get_all_lang_states(str(get_project_dir(project_name)))
    return {"config": cfg, "states": states}


class ProjectConfigUpdate(BaseModel):
    master_lang: str | None = None
    ollama_url: str | None = None
    model: str | None = None
    batch_size: int | None = None
    skip_langs: list[str] | None = None
    source_lang_name: str | None = None


@app.patch("/api/projects/{project_name}/config")
async def api_update_project_config(project_name: str, updates: ProjectConfigUpdate):
    cfg = load_project_config(project_name)
    data = updates.model_dump(exclude_none=True)
    cfg.update(data)
    # Sync is_master flags whenever master_lang changes
    new_master = cfg.get("master_lang")
    if new_master and "languages" in cfg:
        for code, info in cfg["languages"].items():
            info["is_master"] = (code == new_master)
    save_project_config(project_name, cfg)
    return cfg


# ---------------------------------------------------------------------------
# Language / keys endpoints
# ---------------------------------------------------------------------------

@app.get("/api/projects/{project_name}/keys")
async def api_get_keys(project_name: str):
    """Return all translatable keys from the master file."""
    master = get_master_file(project_name)
    if not master or not master.exists():
        raise HTTPException(404, "Master file not found")
    flat = parse_file(str(master))
    # Only return string values (skip functions etc.)
    return {
        k: v for k, v in flat.items()
        if isinstance(v, str)
    }


@app.get("/api/projects/{project_name}/status")
async def api_project_status(project_name: str):
    """Return per-language translation status."""
    cfg = load_project_config(project_name)
    project_dir = str(get_project_dir(project_name))
    states = get_all_lang_states(project_dir)

    master_file = get_master_file(project_name)
    total_keys = 0
    if master_file and master_file.exists():
        flat = parse_file(str(master_file))
        total_keys = sum(
            1 for v in flat.values()
            if isinstance(v, str) or (isinstance(v, dict) and v.get("__type__") == "function")
        )

    result = {}
    languages = cfg.get("languages", {})
    for code, lang_info in languages.items():
        if lang_info.get("is_master"):
            continue
        state = states.get(code, {"status": "idle", "progress": {"done": 0, "total": total_keys}, "translated": {}})
        translated_count = len(state.get("translated", {}))
        result[code] = {
            **lang_info,
            "status": state.get("status", "idle"),
            "progress": state.get("progress", {"done": 0, "total": total_keys}),
            "translated_keys": translated_count,
            "total_keys": total_keys,
            "percent": round(100 * translated_count / total_keys, 1) if total_keys else 0,
            "last_updated": state.get("last_updated"),
            "error": state.get("error"),
        }
    return result


# ---------------------------------------------------------------------------
# Translation endpoints
# ---------------------------------------------------------------------------

class TranslateRequest(BaseModel):
    lang_codes: list[str] | None = None   # None = all non-master, non-skipped
    resume: bool = True                    # Resume from saved state


@app.post("/api/projects/{project_name}/translate")
async def api_start_translation(
    project_name: str,
    req: TranslateRequest,
    background_tasks: BackgroundTasks,
):
    cfg = load_project_config(project_name)
    master_file = get_master_file(project_name)
    if not master_file or not master_file.exists():
        raise HTTPException(404, "Master file not found")

    all_lang_keys: dict[str, str] = {}
    for _k, _v in parse_file(str(master_file)).items():
        if isinstance(_v, str):
            all_lang_keys[_k] = _v
        elif isinstance(_v, dict) and _v.get("__type__") == "function":
            all_lang_keys[_k] = _v["body"]  # send raw body (e.g. `%${x} text`) to LLM

    languages = cfg.get("languages", {})
    skip = set(cfg.get("skip_langs", []))
    master_code = cfg.get("master_lang", "tr")

    # Determine which languages to translate
    target_codes = req.lang_codes
    if target_codes is None:
        target_codes = [
            code for code, info in languages.items()
            if not info.get("is_master") and code not in skip and code != master_code
        ]

    started = []
    for code in target_codes:
        task_key = f"{project_name}:{code}"
        if task_key in _active_tasks and not _active_tasks[task_key].done():
            continue  # Already running

        task = asyncio.create_task(
            _run_translation(
                project_name=project_name,
                lang_code=code,
                all_keys=all_lang_keys,
                cfg=cfg,
                resume=req.resume,
                master_file=str(master_file),
            )
        )
        _active_tasks[task_key] = task
        started.append(code)

    return {"started": started, "total_keys": len(all_lang_keys)}


@app.post("/api/projects/{project_name}/translate/{lang_code}/stop")
async def api_stop_translation(project_name: str, lang_code: str):
    task_key = f"{project_name}:{lang_code}"
    task = _active_tasks.get(task_key)
    if task and not task.done():
        task.cancel()
        project_dir = str(get_project_dir(project_name))
        update_lang_state(project_dir, lang_code, {"status": "idle"})
        return {"stopped": True}
    return {"stopped": False}


@app.post("/api/projects/{project_name}/translate/{lang_code}/reset")
async def api_reset_translation(project_name: str, lang_code: str):
    """Clear saved translations for a language (start fresh)."""
    task_key = f"{project_name}:{lang_code}"
    task = _active_tasks.get(task_key)
    if task and not task.done():
        task.cancel()
    project_dir = str(get_project_dir(project_name))
    update_lang_state(project_dir, lang_code, {
        "status": "idle",
        "progress": {"done": 0, "total": 0},
        "translated": {},
        "error": None,
    })
    return {"reset": True}


@app.get("/api/projects/{project_name}/translate/{lang_code}/state")
async def api_lang_state(project_name: str, lang_code: str):
    project_dir = str(get_project_dir(project_name))
    return get_lang_state(project_dir, lang_code)


@app.post("/api/projects/{project_name}/write/{lang_code}")
async def api_write_output(project_name: str, lang_code: str):
    """Write the translated output file for a language."""
    project_dir = str(get_project_dir(project_name))
    lang_state = get_lang_state(project_dir, lang_code)
    translations = lang_state.get("translated", {})
    if not translations:
        raise HTTPException(400, "No translations available for this language yet")

    cfg = load_project_config(project_name)
    master_file = get_master_file(project_name)
    if not master_file:
        raise HTTPException(404, "Master file not found")

    languages = cfg.get("languages", {})
    lang_info = languages.get(lang_code, {})
    lang_filename = lang_info.get("file", f"{lang_code}{master_file.suffix}")
    lang_dir = get_languages_dir(project_name)
    target_path = lang_dir / lang_filename

    write_output_file(str(master_file), str(target_path), translations, lang_code)
    return {"written": str(target_path)}


# ---------------------------------------------------------------------------
# Ollama check
# ---------------------------------------------------------------------------

@app.get("/api/ollama/check")
async def api_check_ollama(url: str = "http://localhost:11434", model: str = "gpt-oss:20b"):
    return await check_ollama_connection(url, model)


@app.get("/api/ollama/models")
async def api_ollama_models(url: str = "http://localhost:11434"):
    """Return an alphabetically sorted list of models available from the Ollama instance."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{url.rstrip('/')}/api/tags")
            r.raise_for_status()
            models = sorted(m["name"] for m in r.json().get("models", []))
            return {"models": models}
    except Exception as exc:
        return {"models": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Background translation task
# ---------------------------------------------------------------------------

async def _run_translation(
    project_name: str,
    lang_code: str,
    all_keys: dict[str, str],
    cfg: dict,
    resume: bool,
    master_file: str,
):
    project_dir = str(get_project_dir(project_name))
    ollama_url = cfg.get("ollama_url", "http://localhost:11434")
    model = cfg.get("model", "gpt-oss:20b")
    batch_size = cfg.get("batch_size", 25)
    master_code = cfg.get("master_lang", "tr")
    source_lang_name = get_lang_name(master_code) or cfg.get("source_lang_name", "Turkish")

    target_lang_name = await get_lang_name_async(lang_code, ollama_url, model)

    # Load previously translated keys if resuming
    existing_state = get_lang_state(project_dir, lang_code)
    already_translated: dict[str, str] = {}
    if resume:
        already_translated = existing_state.get("translated", {})

    # Only translate keys not yet done
    pending = {k: v for k, v in all_keys.items() if k not in already_translated}

    total = len(all_keys)
    done_so_far = len(already_translated)

    update_lang_state(project_dir, lang_code, {
        "status": "running",
        "progress": {"done": done_so_far, "total": total},
        "error": None,
    })

    # Determine output path up front (needed for incremental writes)
    languages = cfg.get("languages", {})
    lang_info = languages.get(lang_code, {})
    master_path = Path(master_file)
    lang_filename = lang_info.get("file", f"{lang_code}{master_path.suffix}")
    from project_config import get_languages_dir
    lang_dir = get_languages_dir(project_name)
    target_path = lang_dir / lang_filename

    try:
        async def on_progress(done_in_batch: int, total_in_batch: int, batch_result: dict):
            nonlocal done_so_far
            done_so_far = len(already_translated) + done_in_batch
            update_translated_keys(project_dir, lang_code, batch_result)
            update_progress(project_dir, lang_code, done_so_far, total)
            # Incremental write: update the output file after every batch
            current_translations = get_lang_state(project_dir, lang_code).get("translated", {})
            write_output_file(master_file, str(target_path), current_translations, lang_code)

        if pending:
            new_translations = await translate_batch(
                keys_values=pending,
                target_lang=target_lang_name,
                source_lang=source_lang_name,
                ollama_url=ollama_url,
                model=model,
                batch_size=batch_size,
                on_progress=on_progress,
            )
            update_translated_keys(project_dir, lang_code, new_translations)

        # Merge all
        final_translations = {**already_translated}
        if pending:
            final_translations.update(new_translations)

        # Auto-write final output file
        write_output_file(master_file, str(target_path), final_translations, lang_code)

        update_lang_state(project_dir, lang_code, {
            "status": "done",
            "progress": {"done": total, "total": total},
        })

    except asyncio.CancelledError:
        update_lang_state(project_dir, lang_code, {"status": "idle"})
        raise
    except Exception as e:
        update_lang_state(project_dir, lang_code, {
            "status": "error",
            "error": str(e),
        })


# ---------------------------------------------------------------------------
# Language management
# ---------------------------------------------------------------------------

class CreateLanguageRequest(BaseModel):
    code: str
    name: str | None = None


@app.post("/api/projects/{project_name}/languages")
async def api_create_language(project_name: str, req: CreateLanguageRequest):
    """Create a new language file (copy of master) and register it in project config."""
    import re as _re
    code = req.code.strip().lower()
    if not _re.match(r'^[a-z]{2,10}$', code):
        raise HTTPException(400, "Language code must be 2-10 lowercase letters")

    cfg = load_project_config(project_name)
    if code in cfg.get("languages", {}):
        raise HTTPException(409, f"Language '{code}' already exists in this project")

    master_file = get_master_file(project_name)
    if not master_file or not master_file.exists():
        raise HTTPException(404, "Master file not found")

    # Determine display name
    lang_name = (req.name or "").strip() or await get_lang_name_async(code, cfg.get("ollama_url", "http://localhost:11434"), cfg.get("model", "gpt-oss:20b"))

    # Build target path next to master
    lang_dir = get_languages_dir(project_name)
    new_file = lang_dir / f"{code}{master_file.suffix}"
    if new_file.exists():
        raise HTTPException(409, f"File {new_file.name} already exists on disk")

    # Copy master, replace header comment + export identifier
    master_text = master_file.read_text(encoding="utf-8")
    suffix = master_file.suffix.lower()
    if suffix in (".ts", ".js"):
        # Replace everything before the first {  (comment + export const xxx =)
        new_text = _re.sub(
            r'^((?://[^\n]*\n)*)export\s+const\s+\w+\s*=',
            f'// {lang_name}\nexport const {code} =',
            master_text,
            count=1,
            flags=_re.MULTILINE,
        )
    elif suffix == ".py":
        new_text = _re.sub(
            r'^((?:#[^\n]*\n)*)\w+\s*=',
            f'# {lang_name}\n{code} =',
            master_text,
            count=1,
            flags=_re.MULTILINE,
        )
    else:
        new_text = master_text

    lang_dir.mkdir(parents=True, exist_ok=True)
    new_file.write_text(new_text, encoding="utf-8")

    # Register in config
    cfg.setdefault("languages", {})[code] = {
        "code": code,
        "name": lang_name,
        "file": new_file.name,
        "is_master": False,
    }
    save_project_config(project_name, cfg)

    return {"code": code, "name": lang_name, "file": new_file.name}


@app.get("/api/projects/{project_name}/diff")
async def api_diff(project_name: str):
    """Return per-language count of new (un-translated) keys vs current master."""
    master_file = get_master_file(project_name)
    if not master_file or not master_file.exists():
        raise HTTPException(404, "Master file not found")

    master_keys: set[str] = {
        k for k, v in parse_file(str(master_file)).items()
        if isinstance(v, str) or (isinstance(v, dict) and v.get("__type__") == "function")
    }
    project_dir = str(get_project_dir(project_name))
    states = get_all_lang_states(project_dir)
    cfg = load_project_config(project_name)

    result = {}
    for code, info in cfg.get("languages", {}).items():
        if info.get("is_master"):
            continue
        translated_keys = set(states.get(code, {}).get("translated", {}).keys())
        new_count = len(master_keys - translated_keys)
        result[code] = {
            "new_keys": new_count,
            "total_keys": len(master_keys),
        }
    return result


@app.post("/api/projects/{project_name}/check-clones/{lang_code}")
async def api_check_clones(project_name: str, lang_code: str):
    """
    Compare translated values for a language with the master language values.
    Checks BOTH the persisted state and the actual language file on disk.
    Remove any keys from state where the translated value exactly matches the master value
    (indicating the translation failed and just cloned the original).
    """
    master_file = get_master_file(project_name)
    if not master_file or not master_file.exists():
        raise HTTPException(404, "Master file not found")

    cfg = load_project_config(project_name)
    if lang_code == cfg.get("master_lang"):
        raise HTTPException(400, "Cannot check clones for master language")

    master_flat = parse_file(str(master_file))
    # Only consider string values for clone detection
    master_values = {k: v for k, v in master_flat.items() if isinstance(v, str)}

    project_dir = str(get_project_dir(project_name))
    state = get_lang_state(project_dir, lang_code)
    translated = state.get("translated", {})

    # 1. Check clones in state
    state_clones = {k for k, v in translated.items() if k in master_values and v == master_values[k]}

    # 2. Check clones in the actual language file on disk
    lang_dir = get_languages_dir(project_name)
    lang_info = cfg.get("languages", {}).get(lang_code, {})
    lang_filename = lang_info.get("file", f"{lang_code}{master_file.suffix}")
    lang_file = lang_dir / lang_filename

    file_clones: set[str] = set()
    if lang_file.exists():
        try:
            file_flat = parse_file(str(lang_file))
            file_values = {k: v for k, v in file_flat.items() if isinstance(v, str)}
            file_clones = {k for k, v in file_values.items() if k in master_values and v == master_values[k]}
        except Exception:
            pass

    # Combine clones from both state and file
    all_clones = sorted(state_clones | file_clones)

    # Remove from state any that are present there
    if state_clones:
        new_translated = {k: v for k, v in translated.items() if k not in state_clones}
        update_lang_state(project_dir, lang_code, {
            "translated": new_translated,
            "progress": {"done": len(new_translated), "total": len(master_values)},
        })

    return {"removed": len(state_clones), "keys": all_clones}


# ---------------------------------------------------------------------------
# Serve Web UI
# ---------------------------------------------------------------------------

UI_DIR = Path(__file__).parent.parent / "ui"


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    index = UI_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>TranslationHero UI not found</h1>")
