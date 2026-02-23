'''Shell tools: run_shell, llm_code_edit.

claude_code_edit replaced with llm_code_edit — uses LLMClient directly
(no ANTHROPIC_API_KEY or Claude Code CLI required).
Model used: OUROBOROS_MODEL_CODE env var (default: qwen/qwen3-coder:free via OpenRouter).
'''

from __future__ import annotations

import json
import logging
import os
import pathlib
import shlex
import subprocess
from typing import Any, Dict, List, Optional

from ouroboros.tools.registry import ToolContext, ToolEntry
from ouroboros.utils import utc_now_iso, run_cmd, append_jsonl, truncate_for_log

log = logging.getLogger(__name__)

def _run_shell(ctx: ToolContext, cmd, cwd: str = "") -> str:
    # Recover from LLM sending cmd as JSON string instead of list
    if isinstance(cmd, str):
        raw_cmd = cmd
        warning = "run_shell_cmd_string"
        try:
            parsed = json.loads(cmd)
            if isinstance(parsed, list):
                cmd = parsed
                warning = "run_shell_cmd_string_json_list_recovered"
            elif isinstance(parsed, str):
                try:
                    cmd = shlex.split(parsed)
                except ValueError:
                    cmd = parsed.split()
                warning = "run_shell_cmd_string_json_string_split"
            else:
                try:
                    cmd = shlex.split(cmd)
                except ValueError:
                    cmd = cmd.split()
                warning = "run_shell_cmd_string_json_non_list_split"
        except Exception:
            try:
                cmd = shlex.split(cmd)
            except ValueError:
                cmd = cmd.split()
            warning = "run_shell_cmd_string_split_fallback"

        try:
            append_jsonl(ctx.drive_logs() / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "tool_warning",
                "tool": "run_shell",
                "warning": warning,
                "cmd_preview": truncate_for_log(raw_cmd, 500),
            })
        except Exception:
            log.debug("Failed to log run_shell warning to events.jsonl", exc_info=True)

    if not isinstance(cmd, list):
        return "⚠️ SHELL_ARG_ERROR: cmd must be a list of strings."
    cmd = [str(x) for x in cmd]

    work_dir = ctx.repo_dir
    if cwd and cwd.strip() not in ("", ".", "./"):
        candidate = (ctx.repo_dir / cwd).resolve()
        if candidate.exists() and candidate.is_dir():
            work_dir = candidate

    try:
        res = subprocess.run(
            cmd, cwd=str(work_dir),
            capture_output=True, text=True, timeout=120,
        )
        out = res.stdout + ("\n--- STDERR ---\n" + res.stderr if res.stderr else "")
        if len(out) > 50000:
            out = out[:25000] + "\n...(truncated)...\n" + out[-25000:]
        prefix = f"exit_code={res.returncode}\n"
        return prefix + out
    except subprocess.TimeoutExpired:
        return "⚠️ TIMEOUT: command exceeded 120s."
    except Exception as e:
        return f"⚠️ SHELL_ERROR: {e}"

def _check_uncommitted_changes(repo_dir: pathlib.Path) -> str:
    """Check git status after edit, return warning string or empty."""
    try:
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir, capture_output=True, text=True, timeout=5,
        )
        if status_res.returncode == 0 and status_res.stdout.strip():
            diff_res = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=repo_dir, capture_output=True, text=True, timeout=5,
            )
            if diff_res.returncode == 0 and diff_res.stdout.strip():
                return (
                    f"\n\n⚠️ UNCOMMITTED CHANGES detected after edit:\n"
                    f"{diff_res.stdout.strip()}\n"
                    f"Remember to run git_status and repo_commit_push!"
                )
    except Exception as e:
        log.debug("Failed to check git status after llm_code_edit: %s", e, exc_info=True)
    return ""

