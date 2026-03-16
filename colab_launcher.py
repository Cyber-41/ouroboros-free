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

# ---- Repo / branch config ----
REPO_DIR   = pathlib.Path(os.environ.get("OUROBOROS_REPO_DIR", "/content/ouroboros_repo"))
DRIVE_ROOT = pathlib.Path("/content/drive/MyDrive/Ouroboros")

BRANCH_DEV    = "ouroboros"
BRANCH_STABLE = "ouroboros-stable"
BOOT_BRANCH   = os.environ.get("OUROBOROS_BOOT_BRANCH", BRANCH_STABLE)

GITHUB_USER = os.environ.get("GITHUB_USER", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()
REMOTE_URL  = f"https://{os.environ['GITHUB_TOKEN']}@github.com/{GITHUB_USER}/{GITHUB_REPO}.git"

assert GITHUB_USER and GITHUB_REPO, "GITHUB_USER / GITHUB_REPO not set"

# ---- Core secrets ----
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TOTAL_BUDGET       = float(os.environ.get("TOTAL_BUDGET", "1"))
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN")

assert OPENROUTER_API_KEY, "Missing OPENROUTER_API_KEY"
assert TELEGRAM_BOT_TOKEN, "Missing TELEGRAM_BOT_TOKEN"
assert GITHUB_TOKEN, "Missing GITHUB_TOKEN"

# ---- Model configuration (override via env) ----
OUROBOROS_MODEL             = os.environ.get("OUROBOROS_MODEL", "anthropic/claude-sonnet-4.6")
OUROBOROS_MODEL_CODE        = os.environ.get("OUROBOROS_MODEL_CODE", "anthropic/claude-sonnet-4.6")
OUROBOROS_MODEL_LIGHT       = os.environ.get("OUROBOROS_MODEL_LIGHT", "google/gemini-3-pro-preview")
OUROBOROS_WEBSEARCH_MODEL   = os.environ.get("OUROBOROS_WEBSEARCH_MODEL", "gpt-5")
OUROBOROS_MODEL_FALLBACK_LIST = os.environ.get(
    "OUROBOROS_MODEL_FALLBACK_LIST",
    "anthropic/claude-sonnet-4.6,google/gemini-3-pro-preview,openai/gpt-4.1",
)

# ---- Infrastructure ----
OUROBOROS_MAX_WORKERS       = int(os.environ.get("OUROBOROS_MAX_WORKERS", "5"))
OUROBOROS_MAX_ROUNDS        = int(os.environ.get("OUROBOROS_MAX_ROUNDS", "200"))
OUROBOROS_BG_BUDGET_PCT     = float(os.environ.get("OUROBOROS_BG_BUDGET_PCT", "10"))

# ---- Colab runtime ----
WORKER_START_METHOD         = os.environ.get("OUROBOROS_WORKER_START_METHOD", "fork")
DIAG_HEARTBEAT_SEC          = int(os.environ.get("OUROBOROS_DIAG_HEARTBEAT_SEC", "30"))
DIAG_SLOW_CYCLE_SEC         = int(os.environ.get("OUROBOROS_DIAG_SLOW_CYCLE_SEC", "20"))

os.environ["PYTHONUNBUFFERED"] = "1"

# ---- Derive full model config dict ----
MODEL_CFG = {
    "primary": OUROBOROS_MODEL,
    "code": OUROBOROS_MODEL_CODE,
    "light": OUROBOROS_MODEL_LIGHT,
    "websearch": OUROBOROS_WEBSEARCH_MODEL,
    "fallback_list": OUROBOROS_MODEL_FALLBACK_LIST,
}

# ---- Version ----
VERSION = (REPO_DIR / "VERSION").read_text().strip() if (REPO_DIR / "VERSION").exists() else "0.0.0"

# ---- Logging setup ----
DRIVE_ROOT.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)