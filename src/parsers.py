"""
File parsers for extracting and writing translation key/value pairs.
Supports: .ts, .js (TypeScript/JavaScript object exports), .json, .py
"""

import re
import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_file(file_path: str) -> dict[str, Any]:
    """Parse a translation file and return a flat dict of dotted key paths → values."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix in (".ts", ".js"):
        return _parse_ts_js(path)
    elif suffix == ".json":
        return _parse_json(path)
    elif suffix == ".py":
        return _parse_python(path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")


def write_translated_file(
    source_path: str,
    target_path: str,
    translations: dict[str, str],
    target_lang_code: str,
) -> None:
    """
    Write a translated file that mirrors the structure of source_path,
    substituting string values from `translations` (dotted-key → translated string).
    """
    path = Path(source_path)
    suffix = path.suffix.lower()

    if suffix in (".ts", ".js"):
        _write_ts_js(path, Path(target_path), translations, target_lang_code)
    elif suffix == ".json":
        _write_json(path, Path(target_path), translations)
    elif suffix == ".py":
        _write_python(path, Path(target_path), translations, target_lang_code)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")


# ---------------------------------------------------------------------------
# TS / JS  parser & writer
# ---------------------------------------------------------------------------

def _parse_ts_js(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    # Extract the object body between the first { ... }
    body = _extract_object_body(text)
    return _parse_object_text(body, "")


def _extract_object_body(text: str) -> str:
    """Return the content between the outermost export { ... }."""
    start = text.index("{")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    raise ValueError("Could not find object body in file")


def _parse_object_text(text: str, prefix: str) -> dict[str, Any]:
    """Recursively parse TS/JS object literal text into flat dotted keys."""
    result: dict[str, Any] = {}

    # Tokenise into key: value pairs at the current nesting level
    i = 0
    text = text.strip()
    length = len(text)

    while i < length:
        # Skip whitespace and comments
        i = _skip_whitespace_and_comments(text, i)
        if i >= length:
            break

        # Read key
        key, i = _read_key(text, i)
        if key is None:
            break

        # Skip whitespace + colon
        i = _skip_whitespace_and_comments(text, i)
        if i < length and text[i] == ":":
            i += 1
        i = _skip_whitespace_and_comments(text, i)

        full_key = f"{prefix}.{key}" if prefix else key

        # Determine value type
        val, i, val_type = _read_value(text, i)

        if val_type == "object":
            # Recurse into nested object
            nested = _parse_object_text(val, full_key)
            result.update(nested)
        elif val_type == "function":
            # Store params and body separately; body will be sent to the translator
            idx = val.find("=>")
            if idx != -1:
                params = val[:idx + 2].rstrip()   # e.g. "(name: string) =>"
                body   = val[idx + 2:].lstrip()   # e.g. "`text with ${name}`"
            else:
                params, body = "", val
            result[full_key] = {"__type__": "function", "params": params, "body": body}
        elif val_type == "string":
            result[full_key] = val
        # Skip other types (numbers, booleans, null, arrays of non-strings)

        # Skip trailing comma
        i = _skip_whitespace_and_comments(text, i)
        if i < length and text[i] == ",":
            i += 1

    return result


def _skip_whitespace_and_comments(text: str, i: int) -> int:
    length = len(text)
    while i < length:
        if text[i] in " \t\n\r":
            i += 1
        elif text[i : i + 2] == "//":
            # Line comment
            end = text.find("\n", i)
            i = end + 1 if end != -1 else length
        elif text[i : i + 2] == "/*":
            end = text.find("*/", i + 2)
            i = end + 2 if end != -1 else length
        else:
            break
    return i


def _read_key(text: str, i: int) -> tuple[str | None, int]:
    length = len(text)
    if i >= length:
        return None, i

    ch = text[i]
    # Quoted key
    if ch in ('"', "'", "`"):
        quote = ch
        i += 1
        start = i
        while i < length and text[i] != quote:
            if text[i] == "\\" :
                i += 2
            else:
                i += 1
        key = text[start:i]
        i += 1  # closing quote
        return key, i

    # Unquoted identifier key
    if ch.isalpha() or ch == "_" or ch == "$":
        start = i
        while i < length and (text[i].isalnum() or text[i] in "_$"):
            i += 1
        return text[start:i], i

    return None, i


def _read_value(text: str, i: int) -> tuple[Any, int, str]:
    """Returns (value, new_i, type_str) where type_str in 'string','object','function','other'."""
    length = len(text)
    i = _skip_whitespace_and_comments(text, i)

    if i >= length:
        return None, i, "other"

    ch = text[i]

    # String literal
    if ch in ('"', "'", "`"):
        val, i = _read_string(text, i)
        return val, i, "string"

    # Nested object
    if ch == "{":
        body, i = _read_balanced(text, i, "{", "}")
        return body[1:-1], i, "object"

    # Arrow function  e.g.  (x: number) => `...`  or  (name: string) => `...`
    if ch == "(":
        fn_src, i = _extract_arrow_function(text, i)
        return fn_src, i, "function"

    # true / false / number  – skip
    start = i
    while i < length and text[i] not in (",", "\n", "}"):
        i += 1
    return text[start:i].strip(), i, "other"


def _read_string(text: str, i: int) -> tuple[str, int]:
    quote = text[i]
    i += 1
    parts = []
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            esc = text[i + 1] if i + 1 < len(text) else ""
            escape_map = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "`": "`", "\\": "\\"}
            parts.append(escape_map.get(esc, esc))
            i += 2
        elif ch == quote:
            i += 1
            break
        else:
            parts.append(ch)
            i += 1
    return "".join(parts), i


def _read_balanced(text: str, i: int, open_ch: str, close_ch: str) -> tuple[str, int]:
    depth = 0
    start = i
    length = len(text)
    in_str = None
    while i < length:
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < length:
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ('"', "'", "`"):
                in_str = ch
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1], i + 1
        i += 1
    return text[start:], length


def _extract_arrow_function(text: str, i: int) -> tuple[str, int]:
    """Extract an arrow function expression like (x: Type) => `...` or 'string'."""
    start = i
    # Read params
    _, i = _read_balanced(text, i, "(", ")")
    i = _skip_whitespace_and_comments(text, i)
    # Expect =>
    if text[i : i + 2] == "=>":
        i += 2
    i = _skip_whitespace_and_comments(text, i)
    # Read body: either a string literal, a template literal, or a { block }
    ch = text[i]
    if ch in ('"', "'", "`"):
        _, i = _read_string(text, i)
    elif ch == "{":
        _, i = _read_balanced(text, i, "{", "}")
    return text[start:i], i


def _write_ts_js(source: Path, target: Path, translations: dict[str, str], lang_code: str) -> None:
    """Rebuild a TS/JS file from source structure with translated values."""
    source_text = source.read_text(encoding="utf-8")

    # Determine the export const name from source to rename it
    const_match = re.search(r"export\s+const\s+(\w+)\s*=", source_text)
    original_const = const_match.group(1) if const_match else "translations"

    # Build translated object text
    body = _extract_object_body(source_text)
    translated_body = _translate_object_text(body, "", translations)

    # Determine comment header
    lang_name = _lang_name_from_code(lang_code)
    header = f"// {lang_name}\nexport const {lang_code} = {{\n{translated_body}\n}};\n"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(header, encoding="utf-8")


def _translate_object_text(text: str, prefix: str, translations: dict[str, str]) -> str:
    """Rebuild object text substituting translated values, preserving structure & comments."""
    result_lines = []
    i = 0
    text_stripped = text
    length = len(text_stripped)
    indent = "  "

    # We'll do a line-by-line reconstruction preserving comments
    lines = text.split("\n")
    current_prefix = prefix
    prefix_stack = [prefix]
    key_stack = []

    for line in lines:
        stripped = line.strip()

        # Pure comment or blank – keep
        if not stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            result_lines.append(line)
            continue

        # Nested object close
        if stripped in ("}", "},"):
            if key_stack:
                key_stack.pop()
            result_lines.append(line)
            continue

        # Try to match   key: 'value',   or   key: "value",
        str_match = re.match(
            r"^(\s*)(\w+|'[^']+'|\"[^\"]+\")\s*:\s*(['\"`])(.*?)(\3)\s*,?\s*$",
            line,
        )
        if str_match:
            leading = str_match.group(1)
            key_raw = str_match.group(2).strip("'\"")
            quote = str_match.group(3)
            full_key = ".".join(key_stack + [key_raw]) if key_stack else key_raw
            if prefix:
                lookup = f"{prefix}.{full_key}"
            else:
                lookup = full_key

            translated = translations.get(lookup)
            if translated is not None:
                # Escape quotes in translated value
                escaped = translated.replace("\\", "\\\\").replace(quote, f"\\{quote}")
                result_lines.append(f"{leading}{key_raw}: {quote}{escaped}{quote},")
            else:
                result_lines.append(line)
            continue

        # Nested object open   key: {
        obj_match = re.match(r"^(\s*)(\w+|'[^']+'|\"[^\"]+\")\s*:\s*\{", line)
        if obj_match:
            key_raw = obj_match.group(2).strip("'\"")
            key_stack.append(key_raw)
            result_lines.append(line)
            continue

        # Anything else (arrow functions, numbers, booleans) - keep as-is
        result_lines.append(line)

    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# JSON parser & writer
# ---------------------------------------------------------------------------

def _parse_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _flatten_dict(data, "")


def _write_json(source: Path, target: Path, translations: dict[str, str]) -> None:
    source_data = json.loads(source.read_text(encoding="utf-8"))
    result = _apply_translations_nested(source_data, "", translations)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def _flatten_dict(data: dict, prefix: str) -> dict[str, Any]:
    result = {}
    for key, val in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            result.update(_flatten_dict(val, full_key))
        elif isinstance(val, str):
            result[full_key] = val
        else:
            result[full_key] = val
    return result


def _apply_translations_nested(data: dict, prefix: str, translations: dict[str, str]) -> dict:
    result = {}
    for key, val in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            result[key] = _apply_translations_nested(val, full_key, translations)
        elif isinstance(val, str):
            result[key] = translations.get(full_key, val)
        else:
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Python parser & writer  (dict literal like  translations = { ... })
# ---------------------------------------------------------------------------

def _parse_python(path: Path) -> dict[str, Any]:
    # For Python files we use the same object-body extraction
    text = path.read_text(encoding="utf-8")
    # Find first { 
    try:
        body = _extract_object_body(text)
    except ValueError:
        return {}
    return _parse_object_text(body, "")


def _write_python(source: Path, target: Path, translations: dict[str, str], lang_code: str) -> None:
    source_text = source.read_text(encoding="utf-8")
    body = _extract_object_body(source_text)
    translated_body = _translate_object_text(body, "", translations)
    lang_name = _lang_name_from_code(lang_code)
    header = f"# {lang_name}\n{lang_code} = {{\n{translated_body}\n}}\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(header, encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LANG_NAMES = {
    "tr": "Turkish", "en": "English", "ar": "Arabic", "az": "Azerbaijani",
    "bn": "Bengali", "bs": "Bosnian", "fa": "Persian", "fr": "French",
    "hi": "Hindi", "id": "Indonesian", "kk": "Kazakh", "ku": "Kurdish",
    "ky": "Kyrgyz", "ms": "Malay", "ru": "Russian", "sq": "Albanian",
    "tg": "Tajik", "tk": "Turkmen", "ur": "Urdu", "uz": "Uzbek",
}


def _lang_name_from_code(code: str) -> str:
    return LANG_NAMES.get(code, code.upper())