def _extract_code_block(text: str) -> Optional[str]:
    """
    Extract code from LLM response.
<<<<<<< Updated upstream
    Tries ```python ... ``` first, then ``` ... ```, then returns raw text.
    """
    import re
    # Try fenced code block with language tag
    m = re.search(r"```(?:python|py)?\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Try plain fenced block
    m = re.search(r"```\n?(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # No fences — return as-is if it looks like code (not prose)
    stripped = text.strip()
    if stripped and not stripped[0].isupper():
        return stripped
    return None

def _llm_code_edit(ctx: ToolContext, prompt: str, file_path: str = "", cwd: str = "") -> str:
    """
    Edit code files using the configured code LLM (OUROBOROS_MODEL_CODE).

    Workflow:
      1. Read the target file (if file_path given)
      2. Send prompt + current code to LLM
      3. Extract code from response
      4. Write the result back to disk
      5. Return diff summary

    No ANTHROPIC_API_KEY or Claude CLI required.
    """
    from ouroboros.llm import LLMClient, add_usage

    model = os.environ.get("OUROBOROS_MODEL_CODE", "qwen/qwen3-coder:free")
    llm = LLMClient()

    # Resolve target file
    work_dir = ctx.repo_dir
    if cwd and cwd.strip() not in ("", ".", "./"):
        candidate = (ctx.repo_dir / cwd).resolve()
        if candidate.exists() and candidate.is_dir():
            work_dir = candidate

    target: Optional[pathlib.Path] = None
    current_code = ""
    if file_path and file_path.strip():
        target = (work_dir / file_path.strip()).resolve()
        if target.exists() and target.is_file():
            try:
                current_code = target.read_text(encoding="utf-8")
                if len(current_code) > 60_000:
                    # Truncate very large files — LLM context limit
                    current_code = current_code[:60_000] + "\n# ... (file truncated for context)"
            except Exception as e:
                return f"⚠️ FILE_READ_ERROR: {e}"

    ctx.emit_progress_fn(f"llm_code_edit → {model} | file: {file_path or '(no file)'}")

    # Build prompt for LLM
    system_msg = (
        "You are an expert software engineer. "
        "When asked to edit code, return ONLY the complete updated file content "
        "inside a single ```python ... ``` block. "
        "Do NOT include explanations, comments outside the code, or multiple blocks."
    )
    user_content = prompt.strip()
    if current_code:
        user_content += (
            f"\n\nCurrent content of `{file_path}`:\n"
            f"```python\n{current_code}\n```\n\n"
            f"Return the complete updated file."
        )

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user",   "content": user_content},
    ]

    try:
        resp_msg, usage = llm.chat(
            messages=messages,
            model=model,
            tools=None,
            reasoning_effort="low",
            max_tokens=16384,
        )
    except Exception as e:
        return f"⚠️ LLM_CODE_EDIT_ERROR: {type(e).__name__}: {e}"

    # FIX: Include model in usage tracking to prevent 'unknown' in model_breakdown
    add_usage({'model': model}, usage)  # Previously: add_usage({}, usage)

    raw_response = resp_msg.get("content") or ""
    if not raw_response.strip():
        return "⚠️ LLM_CODE_EDIT_EMPTY: model returned empty response. Try rephrasing the prompt."

    # Extract code block from response
    new_code = _extract_code_block(raw_response)
    if new_code is None:
        # No clear code block — return raw response so agent can decide
        return (
            f"⚠️ LLM_CODE_EDIT_NO_BLOCK: Could not extract code block from response.\n"
            f"Raw response (first 2000 chars):\n{raw_response[:2000]}"
        )

    # Write to disk if we have a target file
    if target is not None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_code, encoding="utf-8")
        except Exception as e:
            return f"⚠️ FILE_WRITE_ERROR: {e}"

        # Log edit event
        append_jsonl(ctx.drive_logs() / "events.jsonl", {
            "ts": utc_now_iso(),
            "type": "llm_code_edit",
            "file": str(target.relative_to(ctx.repo_dir)),
            "model": model,
            "prompt_preview": prompt[:200],
        })

        warning = _check_uncommitted_changes(ctx.repo_dir)
        lines_before = current_code.count("\n")
        lines_after = new_code.count("\n")
        return (
            f"✅ llm_code_edit complete.\n"
            f"File: {file_path}\n"
            f"Model: {model}\n"
            f"Lines: {lines_before} → {lines_after}\n"
            f"{warning}"
        )
    else:
        # No file — return generated code directly (agent can write it manually)
        return (
            f"✅ llm_code_edit result (no file_path given — code not written to disk):\n"
            f"```python\n{new_code}\n```"
        )

def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("run_shell", {
            "name": "run_shell",
            "description": "Run a shell command (list of args) inside the repo. Returns stdout+stderr.",
            "parameters": {"type": "object", "properties": {
                "cmd":  {"type": "array", "items": {"type": "string"}},
                "cwd":  {"type": "string", "default": ""},
            }, "required": ["cmd"]},
        }, _run_shell, is_code_tool=True),

        ToolEntry("llm_code_edit", {
            "name": "llm_code_edit",
            "description": (
                "Edit a code file using the configured code LLM (OUROBOROS_MODEL_CODE). "
                "Pass the file path and a plain-English instruction. "
                "The model reads the current file, applies the change, and writes it back. "
                "No Claude CLI or ANTHROPIC_API_KEY required. "
                "Follow with repo_commit_push to save changes."
            ),
            "parameters": {"type": "object", "properties": {
                "prompt":    {"type": "string",  "description": "What to change and why"},
                "file_path": {"type": "string",  "description": "Path relative to repo root (e.g. ouroboros/llm.py)"},
                "cwd":       {"type": "string",  "default": ""},
            }, "required": ["prompt"]},
        }, _llm_code_edit, is_code_tool=True, timeout_sec=300),
    ]
=======
    Tries
>>>>>>> Stashed changes
