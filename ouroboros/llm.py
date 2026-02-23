from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type, Union, cast

from openai import AsyncOpenAI
from ouroboros.llm_openrouter import OpenRouterLLM
from ouroboros.tools import ToolSchema
from ouroboros.utils import utc_now_iso

log = logging.getLogger(__name__)


@dataclass
class LLMUsage:
    """Track token usage per request."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_prompt_tokens: int = 0
    llm_api_seconds: float = 0.0

    def dict(self):
        return {
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'total_tokens': self.total_tokens,
            'cached_prompt_tokens': self.cached_prompt_tokens,
            'llm_api_seconds': self.llm_api_seconds,
        }

    @classmethod
    def from_openrouter(cls, usage: Dict) -> LLMUsage:
        return cls(
            prompt_tokens=usage.get('prompt_tokens', 0),
            completion_tokens=usage.get('completion_tokens', 0),
            total_tokens=usage.get('total_tokens', 0),
            cached_prompt_tokens=usage.get('cached_prompt_tokens', 0),
        )


class LLMClient:
    def __init__(self):
        self.usage_events: List[Dict] = []
        self._openrouter = OpenRouterLLM()

    def add_usage(self, event: Dict, usage: LLMUsage, model: str):
        """Guarantee model field for all emissions."""
        event.setdefault('model', model)
        self.usage_events.append({**event, **usage.dict()})

    async def _execute_single_round(
        self,
        messages: List[Dict],
        ctx: LLMContext,
        tools: Optional[Dict[str, ToolSchema]] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[LLMResponse, LLMUsage]:
        """Core routing logic with unified model handling."""
        if not ctx.model:
            raise ValueError("No model specified in context")

        start_time = time.time()
        try:
            if ctx.model.startswith('openrouter/'):
                # Handle OpenRouter models
                res = await self._openrouter.chat(
                    messages=messages,
                    model=ctx.model,
                    tools=tools,
                    max_tokens=max_tokens,
                )
            else:
                # Fallback for other providers (OpenAI-style)
                client = AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'])
                res = await client.chat.completions.create(
                    model=ctx.model,
                    messages=messages,
                    tools=tools,
                    max_tokens=max_tokens,
                    timeout=30,
                )

            elapsed = time.time() - start_time
            usage = LLMUsage.from_openrouter(res.get('usage', {}))
            usage.llm_api_seconds = elapsed

            # Guarantee model field
            self.add_usage(
                event={
                    'type': 'llm_usage',
                    'task_id': ctx.task_id,
                },
                usage=usage,
                model=ctx.model,
            )

            return LLMResponse.from_response(res), usage

        except Exception as e:
            elapsed = time.time() - start_time
            log.error(f"LLM call failed: {e}", exc_info=True)
            raise

    async def _with_fallbacks(
        self,
        messages: List[Dict],
        ctx: LLMContext,
        tools: Optional[Dict[str, ToolSchema]] = None,
        max_tokens: Optional[int] = None,
        max_retries: int = 2
    ):
        """Robust fallback chain with comprehensive error handling."""
        last_exception = None
        for i in range(max_retries + 1):
            try:
                return await self._execute_single_round(
                    messages=messages,
                    ctx=ctx,
                    tools=tools,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                last_exception = e
                next_model = self._next_fallback_model(ctx.model)
                if next_model is None:
                    break
                log.warning(f"Fallback: {ctx.model} → {next_model} (attempt {i+1})")
                ctx.model = next_model

        if last_exception:
            raise last_exception
        raise RuntimeError("All fallback models failed")

    def _next_fallback_model(self, current_model: str) -> Optional[str]:
        """Return next valid model in chain or None."""
        fallback_chain = os.environ.get('OUROBOROS_MODEL_FALLBACK_LIST', '').split(',')
        try:
            idx = fallback_chain.index(current_model)
            return fallback_chain[idx + 1] if idx + 1 < len(fallback_chain) else None
        except (ValueError, IndexError):
            return fallback_chain[0] if fallback_chain else None