"""
Output file writer.
Rebuilds target translation files preserving source structure.
"""

from pathlib import Path
import re
import json

from project_config import get_lang_name


def write_output_file(
    source_path: str,
    target_path: str,
    translations: dict[str, str],
    lang_code: str,
) -> None:
    suffix = Path(source_path).suffix.lower()
    if suffix in (".ts", ".js"):
        _write_ts_js(source_path, target_path, translations, lang_code)
    elif suffix == ".json":
        _write_json(source_path, target_path, translations)
    elif suffix == ".py":
        _write_python(source_path, target_path, translations, lang_code)
    else:
        raise ValueError(f"Unsupported format: {suffix}")


# ---------------------------------------------------------------------------
# TS/JS writer — line-by-line reconstruction preserving comments & structure
# ---------------------------------------------------------------------------

def _write_ts_js(source_path: str, target_path: str, translations: dict, lang_code: str) -> None:
    source_text = Path(source_path).read_text(encoding="utf-8")
    lang_name = get_lang_name(lang_code)

    # Find the object content
    brace_start = source_text.index("{")
    brace_end = _find_matching_brace(source_text, brace_start)
    object_body = source_text[brace_start + 1 : brace_end]

    translated_body = _translate_lines(object_body, [], translations)

    output = f"// {lang_name}\nexport const {lang_code} = {{{translated_body}}};\n"

    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    Path(target_path).write_text(output, encoding="utf-8")


