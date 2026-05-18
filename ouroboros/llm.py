"""
Ouroboros — LLM client.

The only module that communicates with the LLM API.
Supports multiple providers via OpenAI-compatible endpoints.
Contract: chat(), default_model(), available_models(), add_usage().
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

DEFAULT_LIGHT_MODEL = "deepseek/deepseek-v4-flash:free"

_MODEL_CONFIG_PATH = pathlib.Path("/content/drive/MyDrive/Ouroboros/model_config.json")

# Groq hard limit on max_tokens
_GROQ_MAX_TOKENS = 8192


def _load_model_config() -> Dict[str, Any]:
    """Load model config from Drive if it exists."""
    try:
        if _MODEL_CONFIG_PATH.exists():
            with open(_MODEL_CONFIG_PATH) as f:
                return json.load(f)
    except Exception as e:
        log.debug("Failed to load model_config.json: %s", e)
    return {}


# ---------------------------------------------------------------------------
# Provider routing table
#
# Key   = model prefix (или "_default" для fallback)
# Value = {
#   "base_url"        : OpenAI-compatible endpoint,
#   "key_env"         : имя env-переменной с API ключом,
#   "model_strip"     : prefix, который нужно отрезать от названия модели,
#   "headers"         : дополнительные HTTP-заголовки (только для OpenRouter),
#   "openrouter"      : True — включает OpenRouter-специфичные фичи
#                       (reasoning, provider pinning, cache_control, generation cost),
# }
# ---------------------------------------------------------------------------
_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "google/": {
        "base_url":     "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env":      "GOOGLE_API_KEY",
        "model_strip":  "google/",
        "headers":      {},
        "openrouter":   False,
    },
    "groq/": {
        "base_url":     "https://api.groq.com/openai/v1",
        "key_env":      "GROQ_API_KEY",
        "model_strip":  "groq/",
        "headers":      {},
        "openrouter":   False,
    },
    "mistral/": {
        "base_url":     "https://api.mistral.ai/v1",
        "key_env":      "MISTRAL_API_KEY",
        "model_strip":  "mistral/",
        "headers":      {},
        "openrouter":   False,
    },
    "together/": {
        "base_url":     "https://api.together.xyz/v1",
        "key_env":      "TOGETHER_API_KEY",
        "model_strip":  "together/",
        "headers":      {},
        "openrouter":   False,
    },
    "_default": {
        "base_url":     "https://openrouter.ai/api/v1",
        "key_env":      "OPENROUTER_API_KEY",
        "model_strip":  "",
        "headers": {
            "HTTP-Referer": "https://colab.research.google.com/",
            "X-Title": "Ouroboros",
        },
        "openrouter":   True,
    },
}


def _resolve_provider(model: str) -> Tuple[Dict[str, Any], str]:
    """
    По имени модели возвращает (provider_config, resolved_model_name).

    Например: "google/gemini-2.0-flash" -> (google_cfg, "gemini-2.0-flash")
              "anthropic/claude-sonnet-4.6" -> (openrouter_cfg, "anthropic/claude-sonnet-4.6")
    """
    for prefix, cfg in _PROVIDERS.items():
        if prefix != "_default" and model.startswith(prefix):
            resolved = model[len(cfg["model_strip"]):]
            return cfg, resolved
    return _PROVIDERS["_default"], model


def _normalize_content(value: Any) -> str:
    """Convert content field to plain string for non-OpenRouter providers.

    OpenRouter accepts both string and list[{"type":"text","text":"..."}].
    Direct providers (Mistral, Groq, Google, Together) require plain string.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item["text"])
                elif item.get("type") == "image_url":
                    parts.append("[image]")
                else:
                    parts.append(str(item.get("text", item)))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(value)


