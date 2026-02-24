import json
import logging
import os
import pathlib
from typing import Any, Dict, List, Optional, Tuple

from ouroboros.utils import (
    utc_now_iso, read_text, clip_text, estimate_tokens, get_git_info,
)
from ouroboros.memory import Memory

log = logging.getLogger(__name__)

def get_dynamic_context_limit(model_id: str, task_type: str = "user") -> int:
    limits = {
        'groq/': 4000,
        'google/': 4000,
        'stepfun/': 8000,
        'arcee-ai/': 8000,
        'together/': 6000,
        'qwen/': 6000,
    }
    for prefix, limit in limits.items():
        if model_id.startswith(prefix):
            return limit
    # Evolution tasks always get stricter caps
    return 4000 if task_type == "evolution" else 8000

def _build_user_content(task: Dict[str, Any]) -> Any:
    text = task.get("text", "")
    image_b64 = task.get("image_base64")
    image_mime = task.get("image_mime", "image/jpeg")
    image_caption = task.get("image_caption", "")

    if not image_b64:
        if not text:
            return "(empty message)"
        return text

    parts = []
    combined_text = image_caption
    if text and text != image_caption:
        combined_text = (combined_text + "\n" + text).strip() if combined_text else text

    if not combined_text:
        combined_text = "Analyze the screenshot"

    parts.append({"type": "text", "text": combined_text})
    parts.append({
        "type": "image_url",
        "image_url": {"url": f"data:{image_mime};base64,{image_b64}"}
    })
    return parts

def _build_runtime_section(env: Any, task: Dict[str, Any]) -> str:
    try:
        git_branch, git_sha = get_git_info(env.repo_dir)
    except Exception:
        git_branch, git_sha = "unknown", "unknown"

    budget_info = None
    try:
        state_json = read_text(env.drive_path("state/state.json"), fallback="{}")
        state_data = json.loads(state_json)
        spent_usd = float(state_data.get("spent_usd", 0))
        total_usd = float(os.environ.get("TOTAL_BUDGET", "1"))
        remaining_usd = total_usd - spent_usd
        budget_info = {"total_usd": total_usd, "spent_usd": spent_usd, "remaining_usd": remaining_usd}
    except Exception:
        pass

    runtime_data = {
        "utc_now": utc_now_iso(),
        "repo_dir": str(env.repo_dir),
        "drive_root": str(env.drive_root),
        "git_head": git_sha,
        "git_branch": git_branch,
        "task": {"id": task.get("id"), "type": task.get("type")},
    }
    if budget_info:
        runtime_data["budget"] = budget_info
    return "## Runtime context\n\n" + json.dumps(runtime_data, ensure_ascii=False, indent=2)

def _build_health_invariants(env: Any) -> str:
    checks = []

    try:
        ver_file = read_text(env.repo_path("VERSION")).strip()
        pyproject = read_text(env.repo_path("pyproject.toml"))
        pyproject_ver = ""
        for line in pyproject.splitlines():
            if line.strip().startswith("version"):
                pyproject_ver = line.split("=", 1)[1].strip().strip('\"').strip("'")
                break
        if ver_file and pyproject_ver and ver_file != pyproject_ver:
            checks.append(f"CRITICAL: VERSION DESYNC — VERSION={ver_file}, pyproject.toml={pyproject_ver}")
        elif ver_file:
            checks.append(f"OK: version sync ({ver_file})")
    except Exception:
        pass

    try:
        state_json = read_text(env.drive_path("state/state.json"))
        state_data = json.loads(state_json)
        if state_data.get("budget_drift_alert"):
            drift_pct = state_data.get("budget_drift_pct", 0)
            our = state_data.get("spent_usd", 0)
            theirs = state_data.get("openrouter_total_usd", 0)
            checks.append(f"WARNING: BUDGET DRIFT {drift_pct:.1f}% — tracked=${our:.2f} vs OpenRouter=${theirs:.2f}")
        else:
            checks.append("OK: budget drift within tolerance")
    except Exception:
        pass

    try:
        import time as _time
        identity_path = env.drive_path("memory/identity.md")
        if identity_path.exists():
            age_hours = (_time.time() - identity_path.stat().st_mtime) / 3600
            if age_hours > 8:
                checks.append(f"WARNING: STALE IDENTITY — identity.md last updated {age_hours:.0f}h ago")
            else:
                checks.append("OK: identity.md recent")
    except Exception:
        pass

    if not checks:
        return ""
    return "## Health Invariants\n\n" + "\n".join(f"- {c}" for c in checks)

def build_llm_messages(
    env: Any,
    memory: Memory,
    task: Dict[str, Any],
    review_context_builder: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    task_type = str(task.get("type") or "user")
    base_prompt = read_text(
        env.repo_path("prompts/SYSTEM.md"),
        fallback="You are Ouroboros. Your base prompt could not be loaded."
    )
    bible_md = read_text(env.repo_path("BIBLE.md"))
    state_json = read_text(env.drive_path("state/state.json"), fallback="{}")
    memory.ensure_files()

    # DYNAMIC CONTEXT LIMIT BASED ON TASK TYPE AND MODEL
    active_model = os.environ.get("OUROBOROS_MODEL", "groq/llama-3.1-8b-instant")
    soft_cap = get_dynamic_context_limit(active_model, task_type)

    static_text = (
        base_prompt + "\n\n"
        + "## BIBLE.md\n\n" + clip_text(bible_md, 180000)
    )

    semi_stable_parts = []
    scratchpad_raw = memory.load_scratchpad()
    semi_stable_parts.append("## Scratchpad\n\n" + clip_text(scratchpad_raw, 90000))

    identity_raw = memory.load_identity()
    semi_stable_parts.append("## Identity\n\n" + clip_text(identity_raw, 80000))

    kb_index_path = env.drive_path("memory/knowledge/_index.md")
    if kb_index_path.exists():
        kb_index = kb_index_path.read_text(encoding="utf-8")
        if kb_index.strip():
            semi_stable_parts.append("## Knowledge base\n\n" + clip_text(kb_index, 50000))

    semi_stable_text = "\n\n".join(semi_stable_parts)

    dynamic_parts = [
        "## Drive state\n\n" + clip_text(state_json, 90000),
        _build_runtime_section(env, task),
    ]

    health_section = _build_health_invariants(env)
    if health_section:
        dynamic_parts.append(health_section)

    dynamic_text = "\n\n".join(dynamic_parts)

    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": [
                {"type": "text", "text": static_text, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
                {"type": "text", "text": semi_stable_text, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": dynamic_text},
            ],
        },
        {"role": "user", "content": _build_user_content(task)},
    ]

    messages, cap_info = apply_message_token_soft_cap(messages, soft_cap)
    return messages, cap_info

def apply_message_token_soft_cap(
    messages: List[Dict[str, Any]],
    soft_cap_tokens: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    # ACTUAL IMPLEMENTATION TO ENFORCE TOKEN CAPS
    total_tokens = estimate_tokens(messages)
    cap_info = {"requested": soft_cap_tokens, "actual": total_tokens}

    if total_tokens <= soft_cap_tokens:
        return messages, cap_info

    # Truncate from earliest messages until under cap
    truncated = messages[:1]  # Keep system message
    accumulated = estimate_tokens(truncated)

    # Process user/assistant messages in reverse chronological order
    for msg in reversed(messages[1:]):
        msg_tokens = estimate_tokens([msg])
        if accumulated + msg_tokens <= soft_cap_tokens:
            truncated.insert(1, msg)
            accumulated += msg_tokens
        else:
            break

    cap_info["actual"] = accumulated
    return truncated, cap_info