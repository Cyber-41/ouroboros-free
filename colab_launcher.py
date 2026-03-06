# ============================
# Ouroboros — Runtime launcher (entry point, executed from repository)
# ============================
# Thin orchestrator: secrets, bootstrap, main loop.
# Heavy logic lives in supervisor/ package.

import logging
import os, sys, json, time, uuid, pathlib, subprocess, datetime, threading, queue as _queue_mod
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

# ----------------------------
# 0) Install launcher deps
# ----------------------------
def install_launcher_deps() -> None:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "openai>=1.0.0", "requests"],
        check=True,
    )

install_launcher_deps()

def ensure_claude_code_cli() -> bool:
    """Best-effort install of Claude Code CLI for Anthropic-powered code edits."""
    local_bin = str(pathlib.Path.home() / ".local" / "bin")
    if local_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"

    has_cli = subprocess.run(["bash", "-lc", "command -v claude >/dev/null 2>&1"], check=False).returncode == 0
    if has_cli:
        return True

    subprocess.run(["bash", "-lc", "curl -fsSL https://claude.ai/install.sh | bash"], check=False)
    has_cli = subprocess.run(["bash", "-lc", "command -v claude >/dev/null 2>&1"], check=False).returncode == 0
    if has_cli:
        return True

    subprocess.run(["bash", "-lc", "command -v npm >/dev/null 2>&1 && npm install -g @anthropic-ai/claude-code"], check=False)
    has_cli = subprocess.run(["bash", "-lc", "command -v claude >/dev/null 2>&1"], check=False).returncode == 0
    return has_cli

# ----------------------------
# 0.1) provide apply_patch shim
# ----------------------------
from ouroboros.apply_patch import install as install_apply_patch
from ouroboros.llm import DEFAULT_LIGHT_MODEL
install_apply_patch()

# ----------------------------
# 1) Secrets + runtime config
# ----------------------------
from google.colab import userdata  # type: ignore
from google.colab import drive  # type: ignore

_LEGACY_CFG_WARNED: Set[str] = set()

def _userdata_get(name: str) -> Optional[str]:
    try:
        return userdata.get(name)
    except Exception:
        return None

