"""Source-patching helpers for self_evolve --apply.

Split out of self_evolve.py to keep that file under the 700-line cap. These
helpers are only executed on the `--apply` code path; the evolution loop
itself does not depend on them. Pure utility module — no API calls, no
global state.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from shared import log_stderr as _log

if TYPE_CHECKING:
    from self_evolve import PromptEntry


def apply_results(
    results: list[dict],
    catalog: "list[PromptEntry]",
    py_source: Path,
    md_source: Path,
) -> int:
    """Apply winning prompts to their source files. Returns patch count."""
    patched = 0
    entry_map = {e.name: e for e in catalog}
    py_content = py_source.read_text() if py_source.is_file() else ""
    md_content = md_source.read_text() if md_source.is_file() else ""

    for result in results:
        if not result["improved"]:
            continue
        entry = entry_map.get(result["name"])
        if not entry:
            continue

        if entry.source_type == "python_constant":
            new_py = patch_python_constant(py_content, entry.source_key, result["best"])
            if new_py != py_content:
                py_content = new_py
                patched += 1
                _log(f"  Patched Python: {entry.source_key}")
        elif entry.source_type == "markdown_section":
            new_md = replace_markdown_section(md_content, entry.source_key, result["best"])
            if new_md != md_content:
                md_content = new_md
                patched += 1
                _log(f"  Patched SKILL.md: {entry.source_key}")

    if patched > 0:
        if py_source.is_file():
            py_source.write_text(py_content)
        if md_source.is_file():
            md_source.write_text(md_content)
        _log(f"\n{patched} prompt(s) patched. Review: git diff")

    return patched


def replace_markdown_section(content: str, heading: str, new_body: str) -> str:
    """Replace a markdown section body, keeping the heading line intact."""
    pattern = re.compile(rf'^(#{{2,4}}\s+{re.escape(heading)}[ \t]*\n)', re.MULTILINE)
    match = pattern.search(content)
    if not match:
        return content

    level = len(re.match(r'^(#{2,4})', match.group(1)).group(1))
    heading_end = match.end()
    next_pattern = re.compile(rf'^#{{{1},{level}}}\s+', re.MULTILINE)
    next_match = next_pattern.search(content, heading_end)

    if next_match:
        return content[:heading_end] + "\n" + new_body + "\n\n" + content[next_match.start():]
    return content[:heading_end] + "\n" + new_body + "\n"


def patch_python_constant(content: str, const_name: str, new_value: str) -> str:
    """Replace a parenthesized `NAME = (\\n...\\n)` Python constant.

    Only matches the parenthesized multiline form (the one self_evolve
    generates via `format_python_constant`). Single-line and triple-quote
    formats are NOT supported — logs a warning and returns unchanged.
    """
    pattern = re.compile(rf'^{const_name} = \(\n(.*?)\n\)', re.MULTILINE | re.DOTALL)
    match = pattern.search(content)
    if not match:
        _log(f"  WARNING: {const_name} not found in source")
        return content

    formatted = format_python_constant(const_name, new_value)
    return content[:match.start()] + formatted + content[match.end():]


def format_python_constant(name: str, value: str) -> str:
    """Format a string as a parenthesized Python constant literal.

    Escapes backslash/quote/CR/LF/TAB so control chars in generated variants
    don't produce unterminated string literals when spliced into source.
    """
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    lines: list[str] = []
    remaining = escaped
    while remaining:
        if len(remaining) <= 85:
            lines.append(remaining)
            break
        split_at = remaining.rfind(" ", 0, 85)
        split_at = split_at + 1 if split_at != -1 else 85
        lines.append(remaining[:split_at])
        remaining = remaining[split_at:]

    if len(lines) == 1:
        return f'{name} = (\n    "{lines[0]}"\n)'
    parts = [f'{name} = ('] + [f'    "{ln}"' for ln in lines] + [")"]
    return "\n".join(parts)