def _normalize_messages_for_direct_provider(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Normalize messages so that content fields are plain strings.

    Some providers (Mistral, Groq, Google) reject content as a list of
    {"type":"text","text":"..."} dicts. This flattens them to string.
    Only system and user roles are normalized — assistant messages with
    tool_calls are left alone.
    """
    result = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")
        if content is not None and role in ("system", "user"):
            msg = {**msg, "content": _normalize_content(content)}
        result.append(msg)
    return result


def normalize_reasoning_effort(value: str, default: str = "medium") -> str:
    allowed = {"none", "minimal", "low", "medium", "high", "xhigh"}
    v = str(value or "").strip().lower()
    return v if v in allowed else default


def reasoning_rank(value: str) -> int:
    order = {"none": 0, "minimal": 1, "low": 2, "medium": 3, "high": 4, "xhigh": 5}
    return int(order.get(str(value or "").strip().lower(), 3))


def add_usage(total: Dict[str, Any], usage: Dict[str, Any]) -> None:
    """Accumulate usage from one LLM call into a running total."""
    for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "cache_write_tokens"):
        total[k] = int(total.get(k) or 0) + int(usage.get(k) or 0)
    if usage.get("cost"):
        total["cost"] = float(total.get("cost") or 0) + float(usage["cost"])


def fetch_openrouter_pricing() -> Dict[str, Tuple[float, float, float]]:
    """Fetch current pricing from OpenRouter API.

    Returns dict of {model_id: (input_per_1m, cached_per_1m, output_per_1m)}.
    Returns empty dict on failure.
    """
    try:
        import requests
    except ImportError:
        log.warning("requests not installed, cannot fetch pricing")
        return {}

    try:
        url = "https://openrouter.ai/api/v1/models"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()

        data = resp.json()
        models = data.get("data", [])

        prefixes = ("anthropic/", "openai/", "google/", "meta-llama/", "x-ai/", "qwen/")

        pricing_dict = {}
        for model in models:
            model_id = model.get("id", "")
            if not model_id.startswith(prefixes):
                continue

            pricing = model.get("pricing", {})
            if not pricing or not pricing.get("prompt"):
                continue

            raw_prompt = float(pricing.get("prompt", 0))
            raw_completion = float(pricing.get("completion", 0))
            raw_cached_str = pricing.get("input_cache_read")
            raw_cached = float(raw_cached_str) if raw_cached_str else None

            prompt_price = round(raw_prompt * 1_000_000, 4)
            completion_price = round(raw_completion * 1_000_000, 4)
            if raw_cached is not None:
                cached_price = round(raw_cached * 1_000_000, 4)
            else:
                cached_price = round(prompt_price * 0.1, 4)

            if prompt_price > 1000 or completion_price > 1000:
                log.warning(f"Skipping {model_id}: prices seem wrong (prompt={prompt_price}, completion={prompt_price})")
                continue

            pricing_dict[model_id] = (prompt_price, cached_price, completion_price)

        log.info(f"Fetched pricing for {len(pricing_dict)} models from OpenRouter")
        return pricing_dict

    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning(f"Failed to fetch OpenRouter pricing: {e}")
        return {}


class LLMClient:
    """
    Multi-provider LLM client с единым интерфейсом.

    Роутинг по префиксу модели:
      google/*   -> Google AI Studio (OpenAI-compat, бесплатный tier)
      groq/*     -> Groq             (OpenAI-compat, бесплатный tier)
      mistral/*  -> Mistral AI      (OpenAI-compat, прямой API)
      together/* -> Together AI      (OpenAI-compat)
      всё остальное -> OpenRouter

    Все провайдеры используют один и тот же openai.OpenAI клиент —
    только с разным base_url и api_key.
    """

    def __init__(self, api_key=None):
        # Кэш клиентов по base_url чтобы не пересоздавать
        self._clients: Dict[str, Any] = {}

    def _get_client(self, provider_cfg: Dict[str, Any]):
        """Получить или создать openai.OpenAI клиент для провайдера."""
        base_url = provider_cfg["base_url"]
        if base_url not in self._clients:
            from openai import OpenAI
            api_key = os.environ.get(provider_cfg["key_env"], "")
            if not api_key:
                raise ValueError(
                    f"API key not found. Set env var: {provider_cfg['key_env']}"
                )
            self._clients[base_url] = OpenAI(
                base_url=base_url,
                api_key=api_key,
                default_headers=provider_cfg.get("headers", {}),
            )
        return self._clients[base_url]

    def _fetch_generation_cost(self, generation_id: str, base_url: str, api_key: str) -> Optional[float]:
        """Fetch cost from OpenRouter Generation API as fallback (только для OpenRouter)."""
        try:
            import requests
            url = f"{base_url.rstrip('/')}/generation?id={generation_id}"
            headers = {"Authorization": f"Bearer {api_key}"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json().get("data") or {}
                cost = data.get("total_cost") or data.get("usage", {}).get("cost")
                if cost is not None:
                    return float(cost)
            time.sleep(0.5)
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json().get("data") or {}
                cost = data.get("total_cost") or data.get("usage", {}).get("cost")
                if cost is not None:
                    return float(cost)
        except Exception:
            log.debug("Failed to fetch generation cost from OpenRouter", exc_info=True)
        return None

    def chat(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        reasoning_effort: str = "medium",
        max_tokens: int = 16384,
        tool_choice: str = "auto",
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Single LLM call. Returns: (response_message_dict, usage_dict with cost).

        Автоматически выбирает провайдера по префиксу модели.
        """
        provider_cfg, resolved_model = _resolve_provider(model)
        is_openrouter = provider_cfg["openrouter"]

        client = self._get_client(provider_cfg)
        effort = normalize_reasoning_effort(reasoning_effort)

        # Normalize messages for direct providers (non-OpenRouter).
        # They reject content as list[{"type":"text",...}] — need plain string.
        if not is_openrouter:
            messages = _normalize_messages_for_direct_provider(messages)

        kwargs: Dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        # Groq has a hard limit of 8192 on max_tokens
        if model.startswith("groq/") and max_tokens > _GROQ_MAX_TOKENS:
            kwargs["max_tokens"] = _GROQ_MAX_TOKENS
            log.debug("[LLM] Groq max_tokens capped to %d", _GROQ_MAX_TOKENS)

        # OpenRouter-специфичные параметры
        if is_openrouter:
            extra_body: Dict[str, Any] = {}
            # Reasoning — only if effort is meaningful (free models may not support)
            if effort not in ("none", "minimal"):
                extra_body["reasoning"] = {"effort": effort, "exclude": True}
            # Pin Anthropic models to Anthropic provider — only for paid models
            # Free models (:free suffix) go through OpenRouter's default routing
            if model.startswith("anthropic/") and not model.endswith(":free"):
                extra_body["provider"] = {
                    "order": ["Anthropic"],
                    "allow_fallbacks": False,
                    "require_parameters": True,
                }
            kwargs["extra_body"] = extra_body

            if tools:
                # cache_control on tools — only for paid models that support it
                if not model.endswith(":free"):
                    tools_with_cache = list(tools)
                    if tools_with_cache:
                        last_tool = {**tools_with_cache[-1]}
                        last_tool["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
                        tools_with_cache[-1] = last_tool
                    kwargs["tools"] = tools_with_cache
                else:
                    kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice
        else:
            # Прямые провайдеры — чистый OpenAI-совместимый запрос
            # (без cache_control, reasoning, provider pinning)
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice
            log.debug(f"[LLM] Routing {model!r} -> {provider_cfg['base_url']} as {resolved_model!r}")

        resp = client.chat.completions.create(**kwargs)
        resp_dict = resp.model_dump()
        usage = resp_dict.get("usage") or {}
        choices = resp_dict.get("choices") or [{}]
        msg = (choices[0] if choices else {}).get("message") or {}

        # Извлечь cached_tokens из prompt_tokens_details если есть
        if not usage.get("cached_tokens"):
            prompt_details = usage.get("prompt_tokens_details") or {}
            if isinstance(prompt_details, dict) and prompt_details.get("cached_tokens"):
                usage["cached_tokens"] = int(prompt_details["cached_tokens"])

        # Извлечь cache_write_tokens
        if not usage.get("cache_write_tokens"):
            prompt_details_for_write = usage.get("prompt_tokens_details") or {}
            if isinstance(prompt_details_for_write, dict):
                cache_write = (prompt_details_for_write.get("cache_write_tokens")
                              or prompt_details_for_write.get("cache_creation_tokens")
                              or prompt_details_for_write.get("cache_creation_input_tokens"))
                if cache_write:
                    usage["cache_write_tokens"] = int(cache_write)

        # Cost: for OpenRouter paid models only
        # Free models (:free suffix) always have cost=0 — skip the HTTP call
        if is_openrouter and not usage.get("cost"):
            if model.endswith(":free"):
                usage["cost"] = 0.0
            else:
                gen_id = resp_dict.get("id") or ""
                if gen_id:
                    api_key = os.environ.get(provider_cfg["key_env"], "")
                    cost = self._fetch_generation_cost(gen_id, provider_cfg["base_url"], api_key)
                    if cost is not None:
                        usage["cost"] = cost

        return msg, usage

    def vision_query(
        self,
        prompt: str,
        images: List[Dict[str, Any]],
        model: str = "",
        max_tokens: int = 1024,
        reasoning_effort: str = "low",
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Send a vision query to an LLM. Lightweight — no tools, no loop.

        Args:
            prompt: Text instruction for the model
            images: List of image dicts. Each dict must have either:
                - {"url": "https://..."} — for URL images
                - {"base64": "<b64>", "mime": "image/png"} — for base64 images
            model: VLM-capable model ID
            max_tokens: Max response tokens
            reasoning_effort: Effort level

        Returns:
            (text_response, usage_dict)
        """
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in images:
            if "url" in img:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": img["url"]},
                })
            elif "base64" in img:
                mime = img.get("mime", "image/png")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{img['base64']}"},
                })
            else:
                log.warning("vision_query: skipping image with unknown format: %s", list(img.keys()))

        if not model:
            model = self.default_model()
        messages = [{"role": "user", "content": content}]
        response_msg, usage = self.chat(
            messages=messages,
            model=model,
            tools=None,
            reasoning_effort=reasoning_effort,
            max_tokens=max_tokens,
        )
        text = response_msg.get("content") or ""
        return text, usage

    def default_model(self) -> str:
        """Return the default model: model_config > env > dynamic free model selection."""
        config = _load_model_config()
        cfg_model = config.get("primary")
        if cfg_model:
            return cfg_model
        env_model = os.environ.get("OUROBOROS_MODEL", "")
        if env_model:
            return env_model
        try:
            from ouroboros.model_selector import select_primary_model
            return select_primary_model()
        except Exception:
            log.debug("model_selector failed, using hardcoded fallback", exc_info=True)
            return "deepseek/deepseek-v4-flash:free"

    def available_models(self) -> List[str]:
        """Return list of available models from model_config + env + free API."""
        models = []
        config = _load_model_config()

        # From model_config (Drive) — primary source of truth
        for key in ("primary", "code", "light"):
            m = config.get(key)
            if m and m not in models:
                models.append(m)

        # From env override
        env_models = {
            "primary": "OUROBOROS_MODEL",
            "code": "OUROBOROS_MODEL_CODE",
            "light": "OUROBOROS_MODEL_LIGHT",
        }
        for key, env_var in env_models.items():
            m = config.get(key) or os.environ.get(env_var)
            if m and m not in models:
                models.append(m)

        if not models:
            models.append(self.default_model())

        # Add free models from API as additional options
        try:
            from ouroboros.model_selector import get_fallback_chain
            main = models[0] if models else ""
            for m in get_fallback_chain(exclude_model=main):
                if m not in models:
                    models.append(m)
        except Exception:
            log.debug("Failed to get fallback chain for available_models", exc_info=True)
        return models


def normalize_fallback_errors(errors: List[str]) -> List[str]:
    """Collapse repeated identical fallback errors into single entries."""
    seen = set()
    result = []
    for err in errors:
        # Hash just the error type/model, not the full 19K traceback
        key = err[:200]
        if key not in seen:
            seen.add(key)
            result.append(err)
    return result
