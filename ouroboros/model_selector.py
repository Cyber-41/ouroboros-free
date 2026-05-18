"""
Ouroboros — Dynamic Free Model Selector.

Fetches the best available free LLM models from the daily-updated
shir-man.com API and provides model selection with caching.

Does not import anything from ouroboros.* (zero dependency level,
same as utils.py).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_URL = "https://shir-man.com/api/free-llm/top-models"
_CACHE_TTL_SEC = 6 * 3600  # 6 hours

# Hardcoded fallback list in case the API is down
_HARDCODED_FREE_MODELS = [
    {
        "id": "deepseek/deepseek-v4-flash:free",
        "score": 1050,
        "supportsTools": True,
        "contextLength": 1048576,
        "maxCompletionTokens": 393216,
        "supportsReasoning": False,
        "healthStatus": "all_ok",
    },
    {
        "id": "nvidia/nemotron-3-super-120b-a12b:free",
        "score": 1375,
        "supportsTools": True,
        "contextLength": 262144,
        "maxCompletionTokens": 262144,
        "supportsReasoning": True,
        "healthStatus": "partial",
    },
    {
        "id": "arcee-ai/trinity-large-thinking:free",
        "score": 975,
        "supportsTools": True,
        "contextLength": 262144,
        "maxCompletionTokens": 81920,
        "supportsReasoning": True,
        "healthStatus": "partial",
    },
    {
        "id": "qwen/qwen3-coder:free",
        "score": 800,
        "supportsTools": True,
        "contextLength": 262144,
        "maxCompletionTokens": 65536,
        "supportsReasoning": False,
        "healthStatus": "partial",
    },
]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cached_models: Optional[List[Dict[str, Any]]] = None
_cached_at: float = 0.0


def _is_cache_valid() -> bool:
    return _cached_models is not None and (time.time() - _cached_at) < _CACHE_TTL_SEC


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------

def fetch_top_free_models(timeout: int = 10) -> List[Dict[str, Any]]:
    """Fetch top free models from the shir-man API.

    Returns list of model dicts sorted by score (descending).
    Falls back to hardcoded list on any error.
    """
    global _cached_models, _cached_at

    with _cache_lock:
        if _is_cache_valid():
            return list(_cached_models)  # type: ignore[arg-type]

    try:
        req = urllib.request.Request(
            _API_URL,
            headers={"User-Agent": "Ouroboros/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # API returns a dict with "models" key containing the list
        if isinstance(data, dict):
            models = data.get("models", [])
        elif isinstance(data, list):
            models = data
        else:
            models = []

        if not models:
            log.warning("shir-man API returned empty model list, using hardcoded fallback")
            models = list(_HARDCODED_FREE_MODELS)
        else:
            # Normalize field names — API uses 'id' as the model identifier
            normalized = []
            for m in models:
                normalized.append({
                    "id": m.get("id") or m.get("modelId") or "",
                    "score": int(m.get("score") or m.get("compositeScore") or 0),
                    "supportsTools": bool(m.get("supportsTools", False)),
                    "contextLength": int(m.get("contextLength") or 0),
                    "maxCompletionTokens": int(m.get("maxCompletionTokens") or 0),
                    "supportsReasoning": bool(m.get("supportsReasoning", False)),
                    "healthStatus": str(m.get("healthStatus") or "unknown"),
                })
            models = normalized

        # Sort by score descending
        models.sort(key=lambda x: x.get("score", 0), reverse=True)

        with _cache_lock:
            _cached_models = models
            _cached_at = time.time()

        log.info("Fetched %d free models from shir-man API (top: %s, score=%d)",
                 len(models),
                 models[0].get("id", "?") if models else "none",
                 models[0].get("score", 0) if models else 0)
        return list(models)

    except Exception as e:
        log.warning("Failed to fetch free models from API: %s — using hardcoded fallback", e)
        with _cache_lock:
            if _cached_models is not None:
                return list(_cached_models)
        return list(_HARDCODED_FREE_MODELS)


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------

def _filter_models(
    models: List[Dict[str, Any]],
    require_tools: bool = True,
    min_completion_tokens: int = 0,
    exclude_unhealthy: bool = True,
) -> List[Dict[str, Any]]:
    """Filter models by capabilities."""
    result = []
    for m in models:
        if require_tools and not m.get("supportsTools"):
            continue
        if min_completion_tokens > 0:
            max_out = m.get("maxCompletionTokens") or 0
            if max_out < min_completion_tokens:
                continue
        if exclude_unhealthy:
            health = str(m.get("healthStatus") or "").lower()
            if health in ("timeout_or_error", "all_failed", "error"):
                continue
        result.append(m)
    return result


def select_primary_model() -> str:
    """Select the best free model for primary agent use.

    Requirements: tool support, >= 16K completion tokens, healthy.
    """
    models = fetch_top_free_models()
    candidates = _filter_models(models, require_tools=True, min_completion_tokens=16384)
    if candidates:
        return candidates[0]["id"]
    # Relaxed: any model with tools
    candidates = _filter_models(models, require_tools=True, exclude_unhealthy=False)
    if candidates:
        return candidates[0]["id"]
    return "deepseek/deepseek-v4-flash:free"


def select_light_model() -> str:
    """Select a lightweight free model for background tasks (consciousness, summaries).

    Optimized for low latency and low cost. Smaller models preferred.
    """
    models = fetch_top_free_models()
    candidates = _filter_models(models, require_tools=True, min_completion_tokens=4096)
    # Prefer models with smaller context (proxy for "lighter")
    # but still capable
    if len(candidates) > 1:
        # Return the 2nd best or a specifically light model
        for c in candidates:
            mid = c.get("id", "")
            # Prefer nano/small/mini variants
            if any(tag in mid.lower() for tag in ("nano", "mini", "small", "flash")):
                return mid
        # Fallback to 2nd best (save the primary for main tasks)
        return candidates[1]["id"] if len(candidates) > 1 else candidates[0]["id"]
    if candidates:
        return candidates[0]["id"]
    return "deepseek/deepseek-v4-flash:free"


def select_code_model() -> str:
    """Select the best free model for code editing.

    Requirements: high max_completion_tokens (>= 32K), tool support.
    """
    # First check env override
    env_code = os.environ.get("OUROBOROS_MODEL_CODE", "")
    if env_code:
        return env_code

    models = fetch_top_free_models()
    candidates = _filter_models(models, require_tools=True, min_completion_tokens=32768)
    if candidates:
        # Prefer models with "code" or "coder" in name
        for c in candidates:
            mid = c.get("id", "")
            if "code" in mid.lower() or "coder" in mid.lower():
                return mid
        return candidates[0]["id"]
    # Fallback: any model with decent output
    candidates = _filter_models(models, require_tools=True, min_completion_tokens=16384)
    if candidates:
        return candidates[0]["id"]
    return "qwen/qwen3-coder:free"


def get_fallback_chain(exclude_model: str = "") -> List[str]:
    """Build a fallback chain from available free models.

    Excludes the primary model (already tried).
    Returns list of model IDs sorted by score.
    """
    models = fetch_top_free_models()
    candidates = _filter_models(models, require_tools=True)
    chain = []
    seen = set()
    for c in candidates:
        mid = c["id"]
        if mid == exclude_model or mid in seen:
            continue
        seen.add(mid)
        chain.append(mid)

    # Always add these ultra-stable fallbacks at the end if not already present
    ultimate_fallbacks = [
        "deepseek/deepseek-v4-flash:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
    ]
    for fb in ultimate_fallbacks:
        if fb not in seen and fb != exclude_model:
            chain.append(fb)

    return chain


def get_model_info(model_id: str) -> Optional[Dict[str, Any]]:
    """Get cached info about a specific model, or None if not found."""
    models = fetch_top_free_models()
    for m in models:
        if m.get("id") == model_id:
            return dict(m)
    return None


def is_free_model(model_id: str) -> bool:
    """Check if a model is a free-tier model.

    Heuristic: model ID ends with ':free' or is in our free models list.
    """
    if model_id.endswith(":free"):
        return True
    models = fetch_top_free_models()
    return any(m.get("id") == model_id for m in models)


def invalidate_cache() -> None:
    """Force cache refresh on next call."""
    global _cached_models, _cached_at
    with _cache_lock:
        _cached_models = None
        _cached_at = 0.0
