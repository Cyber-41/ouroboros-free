"""
Ouroboros — Startup health checks.

Verifies that the runtime environment is capable of running
before entering the main supervisor loop. This is especially
important for free models which may have intermittent availability.

Run during launcher startup, before spawning workers.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Optional, Tuple

log = logging.getLogger(__name__)


def check_openrouter_api(timeout: int = 10) -> Tuple[bool, str]:
    """Verify that OpenRouter API is reachable and the key is valid.

    Returns (ok, message).
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return False, "OPENROUTER_API_KEY not set"

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            label = data.get("data", {}).get("label", "unknown")
            limit = data.get("data", {}).get("limit", None)
            usage = data.get("data", {}).get("usage", 0)
            rate_limit = data.get("data", {}).get("rate_limit", {})

            info = f"API key valid (label={label}, usage=${usage:.2f}"
            if limit:
                info += f", limit=${limit}"
            info += ")"

            if rate_limit:
                requests_limit = rate_limit.get("requests", "?")
                interval = rate_limit.get("interval", "?")
                info += f" Rate limit: {requests_limit} req/{interval}"

            return True, info

    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Invalid API key (401 Unauthorized)"
        if e.code == 429:
            return False, "Rate limited (429). Wait before retrying."
        return False, f"HTTP error: {e.code} {e.reason}"
    except Exception as e:
        return False, f"Connection error: {e}"


def check_free_model_availability(timeout: int = 15) -> Tuple[bool, str]:
    """Verify that at least one free model responds to a simple request.

    Sends a minimal chat request and checks for a valid response.
    Returns (ok, message).
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return False, "OPENROUTER_API_KEY not set"

    # Try the primary model first, then fallbacks
    primary = os.environ.get("OUROBOROS_MODEL", "deepseek/deepseek-v4-flash:free")
    models_to_try = [primary]
    if not primary.endswith(":free"):
        models_to_try.append("deepseek/deepseek-v4-flash:free")

    for model in models_to_try:
        try:
            payload = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": "Say 'ok' and nothing else."}],
                "max_tokens": 5,
            }).encode("utf-8")

            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://colab.research.google.com/",
                    "X-Title": "Ouroboros",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    if content:
                        return True, f"Model {model} responded: '{content[:50]}'"
                return False, f"Model {model} returned empty response"

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")[:200]
            except Exception:
                pass
            log.warning("Model %s health check failed: HTTP %d — %s", model, e.code, error_body)
            continue
        except Exception as e:
            log.warning("Model %s health check failed: %s", model, e)
            continue

    return False, "No free model responded to health check"


def check_free_models_api(timeout: int = 10) -> Tuple[bool, str]:
    """Check if the shir-man.com free models API is reachable."""
    try:
        from ouroboros.model_selector import fetch_top_free_models
        models = fetch_top_free_models(timeout=timeout)
        if models:
            top = models[0].get("modelId", "?")
            return True, f"Free models API OK: {len(models)} models (top: {top})"
        return False, "Free models API returned empty list"
    except Exception as e:
        return False, f"Free models API unreachable: {e}"


def run_startup_checks(retry_on_failure: bool = True, max_retries: int = 3,
                        retry_delay_sec: int = 60) -> bool:
    """Run all startup health checks.

    If retry_on_failure is True, will retry failed checks up to max_retries times
    with retry_delay_sec between attempts.

    Returns True if all critical checks passed.
    """
    checks = [
        ("OpenRouter API", check_openrouter_api),
        ("Free Models API", check_free_models_api),
        ("Model Availability", check_free_model_availability),
    ]

    for attempt in range(1, max_retries + 1):
        all_ok = True
        results = []

        for name, check_fn in checks:
            try:
                ok, msg = check_fn()
            except Exception as e:
                ok, msg = False, f"Check crashed: {e}"

            status = "✅" if ok else "❌"
            results.append(f"  {status} {name}: {msg}")
            if not ok:
                all_ok = False

        log.info("Health check (attempt %d/%d):\n%s", attempt, max_retries, "\n".join(results))

        if all_ok:
            return True

        if not retry_on_failure or attempt >= max_retries:
            break

        log.warning("Some health checks failed. Retrying in %ds...", retry_delay_sec)
        time.sleep(retry_delay_sec)

    # Even if model availability fails, API key is the critical one
    # We can still try to run with the model selector fallbacks
    api_ok, _ = check_openrouter_api()
    if api_ok:
        log.warning("Model availability check failed but API key is valid. Continuing with best-effort model selection.")
        return True

    return False
