"""Session retrospective scanner.

Scan the previous Claude Code session JSONL file,
find complex tasks with 5+ tool calls not yet captured as skills.
Runs in Phase 0, outputs plain text report to stdout.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

# shared module from same directory
from shared import DRAFT_FILE, FILE_WRITE_TOOLS, TOOL_CALL_THRESHOLD


# ── core functions ────────────────────────────────────


def resolve_project_dir(cwd: str) -> Path:
    """Working directory to Claude Code project storage path.

    /Users/user/project -> ~/.claude/projects/-Users-user-project
    Replace / with -, ensure leading -.
    """
    slug = cwd.replace("/", "-")
    # paths without leading / still need - prefix
    if not slug.startswith("-"):
        slug = "-" + slug
    return Path.home() / ".claude" / "projects" / slug


def get_sessions_sorted(project_dir: Path) -> list[Path]:
    """Get JSONL file list sorted by mtime descending.

    Skip agent- prefixed files. Non-existent directory returns empty list.
    """
    if not project_dir.is_dir():
        return []
    files = [
        f
        for f in project_dir.glob("*.jsonl")
        if not f.name.startswith("agent-")
    ]
    # sort by mtime descending (newest first)
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files


def _extract_content_items(record: dict) -> list[dict] | None:
    """Safely extract content dict list from JSONL record. Malformed returns None."""
    message = record.get("message", {})
    if not isinstance(message, dict):
        return None
    content = message.get("content", [])
    if not isinstance(content, list):
        return None
    return [item for item in content if isinstance(item, dict)]


_DRAFT_PATH_SUFFIX = (DRAFT_FILE.parent.name, DRAFT_FILE.name)


def _is_draft_path(file_path: str) -> bool:
    """True if file_path ends with the draft's parent/name suffix.

    Match the last two parts (e.g. ".workspace/draft.md") — DRAFT_FILE.name
    alone is too generic and would collide with unrelated files.
    """
    if not file_path:
        return False
    return Path(file_path).parts[-2:] == _DRAFT_PATH_SUFFIX


def scan_session(session_file: Path) -> tuple[int, list[dict]]:
    """Single-pass JSONL scan: find last draft write line + collect assistant tool sequences.

    Returns (draft_line, filtered_turns).
    draft_line: line number of last draft write, -1 if not found.
    filtered_turns: assistant tool call turns after draft_line.
    """
    write_tool_quoted = {f'"{t}"' for t in FILE_WRITE_TOOLS}
    draft_line = -1
    turns: list[dict] = []

    with open(session_file) as f:
        for line_number, line in enumerate(f):
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            items = _extract_content_items(record)
            if items is None:
                continue

            # draft write detection — string pre-filter avoids json.loads per-item cost.
            # Assumes Claude Code JSONL uses `"name": "Write"` format (Python json.dumps default).
            if any(q in line for q in write_tool_quoted):
                for item in items:
                    if item.get("name", "") not in FILE_WRITE_TOOLS:
                        continue
                    fp = item.get("input", {}).get("file_path", "")
                    if _is_draft_path(fp):
                        draft_line = line_number

            # assistant tool call collection
            if record.get("type") == "assistant":
                tools: list[str] = []
                summary = ""
                for item in items:
                    if item.get("type") == "tool_use":
                        tool_name = item.get("name", "")
                        if tool_name:
                            tools.append(tool_name)
                    elif item.get("type") == "text" and not summary:
                        summary = item.get("text", "")[:200]
                if tools:
                    turns.append({
                        "tools": tools,
                        "summary": summary,
                        "line": line_number,
                    })

    # keep only turns after draft_line
    if draft_line >= 0:
        turns = [t for t in turns if t["line"] > draft_line]

    return draft_line, turns


def check_session_complexity(turns: list[dict]) -> dict | None:
    """Merge all turns into one task block, filter by threshold.

    Returns {tools, summary, start_line} when total tool calls >= TOOL_CALL_THRESHOLD.
    summary uses first non-empty value. None if below threshold.
    """
    if not turns:
        return None
    all_tools: list[str] = []
    summary = ""
    start_line = turns[0]["line"]
    for turn in turns:
        all_tools.extend(turn["tools"])
        if not summary and turn["summary"]:
            summary = turn["summary"]
    if len(all_tools) < TOOL_CALL_THRESHOLD:
        return None
    return {
        "tools": all_tools,
        "summary": summary,
        "start_line": start_line,
    }


def format_report(task: dict | None) -> str:
    """Format report text. Returns empty string when no task.

    Shows aggregated tool counts (e.g. Readx3, Writex1), summary, suggested command.
    """
    if not task:
        return ""
    tool_count = Counter(task["tools"])
    total = len(task["tools"])
    tool_summary = ", ".join(
        f"{name}x{count}" for name, count in tool_count.most_common()
    )
    lines: list[str] = [
        "=== Skill Catchup: uncaptured complex tasks ===\n",
        f"  1. {total} tool calls: {tool_summary}",
    ]
    if task["summary"]:
        lines.append(f"     Summary: {task['summary']}")
    lines.append("     => /skill-forge create <prompt>\n")
    return "\n".join(lines)


def main(cwd: str | None = None) -> str:
    """Entry point. Scan previous session for complex uncaptured tasks.

    cwd: working directory (defaults to sys.argv[1] for CLI usage).
    Returns report string (empty if nothing found).
    """
    if cwd is None:
        if len(sys.argv) < 2:
            return ""
        cwd = sys.argv[1]
    project_dir = resolve_project_dir(cwd)
    sessions = get_sessions_sorted(project_dir)
    # sessions[0] is current session (exists when Phase 0 runs), scan previous via sessions[1]
    if len(sessions) < 2:
        return ""
    session = sessions[1]
    _draft_line, turns = scan_session(session)
    task = check_session_complexity(turns)
    return format_report(task)


if __name__ == "__main__":  # pragma: no cover — entry guard, tests call main() directly
    report = main()
    if report:
        print(report)
