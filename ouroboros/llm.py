import json
import os
import re
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import requests
from openrouter import OpenRouter

from ouroboros.memory import update_state
from ouroboros.context import LLMContext
from ouroboros.utils import logger

@dataclass
class ModelSpec:
    name: str
    prompt_price: float
    completion_price: float
    context_window: int
    max_completion_tokens: int
    supports_system: bool
    supports_vision: bool

MODEL_SPECS = {
    'anthropic/claude-3.5-haiku': ModelSpec('anthropic/claude-3.5-haiku', 0.00045, 0.0015, 200_000, 4096, True, True),
    'anthropic/claude-3-haiku': ModelSpec('anthropic/claude-3-haiku', 0.00025, 0.00125, 200_000, 4096, True, True),
    'anthropic/claude-3.5-sonnet': ModelSpec('anthropic/claude-3.5-sonnet', 0.003, 0.015, 200_000, 4096, True, True),
    'anthropic/claude-3-sonnet': ModelSpec('anthropic/claude-3-sonnet', 0.003, 0.015, 200_000, 4096, True, True),
    'anthropic/claude-3-opus': ModelSpec('anthropic/claude-3-opus', 0.015, 0.075, 200_000, 4096, True, True),
    'openai/gpt-4o': ModelSpec('openai/gpt-4o', 0.005, 0.015, 128_000, 4096, True, True),
    'openai/gpt-4o-mini': ModelSpec('openai/gpt-4o-mini', 0.00015, 0.0006, 128_000, 4096, True, True),
    'openai/gpt-4': ModelSpec('openai/gpt-4', 0.03, 0.06, 8192, 4096, True, False),
    'google/gemini-1.5-flash': ModelSpec('google/gemini-1.5-flash', 0.00035, 0.00105, 1_048_576, 8192, True, True),
    'google/gemini-1.5-pro': ModelSpec('google/gemini-1.5-pro', 0.0035, 0.0105, 2_097_152, 8192, True, True),
    'meta-llama/llama-3.1-405b-instruct': ModelSpec('meta-llama/llama-3.1-405b-instruct', 0.001, 0.001, 131_072, 4096, True, False),
    'meta-llama/llama-3.1-70b-instruct': ModelSpec('meta-llama/llama-3.1-70b-instruct', 0.00059, 0.00059, 131_072, 4096, True, False),
    'stepfun/step-3.5-flash': ModelSpec('stepfun/step-3.5-flash', 0.0, 0.0, 32768, 512, False, False),
    'arcee-ai/trinity-large-preview': ModelSpec('arcee-ai/trinity-large-preview', 0.0, 0.0, 32768, 512, False, False),
    'google/gemini-2.0-flash': ModelSpec('google/gemini-2.0-flash', 0.0, 0.0, 4096, 512, False, False),
    'openai/gpt-oss-120b': ModelSpec('openai/gpt-oss-120b', 0.0, 0.0, 8192, 4096, False, False),
    'z-ai/glm-4.5-air': ModelSpec('z-ai/glm-4.5-air', 0.0, 0.0, 32768, 512, False, False),
    'anthropic/claude-3.5-haiku:beta': ModelSpec('anthropic/claude-3.5-haiku:beta', 0.00045, 0.0015, 200_000, 4096, True, True),
    'qwen/qwen3-72b': ModelSpec('qwen/qwen3-72b', 0.0, 0.0, 32768, 512, False, False),
    'nvidia/llama-3.1-nemotron-70b': ModelSpec('nvidia/llama-3.1-nemotron-70b', 0.0, 0.0, 8192, 4096, False, False),
    'google/gemini-2.5-flash': ModelSpec('google/gemini-2.5-flash', 0.0, 0.0, 32768, 512, False, False),
    'google/gemini-2.5-pro': ModelSpec('google/gemini-2.5-pro', 0.0, 0.0, 4096, 512, False, False),
    'qwen/qwen3-14b': ModelSpec('qwen/qwen3-14b', 0.0, 0.0, 32768, 512, False, False),
    'qwen/qwen3-8b': ModelSpec('qwen/qwen3-8b', 0.0, 0.0, 32768, 512, False, False),
    'qwen/qwen3-4b': ModelSpec('qwen/qwen3-4b', 0.0, 0.0, 32768, 512, False, False),
    'qwen/qwen3-1.5b': ModelSpec('qwen/qwen3-1.5b', 0.0, 0.0, 32768, 512, False, False),
    'qwen/qwen3-0.6b': ModelSpec('qwen/qwen3-0.6b', 0.0, 0.0, 32768, 512, False, False),
    'nvidia/llama-3.1-nemotron-70b': ModelSpec('nvidia/llama-3.1-nemotron-70b', 0.0, 0.0, 8192, 4096, False, False),
}

OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')

# Updated pricing fetch with precise decimal handling
MODEL_PRICING_CACHE = None
MODEL_PRICING_CACHE_TIME = 0
CACHE_EXPIRY = 3600  # 1 hour
current_provider = 'openrouter'

def fetch_openrouter_pricing():
    global MODEL_PRICING_CACHE, MODEL_PRICING_CACHE_TIME
    current_time = time.time()

    if MODEL_PRICING_CACHE is not None and current_time - MODEL_PRICING_CACHE_TIME < CACHE_EXPIRY:
        return MODEL_PRICING_CACHE

    try:
        response = requests.get(
            'https://openrouter.ai/api/v1/models',
            headers={'Authorization': f'Bearer {OPENROUTER_API_KEY}'}
        )
        response.raise_for_status()
        data = response.json()

        pricing = {}
        for model in data['data']:
            model_id = model['id']
            
            # Handle pricing units directly from API
            prompt_price = model['pricing']['prompt']
            completion_price = model['pricing']['completion']
            
            pricing[model_id] = {
                'prompt': float(prompt_price),
                'completion': float(completion_price)
            }

        MODEL_PRICING_CACHE = pricing
        MODEL_PRICING_CACHE_TIME = current_time
        return pricing
    except Exception as e:
        logger.error(f"Failed to fetch OpenRouter pricing: {e}")
        # Return known specs as fallback
        return {
            model: {
                'prompt': spec.prompt_price,
                'completion': spec.completion_price
            } for model, spec in MODEL_SPECS.items()
        }

class LLMInterface:
    def __init__(self):
        self.or_client = OpenRouter(api_key=OPENROUTER_API_KEY)

    def _resolve_provider(self, model_name: str) -> Tuple[str, str]:
        if model_name in MODEL_SPECS:
            return 'openrouter', model_name
        
        # Handle provider prefixes
        if ':' in model_name:
            provider, actual_model = model_name.split(':', 1)
            if provider == 'openrouter':
                return 'openrouter', actual_model
            # Add other providers as needed
            
        # Default: assume OpenRouter
        return 'openrouter', model_name

    async def run_model(
        self,
        ctx: LLMContext,
        system: Optional[str] = None,
        prompt: Optional[str] = None,
        images: Optional[List[str]] = None
    ) -> str:
        model = ctx.model
        provider, model_name = self._resolve_provider(model)

        try:
            # Fetch latest pricing (caches automatically)
            pricing = fetch_openrouter_pricing().get(model_name, {})
            
            # Calculate usage based on actual token counts
            prompt_tokens = ctx.prompt_tokens_used
            completion_tokens = ctx.completion_tokens_used
            
            prompt_cost = (prompt_tokens / 1_000_000) * pricing.get('prompt', 0)
            completion_cost = (completion_tokens / 1_000_000) * pricing.get('completion', 0)
            
            total_cost = prompt_cost + completion_cost
            
            # Record precise usage
            ctx.pending_events.append({
                'type': 'llm_usage',
                'model': model,
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'cost': round(total_cost, 6),  # 6 decimal precision for cents
                'provider': provider
            })

            # Actual API call would happen here
            response = await self._call_api(provider, model_name, system, prompt, images)
            return response
            
        except Exception as e:
            logger.error(f"API call failed: {e}")
            # Fallback to next model in provider chain
            return await self._handle_fallback(ctx, e)

    async def _call_api(self, provider: str, model: str, system: str, prompt: str, images: List[str]):
        # Implementation would handle different provider APIs
        if provider == 'openrouter':
            return await self.or_client.chat(
                model=model,
                messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
                images=images
            )
        # Handle other providers...
        
    async def _handle_fallback(self, ctx: LLMContext, error: Exception):
        # Fallback logic would rotate through provider chain
        current_index = ctx.provider_chain.index(ctx.current_provider)
        if current_index < len(ctx.provider_chain) - 1:
            ctx.current_provider = ctx.provider_chain[current_index + 1]
            return await self.run_model(ctx)
        raise error