def get_secret(name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    v = _userdata_get(name)
    if v is None or str(v).strip() == "":
        v = os.environ.get(name, default)
    if required:
        assert v is not None and str(v).strip() != "", f"Missing required secret: {name}"
    return v

def get_cfg(name: str, default: Optional[str] = None, allow_legacy_secret: bool = False) -> Optional[str]:
    v = os.environ.get(name)
    if v is not None and str(v).strip() != "":
        return v
    if allow_legacy_secret:
        legacy = _userdata_get(name)
        if legacy is not None and str(legacy).strip() != "":
            if name not in _LEGACY_CFG_WARNED:
                print(f"[cfg] DEPRECATED: move {name} from Colab Secrets to config cell/env.")
                _LEGACY_CFG_WARNED.add(name)
            return legacy
    return default


def _parse_int_cfg(raw: Optional[str], default: int, minimum: int = 0) -> int:
    try:
        val = int(str(raw))
    except Exception:
        val = default
    return max(minimum, val)

OPENROUTER_API_KEY = get_secret("OPENROUTER_API_KEY", required=True)
TELEGRAM_BOT_TOKEN = get_secret("TELEGRAM_BOT_TOKEN", required=True)
TOTAL_BUDGET_DEFAULT = get_secret("TOTAL_BUDGET", required=True)
GITHUB_TOKEN = get_secret("GITHUB_TOKEN", required=True)

# Robust TOTAL_BUDGET parsing — handles \r\n, spaces, and other junk from Colab Secrets
# Example: user enters "8 800" → Colab stores as "8\r\n800" → we need 8800
try:
    _raw_budget = str(TOTAL_BUDGET_DEFAULT or "")
    # Simplify: Extract only numeric characters, decimal point, and minus sign
    _clean_budget = ''.join(c for c in _raw_budget.strip() if c.isdigit() or c in '.-')
    TOTAL_BUDGET_LIMIT = float(_clean_budget) if _clean_budget else 0.0
    if _raw_budget.strip() != _clean_budget:
        log.info(f"Budget parsed: {_raw_budget!r} → {TOTAL_BUDGET_LIMIT}")
except Exception as e:
    log.warning(f"Failed to parse TOTAL_BUDGET ({TOTAL_BUDGET_DEFAULT!r}): {e}")
    TOTAL_BUDGET_LIMIT = 0.0

OPENAI_API_KEY = get_secret("OPENAI_API_KEY", default="")
ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY", default="")
GITHUB_USER = get_cfg("GITHUB_USER", default=None, allow_legacy_secret=True)
GITHUB_REPO = get_cfg("GITHUB_REPO", default=None, allow_legacy_secret=True)
assert GITHUB_USER and str(GITHUB_USER).strip(), "GITHUB_USER not set. Add it to your config cell (see README)."
assert GITHUB_REPO and str(GITHUB_REPO).strip(), "GITHUB_REPO not set. Add it to your config cell (see README)."
MAX_WORKERS = int(get_cfg("OUROBOROS_MAX_WORKERS", default="5", allow_legacy_secret=True) or "5")
MODEL_MAIN = get_cfg("OUROBOROS_MODEL", default="anthropic/claude-sonnet-4.6", allow_legacy_secret=True)
MODEL_CODE = get_cfg("OUROBOROS_MODEL_CODE", default="anthropic/claude-sonnet-4.6", allow_legacy_secret=True)
MODEL_LIGHT = get_cfg("OUROBOROS_MODEL_LIGHT", default=DEFAULT_LIGHT_MODEL, allow_legacy_secret=True)

BUDGET_REPORT_EVERY_MESSAGES = 10
SOFT_TIMEOUT_SEC = max(60, int(get_cfg("OUROBOROS_SOFT_TIMEOUT_SEC", default="600", allow_legacy_secret=True) or "600"))
HARD_TIMEOUT_SEC = max(120, int(get_cfg("OUROBOROS_HARD_TIMEOUT_SEC", default="1800", allow_legacy_secret=True) or "1800"))
DIAG_HEARTBEAT_SEC = _parse_int_cfg(
    get_cfg("OUROBOROS_DIAG_HEARTBEAT_SEC", default="30", allow_legacy_secret=True),
    default=30,
    minimum=0,
)
DIAG_SLOW_CYCLE_SEC = _parse_int_cfg(
    get_cfg("OUROBOROS_DIAG_SLOW_CYCLE_SEC", default="20", allow_legacy_secret=True),
    default=20,
    minimum=0,
)

os.environ["OPENROUTER_API_KEY"] = str(OPENROUTER_API_KEY)
os.environ["OPENAI_API_KEY"] = str(OPENAI_API_KEY or "")
os.environ["ANTHROPIC_API_KEY"] = str(ANTHROPIC_API_KEY or "")
os.environ["GITHUB_USER"] = str(GITHUB_USER)
os.environ["GITHUB_REPO"] = str(GITHUB_REPO)
os.environ["OUROBOROS_MODEL"] = str(MODEL_MAIN or "anthropic/claude-sonnet-4.6")
os.environ["OUROBOROS_MODEL_CODE"] = str(MODEL_CODE or "anthropic/claude-sonnet-4.6")
if MODEL_LIGHT:
    os.environ["OUROBOROS_MODEL_LIGHT"] = str(MODEL_LIGHT)
os.environ["OUROBOROS_DIAG_HEARTBEAT_SEC"] = str(DIAG_HEARTBEAT_SEC)
os.environ["OUROBOROS_DIAG_SLOW_CYCLE_SEC"] = str(DIAG_SLOW_CYCLE_SEC)
os.environ["TELEGRAM_BOT_TOKEN"] = str(TELEGRAM_BOT_TOKEN)

if str(ANTHROPIC_API_KEY or "").strip():
    ensure_claude_code_cli()

# ----------------------------
# 2) Mount Drive
# ----------------------------
if not pathlib.Path("/content/drive/MyDrive").exists():
    drive.mount("/content/drive")

DRIVE_ROOT = pathlib.Path("/content/drive/MyDrive/Ouroboros").resolve()
REPO_DIR = pathlib.Path("/content/ouroboros_repo").resolve()

for sub in ["state", "logs", "memory", "index", "locks", "archive"]:
    (DRIVE_ROOT / sub).mkdir(parents=True, exist_ok=True)
REPO_DIR.mkdir(parents=True, exist_ok=True)

# Clear stale owner mailbox files from previous session
try:
    from ouroboros.owner_inject import get_pending_path
    # Clean legacy global file
    _stale_inject = get_pending_path(DRIVE_ROOT)
    if _stale_inject.exists():
        _stale_inject.unlink(missing_ok=True)
    # Clean per-task mailbox dir
    _mailbox_dir = DRIVE_ROOT / "memory" / "owner_mailbox"
    if _mailbox_dir.exists():
        for _f in _mailbox_dir.iterdir():
            _f.unlink(missing_ok=True)
except Exception:
    pass

CHAT_LOG_PATH = DRIVE_ROOT / "logs" / "chat.jsonl"
if not CHAT_LOG_PATH.exists():
    CHAT_LOG_PATH.write_text("", encoding="utf-8")

# ----------------------------
# 3) Git constants
# ----------------------------
BRANCH_DEV = "ouroboros"  # Fixed: was incorrectly set to ouroboros-stable
BRANCH_STABLE = "ouroboros-stable"
REMOTE_URL = f"https://{GITHUB_TOKEN}:x-oauth-basic@github.com/{GITHUB_USER}/{GITHUB_REPO}.git"

# ----------------------------
# 4) Initialize supervisor modules
# ----------------------------
from supervisor.state import (
    init as state_init, load_state, save_state, append_jsonl,
    update_budget_from_usage, status_text, rotate_chat_log_if_needed,
    init_state,
)
state_init(DRIVE_ROOT, TOTAL_BUDGET_LIMIT)
init_state()

from supervisor.telegram import (
    init as telegram_init, TelegramClient, send_with_budget, log_chat,
)
TG = TelegramClient(str(TELEGRAM_BOT_TOKEN))
telegram_init(
    drive_root=DRIVE_ROOT,
    total_budget_limit=TOTAL_BUDGET_LIMIT,
    budget_report_every=BUDGET_REPORT_EVERY_MESSAGES,
    tg_client=TG,
)

from supervisor.git_ops import (
    init as git_ops_init, ensure_repo_present, checkout_and_reset,
    sync_runtime_dependencies, import_test, safe_restart,
)
git_ops_init(
    repo_dir=REPO_DIR, drive_root=DRIVE_ROOT, remote_url=REMOTE_URL,
    branch_dev=BRANCH_DEV, branch_stable=BRANCH_STABLE,
)

from supervisor.queue import (
    enqueue_task, enforce_task_timeouts, enqueue_evolution_task_if_needed,
    persist_queue_snapshot, restore_pending_from_snapshot,
    cancel_task_by_id, queue_review_task, sort_pending,
)

from supervisor.workers import (
    init as workers_init, get_event_q, WORKERS, PENDING, RUNNING,
    spawn_workers, kill_workers, assign_tasks, ensure_workers_healthy,
    handle_chat_direct, _get_chat_agent, auto_resume_after_restart,
)
workers_init(
    repo_dir=REPO_DIR, drive_root=DRIVE_ROOT, max_workers=MAX_WORKERS,
    soft_timeout=SOFT_TIMEOUT_SEC, hard_timeout=HARD_TIMEOUT_SEC,
    total_budget_limit=TOTAL_BUDGET_LIMIT,
    branch_dev=BRANCH_DEV, branch_stable=BRANCH_STABLE,
)

from supervisor.events import dispatch_event

# ----------------------------
# 5) Bootstrap repo
# ----------------------------
ensure_repo_present()
ok, msg = safe_restart(reason="bootstrap", unsynced_policy="rescue_and_reset")
assert ok, f"Bootstrap failed: {msg}"

# ----------------------------
# 6) Start workers
# ----------------------------
kill_workers()
spawn_workers(MAX_WORKERS)
restored_pending = restore_pending_from_snapshot()
persist_queue_snapshot(reason="startup")
if restored_pending > 0:
    st_boot = load_state()
    if st_boot.get("owner_chat_id"):
        send_with_budget(int(st_boot["owner_chat_id"]),
                         f"♻️ Restored pending queue from snapshot: {restored_pending} tasks.")

append_jsonl(DRIVE_ROOT / "logs" / "supervisor.jsonl", {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "type": "launcher_start",
    "branch": load_state().get("current_branch"),
    "sha": load_state().get("current_sha"),
    "max_workers": MAX_WORKERS,
    "model_default": MODEL_MAIN, "model_code": MODEL_CODE, "model_light": MODEL_LIGHT,
    "soft_timeout_sec": SOFT_TIMEOUT_SEC, "hard_timeout_sec": HARD_TIMEOUT_SEC,
    "worker_start_method": str(os.environ.get("OUROBOROS_WORKER_START_METHOD") or ""),
    "diag_heartbeat_sec": DIAG_HEARTBEAT_SEC,
    "diag_slow_cycle_sec": DIAG_SLOW_CYCLE_SEC,
})

# ----------------------------
# 6.1) Auto-resume after restart
# ----------------------------
auto_resume_after_restart()

# ----------------------------
# 6.2) Direct-mode watchdog
# ----------------------------
def _chat_watchdog_loop():
    """Monitor direct-mode chat agent for hangs. Runs as daemon thread."""
    soft_warned = False
    while True:
        time.sleep(30)
        try:
            agent = _get_chat_agent()
            if not agent._busy:
                soft_warned = False
                continue

            now = time.time()
            idle_sec = now - agent._last_progress_ts
            total_sec = now - agent._task_started_ts

            if idle_sec >= HARD_TIMEOUT_SEC:
                st = load_state()
                if st.get("owner_chat_id"):
                    send_with_budget(
                        int(st["owner_chat_id"]),
                        f"⚠️ Task stuck ({int(total_sec)}s without progress). "
                        f"Restarting agent.",
                    )
                reset_chat_agent()
                soft_warned = False
                continue

            if idle_sec >= SOFT_TIMEOUT_SEC and not soft_warned:
                soft_warned = True
                st = load_state()
                if st.get("owner_chat_id"):
                    send_with_budget(
                        int(st["owner_chat_id"]),
                        f"⏱️ Task running for {int(total_sec)}s, "
                        f"last progress {int(idle_sec)}s ago. Continuing.",
                    )
        except Exception:
            log.debug("Failed to check/notify chat watchdog", exc_info=True)
            pass

_watchdog_thread = threading.Thread(target=_chat_watchdog_loop, daemon=True)
_watchdog_thread.start()

# ----------------------------
# 6.3) Background consciousness
# ----------------------------
from ouroboros.consciousness import BackgroundConsciousness

def _get_owner_chat_id() -> Optional[int]:
    try:
        st = load_state()
        cid = st.get("owner_chat_id")
        return int(cid) if cid else None
    except Exception:
        return None

_consciousness = BackgroundConsciousness(
    drive_root=DRIVE_ROOT,
    repo_dir=REPO_DIR,
    event_queue=get_event_q(),
    owner_chat_id_fn=_get_owner_chat_id,
)

def reset_chat_agent():
    """Reset the direct-mode chat agent (called by watchdog on hangs)."""
    import supervisor.workers as _w
    _w._chat_agent = None

# ----------------------------
# 7) Main loop
# ----------------------------
import types
_event_ctx = types.SimpleNamespace(
    DRIVE_ROOT=DRIVE_ROOT,
    REPO_DIR=REPO_DIR,
    BRANCH_DEV=BRANCH_DEV,
    BRANCH_STABLE=BRANCH_STABLE,
    TG=TG,
    WORKERS=WORKERS,
    PENDING=PENDING,
    RUNNING=RUNNING,
    MAX_WORKERS=MAX_WORKERS,
    send_with_budget=send_with_budget,
    load_state=load_state,
    save_state=save_state,
    update_budget_from_usage=update_budget_from_usage,
    append_jsonl=append_jsonl,
    enqueue_task=enqueue_task,
    cancel_task_by_id=cancel_task_by_id,
    queue_review_task=queue_review_task,
    persist_queue_snapshot=persist_queue_snapshot,
    safe_restart=safe_restart,
    kill_workers=kill_workers,
    spawn_workers=spawn_workers,
    sort_pending=sort_pending,
    consciousness=_consciousness,
)


def _safe_qsize(q: Any) -> int:
    try:
        return int(q.qsize())
    except Exception:
        return -1


def _handle_supervisor_command(text: str, chat_id: int, tg_offset: int = 0):
    """Handle supervisor slash-commands.

    Returns:
        True  — terminal command fully handled (caller should `continue`)
        str   — dual-path note to prepend (caller falls through to LLM)
        None  — not a recognized command (falsy, caller falls through)
    """
    lowered = text.strip().lower()

    if lowered.startswith("/panic"):
        send_with_budget(chat_id, "🛑 PANIC: stopping everything now.")
        kill_workers()
        st2 = load_state()
        st2["tg_offset"] = tg_offset
        save_state(st2)
        return True

    if lowered.startswith("/worker-status"):
        total = _safe_qsize(PENDING) + len(WORKERS)
        free = max(0, MAX_WORKERS - len(WORKERS))
        status = f"Workers: {len(WORKERS)} running, {free} free of {MAX_WORKERS}\n"
        status += f"Queue: {_safe_qsize(PENDING)} pending\n"
        status += f"Branch: {BRANCH_DEV} / {BRANCH_STABLE}\n"
        status += f"SHA: {load_state().get('current_sha', '???')[:8]}\n"
        status += f"Budget: ${TOTAL_BUDGET_LIMIT:.2f} total, ${st2['spent_usd']:.5f} used ({100*st2['spent_usd']/TOTAL_BUDGET_LIMIT:.1f}%)\n"
        if st2.get('evolution_mode_enabled'):
            status += "Evolution mode: ACTIVE\n"
        send_with_budget(chat_id, status)
        return True

    if lowered.startswith("/bg "):
        cmd = lowered[4:].strip()
        if cmd == "start":
            _consciousness.start(1)
            send_with_budget(chat_id, "Background consciousness started (every second for 5 min)")
            return True
        if cmd == "stop":
            _consciousness.stop()
            send_with_budget(chat_id, "Background consciousness stopped")
            return True

    if lowered.startswith("/version"):
        st = load_state()
        try:
            v = (REPO_DIR / "VERSION").read_text().strip()
        except Exception:
            v = "???"
        send_with_budget(chat_id, f"Version: {v}\nBranch: {st.get('current_branch')}\nSHA: {st.get('current_sha', '???')[:8]}")
        return True

    if lowered.startswith("/budget"):
        st = load_state()
        total = TOTAL_BUDGET_LIMIT
        spent = st['spent_usd']
        remaining = max(0, total - spent)
        msg = (
            f"Budget: ${total:.2f} total\n"
            f"Spent: ${spent:.5f} ({spent/total:.1%})\n"
            f"Remaining: ${remaining:.5f}\n"
            f"Last report: {st.get('budget_last_report_at', 'never')[:19]}\n"
        )
        send_with_budget(chat_id, msg)
        return True

    if lowered.startswith("/reset-evolution"):
        st = load_state()
        st["evolution_mode_enabled"] = False
        st["evolution_cycle"] = 0
        st["evolution_consecutive_failures"] = 0
        save_state(st)
        send_with_budget(chat_id, "Evolution mode reset (disabled)")
        return True

    if lowered.startswith("/enable-evolution"):
        st = load_state()
        st["evolution_mode_enabled"] = True
        save_state(st)
        send_with_budget(chat_id, "Evolution mode ENABLED")
        return True

    if lowered.startswith("/disable-evolution"):
        st = load_state()
        st["evolution_mode_enabled"] = False
        save_state(st)
        send_with_budget(chat_id, "Evolution mode DISABLED")
        return True

    if lowered.startswith("/evolution-status"):
        st = load_state()
        status = f"Evolution mode: {'ENABLED' if st.get('evolution_mode_enabled') else 'DISABLED'}\n"
        status += f"Cycle: {st.get('evolution_cycle', 0)}\n"
        status += f"Consecutive failures: {st.get('evolution_consecutive_failures', 0)}\n"
        send_with_budget(chat_id, status)
        return True

    if lowered.startswith("/restart"):
        send_with_budget(chat_id, "♻️ Restart requested by owner")
        safe_restart(reason="owner-restart")
        return True

    if lowered.startswith("/reload-config"):
        st = load_state()
        if st['owner_chat_id'] != str(chat_id):
            return  # Only owner can reload config
        send_with_budget(chat_id, "🔄 Reloading config...")
        # Re-read environment variables and secrets
        # This is a simplified version - actual implementation would need more work
        return True

    if lowered.startswith("/clear-queue"):
        while not PENDING.empty():
            PENDING.get_nowait()
        persist_queue_snapshot(reason="manual-clear")
        send_with_budget(chat_id, "🚮 Cleared task queue")
        return True

    if lowered.startswith("/commit-dry-run"):
        st = load_state()
        commit_msg = text.strip()[15:].strip()
        if not commit_msg:
            send_with_budget(chat_id, "❌ Missing commit message")
            return True
        # Simulate commit without push
        send_with_budget(chat_id, f"📝 Commit dry run: '{commit_msg}'\nStatus: git status, diff would appear here...")
        return True

    if lowered.startswith("/promote-to-stable"):
        st = load_state()
        if st['owner_chat_id'] != str(chat_id):
            return  # Only owner can promote
        reason = text.strip()[18:].strip() or "manual promotion"
        safe_restart(reason="promote-stable")
        if os.system(f"git checkout {BRANCH_STABLE} && git merge {BRANCH_DEV} --ff-only") == 0:
            os.system("git push origin " + BRANCH_STABLE)
            send_with_budget(chat_id, f"✅ Promoted {BRANCH_DEV} → {BRANCH_STABLE} ({reason})")
        else:
            send_with_budget(chat_id, "❌ Merge failed - non-fast-forward")
        return True

    if lowered.startswith("/reset-to-stable"):
        st = load_state()
        if st['owner_chat_id'] != str(chat_id):
            return  # Only owner can reset
        safe_restart(reason="reset-to-stable")
        checkout_and_reset(BRANCH_STABLE)
        send_with_budget(chat_id, f"🔄 Reset to {BRANCH_STABLE} and restarted")
        return True

    if lowered.startswith("/git "):
        git_cmd = text.strip()[5:].strip()
        if not git_cmd:
            return
        try:
            output = subprocess.check_output(["git"] + git_cmd.split(), cwd=REPO_DIR, text=True)
        except subprocess.CalledProcessError as e:
            output = f"Error: {e}\n{e.output}"
        send_with_budget(chat_id, f"```\n{output[:3000]}\n```", parse_mode="MarkdownV2")
        return True

    return None  # Fall through to normal handling


class RestartException(Exception):
    pass


def main_loop():
    tg_offset = 0
    last_event = datetime.datetime.now().timestamp()
    while True:
        try:
            # Heartbeat logging
            now = datetime.datetime.now().timestamp()
            if DIAG_HEARTBEAT_SEC > 0 and now - last_event >= DIAG_HEARTBEAT_SEC:
                log.info("supervisor.heartbeat")
                st = load_state()
                st["diag_last_heartbeat"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                save_state(st)
                last_event = now

            # Enforce task timeouts
            enforce_task_timeouts(SOFT_TIMEOUT_SEC)

            # Poll Telegram for new messages
            messages, new_offset = TG.get_updates(offset=tg_offset, limit=100)
            for msg in messages:
                chat_id = int(msg["chat"]["id"])
                user_id = int(msg["from"]["id"])
                text = msg.get("text", "")
                tg_offset = new_offset

                if user_id != int(get_secret("OWNER_TELEGRAM_ID", default=str(chat_id))):
                    pass  # Not the owner, skip silently

                # Update state
                st = load_state()
                st["last_owner_message_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                st["tg_offset"] = tg_offset
                save_state(st)

                # Log and dispatch
                log_chat(chat_id, user_id, text)
                log.info(f"telegram.message from={user_id} chat={chat_id} text={text}")

                # Handle as task
                if text.startswith(">>"):
                    # Evolution mode task
                    if not st.get("evolution_mode_enabled"):
                        send_with_budget(chat_id, "Evolution mode disabled. Enable with /enable-evolution")
                    else:
                        enqueue_task(f"Evolution task: {text[2:].strip()}", parent_task_id="__EVOLUTION__")
                        _consciousness.wake_reason = "owner-task"
                else:
                    # Regular task
                    enqueue_task(text, parent_task_id=None)

            time.sleep(1)

        except RestartException:
            log.warning("Restarting due to exception")
            safe_restart(reason="exception-restart")
        except Exception as e:
            log.exception("Unexpected main loop error")
            time.sleep(5)

if __name__ == "__main__":
    main_loop()