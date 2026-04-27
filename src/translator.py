"""
Ollama translation engine with batched requests.
Sends N keys at a time to avoid context limits.
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
import httpx
from typing import Any


DEFAULT_BATCH_SIZE = 25


async def translate_batch(
    keys_values: dict[str, str],
    target_lang: str,
    source_lang: str,
    ollama_url: str,
    model: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_progress=None,  # async callable(done, total)
) -> dict[str, str]:
    """
    Translate a dict of {key: source_text} to target_lang.
    Returns {key: translated_text}.
    Processes in batches of batch_size.
    """
    items = list(keys_values.items())
    results: dict[str, str] = {}
    total = len(items)
    done = 0

    for start in range(0, total, batch_size):
        chunk = items[start : start + batch_size]
        chunk_result = await _translate_chunk(
            chunk, target_lang, source_lang, ollama_url, model
        )
        results.update(chunk_result)
        done += len(chunk)
        if on_progress:
            await on_progress(done, total, chunk_result)

    return results


async def _translate_chunk(
    chunk: list[tuple[str, str]],
    target_lang: str,
    source_lang: str,
    ollama_url: str,
    model: str,
    retries: int = 3,
) -> dict[str, str]:
    """Send one batch to Ollama and parse the response."""
    # Build a numbered list so the model returns structured data
    numbered = {str(i + 1): {"key": k, "text": v} for i, (k, v) in enumerate(chunk)}
    input_json = json.dumps(
        {str(i + 1): v["text"] for i, (_, v) in enumerate(numbered.items())},
        ensure_ascii=False,
        indent=2,
    )

    prompt = f"""You are a professional translator. Translate the following JSON object values from {source_lang} to {target_lang}.

RULES:
- Preserve the JSON structure exactly (same keys, same order)
- Only translate the string values, do NOT change the keys
- Keep placeholders like ${{variable}}, %s, %d, {{name}} unchanged
- Keep punctuation style consistent with the target language
- Return ONLY valid JSON, no markdown, no explanation

Input:
{input_json}

Output (valid JSON only):"""

    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{ollama_url.rstrip('/')}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "num_predict": 4096,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                raw_text = data.get("response") or data.get("thinking", "")

            _log_ollama_response(
                data=data,
                raw_text=raw_text,
                source_lang=source_lang,
                target_lang=target_lang,
                model=model,
                ollama_url=ollama_url,
            )

            translated_map = _parse_json_response(raw_text)
            if not translated_map:
                raise ValueError("Empty or unparseable response from model")

            # Map back from numbered positions to original keys
            result = {}
            for idx_str, item in numbered.items():
                key = item["key"]
                translated = translated_map.get(idx_str)
                if translated and isinstance(translated, str):
                    result[key] = translated
                else:
                    raise ValueError(f"Model did not return a translation for key '{item['key']}'")
            return result

        except (httpx.HTTPError, ValueError, KeyError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                raise RuntimeError(f"Translation failed after {retries} attempts: {e}") from e

    return {k: v for k, v in chunk}


def _parse_json_response(text: str) -> dict:
    """Extract and parse JSON from a potentially noisy model response."""
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = text.strip("`").strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find first {...} block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Fallback: parse numbered translation lines such as "1": "source" -> "target"
    fallback = _parse_numbered_translation_lines(text)
    if fallback:
        return fallback

    return {}


def _parse_numbered_translation_lines(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in re.finditer(
        r'"(\d+)"\s*:\s*"((?:\\.|[^"\\])*)"\s*->\s*"((?:\\.|[^"\\])*)"',
        text,
    ):
        index = match.group(1)
        translated_text = match.group(3)
        try:
            translated_text = json.loads(f'"{translated_text}"')
        except json.JSONDecodeError:
            translated_text = translated_text.replace('\\"', '"')
        result[index] = translated_text
    return result


def _log_ollama_response(
    data: dict[str, Any],
    raw_text: str,
    source_lang: str,
    target_lang: str,
    model: str,
    ollama_url: str,
) -> None:
    """Append full Ollama request/response details to a log file."""
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "ollama.log"
    timestamp = datetime.now().isoformat(sep=" ", timespec="seconds")
    separator = "=" * 120
    entry = [
        separator,
        f"[{timestamp}] Ollama request",
        f"Source language: {source_lang}",
        f"Target language: {target_lang}",
        f"Model: {model}",
        f"Ollama URL: {ollama_url}",
        "Full response JSON:",
    ]
    try:
        entry.append(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        entry.append(repr(data))
    entry.extend([
        "Raw response text:",
        raw_text,
        separator,
        "\n",
    ])
    with log_file.open("a", encoding="utf-8") as f:
        f.write("\n".join(entry))


async def check_ollama_connection(ollama_url: str, model: str) -> dict:
    """Check if Ollama is reachable and the model is available."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Check tags endpoint
            r = await client.get(f"{ollama_url.rstrip('/')}/api/tags")
            r.raise_for_status()
            data = r.json()
            models = [m["name"] for m in data.get("models", [])]
            model_available = any(m == model or m.startswith(model.split(":")[0]) for m in models)
            return {
                "connected": True,
                "models": models,
                "model_available": model_available,
            }
    except Exception as e:
        return {"connected": False, "error": str(e), "models": [], "model_available": False}