def _find_matching_brace(text: str, start: int) -> int:
    depth = 0
    in_str = None
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < len(text):
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ('"', "'", "`"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return len(text) - 1


def _translate_lines(body: str, key_stack: list[str], translations: dict) -> str:
    """
    Line-by-line pass. Handles:
    - String values:    key: 'value',
    - Nested objects:   key: {
    - Comments:         // ...
    - Arrow functions:  key: (x) => `...`
    - Closing braces:   },
    """
    lines = body.split("\n")
    result = []
    stack = list(key_stack)  # copy

    # Multi-line string detection not needed – source files are one-liner values

    for line in lines:
        stripped = line.strip()

        # Blank or comment lines – keep verbatim
        if not stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            result.append(line)
            continue

        # Closing brace (end of nested object)
        if re.match(r"^\},?$", stripped):
            if stack:
                stack.pop()
            result.append(line)
            continue

        # Single-line inline object:  key: {k: "v", k: "v"},  (no nested braces)
        inline_obj_m = re.match(r'^(\s*)(\w+)\s*:\s*(\{[^{}]*\}),?\s*(//.*)?$', line)
        if inline_obj_m:
            leading    = inline_obj_m.group(1)
            key_raw    = inline_obj_m.group(2)
            inner      = inline_obj_m.group(3)  # "{k: \"v\", ...}"
            comment    = inline_obj_m.group(4) or ""
            obj_prefix = ".".join(stack + [key_raw])
            def _sub(m, _prefix=obj_prefix):
                ik = m.group(1)
                q  = m.group(2)
                t  = translations.get(f"{_prefix}.{ik}")
                if t is not None:
                    esc = (t.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace(q, f"\\{q}"))
                    return f'{ik}: {q}{esc}{q}'
                return m.group(0)
            new_inner = re.sub(r"(\w+)\s*:\s*(['\"`])(.*?)\2", _sub, inner)
            comment_part = f"  {comment}" if comment else ""
            result.append(f"{leading}{key_raw}: {new_inner},{comment_part}")
            continue

        # Nested object opener:   key: {   or   key: {  // comment
        obj_open = re.match(r"^(\s*)(\w+|'[^']+'|\"[^\"]+\")\s*:\s*\{", line)
        if obj_open:
            key_raw = obj_open.group(2).strip("'\"")
            stack.append(key_raw)
            result.append(line)
            continue

        # String value:  key: 'value',   or   key: "value",   or   key: `value`,
        str_val = re.match(
            r"^(\s*)(\w+|'[^']+'|\"[^\"]+\")\s*:\s*(['\"`])(.*?)(\3)\s*,?\s*(//.*)?$",
            line,
        )
        if str_val:
            leading   = str_val.group(1)
            key_raw   = str_val.group(2).strip("'\"")
            quote     = str_val.group(3)
            comment   = str_val.group(6) or ""
            dot_key   = ".".join(stack + [key_raw])

            translated = translations.get(dot_key)
            if translated is not None:
                escaped = (
                    translated
                    .replace("\\", "\\\\")
                    .replace("\n", "\\n")
                    .replace("\t", "\\t")
                    .replace(quote, f"\\{quote}")
                )
                comment_part = f"  {comment}" if comment else ""
                result.append(f"{leading}{key_raw}: {quote}{escaped}{quote},{comment_part}")
            else:
                result.append(line)
            continue

        # Arrow function:  key: (params) => body,  [optional comment]
        if ') =>' in line:
            fn_match = re.match(r'^(\s*)(\w+)\s*:\s*(\([^)]*\)\s*=>\s*)', line)
            if fn_match:
                leading     = fn_match.group(1)
                key_raw     = fn_match.group(2)
                params_part = fn_match.group(3)  # "(name: string) => "
                dot_key     = ".".join(stack + [key_raw])
                translated  = translations.get(dot_key)
                if translated is not None:
                    # Preserve any trailing inline comment from the source line
                    rest = line[fn_match.end():].rstrip()
                    comment_m = re.search(r'\s*//.*$', rest)
                    comment_part = f"  {comment_m.group(0).strip()}" if comment_m else ""
                    # If source body used a template literal, ensure outer backticks and clean inner ones
                    src_body = rest.lstrip()
                    if src_body.startswith('`'):
                        # Strip outer backticks if LLM added them (we'll re-add cleanly)
                        inner = translated.strip('`') if translated else translated
                        # Remove any spurious backticks the LLM inserted around ${...} interpolations
                        # e.g. `${username}` → ${username}
                        inner = re.sub(r'`(\$\{[^}]+\})`', r'\1', inner) if inner else inner
                        # Also strip any remaining lone backticks inside the body
                        inner = inner.replace('`', '') if inner else inner
                        translated = f'`{inner}`'
                    result.append(f"{leading}{key_raw}: {params_part}{translated},{comment_part}")
                else:
                    result.append(line)
                continue

        # Everything else (booleans, numbers, arrays, multi-param fns) – keep verbatim
        result.append(line)

    return "\n".join(result)


# ---------------------------------------------------------------------------
# JSON writer
# ---------------------------------------------------------------------------

def _write_json(source_path: str, target_path: str, translations: dict) -> None:
    source_data = json.loads(Path(source_path).read_text(encoding="utf-8"))
    result = _apply_to_nested(source_data, [], translations)
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    Path(target_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _apply_to_nested(data: dict, key_stack: list, translations: dict) -> dict:
    result = {}
    for key, val in data.items():
        dot_key = ".".join(key_stack + [key])
        if isinstance(val, dict):
            result[key] = _apply_to_nested(val, key_stack + [key], translations)
        elif isinstance(val, str):
            result[key] = translations.get(dot_key, val)
        else:
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Python writer
# ---------------------------------------------------------------------------

def _write_python(source_path: str, target_path: str, translations: dict, lang_code: str) -> None:
    source_text = Path(source_path).read_text(encoding="utf-8")
    lang_name = get_lang_name(lang_code)

    brace_start = source_text.index("{")
    brace_end = _find_matching_brace(source_text, brace_start)
    object_body = source_text[brace_start + 1 : brace_end]

    translated_body = _translate_lines(object_body, [], translations)
    output = f"# {lang_name}\n{lang_code} = {{{translated_body}}}\n"

    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    Path(target_path).write_text(output, encoding="utf-8")
