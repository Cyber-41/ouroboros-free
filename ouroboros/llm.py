import os
from typing import Any, Dict, List, Optional, Tuple

import httpx
from requests.models import Response

from .utils import getenv_or_fail

# Model routing configuration
GOOGLE_API_MODELS = ['gemini-3-flash', 'gemini-2.5-pro']
PREFER_OPENROUTER_MODELS = True

# Pricing constants
MODEL_PRICING = {
    # OpenRouter standard models
    'anthropic/claude-3-sonnet': (3.0, 15.0),
    'anthropic/claude-3-haiku': (0.25, 1.25),
    'openai/gpt-4o-mini': (0.15, 0.6),
    # Free tier models
    'stepfun/step-3.5-flash:free': (0.0, 0.0),
    'arcee-ai/trinity-large-preview:free': (0.0, 0.0),
    'z-ai/glm-4.5-air:free': (0.0, 0.0),
    'qwen/qwen3-next-80b-a3b-instruct:free': (0.0, 0.0),
    'openai/gpt-oss-120b:free': (0.0, 0.0),
    # Google direct API models
    'gemini-3-flash': (0.0, 0.0),
    'gemini-2.5-pro': (0.0, 0.0),
}

# Default models
DEFAULT_LIGHT_MODEL = 'gemini-3-flash'
DEFAULT_HEAVY_MODEL = 'gemini-2.5-pro'

# Constants
OPENROUTER_API_URL = 'https://openrouter.ai/api/v1/chat/completions'
GOOGLE_API_URL = 'https://generativelanguage.googleapis.com/v1beta/models'

# Environment variables
OPENROUTER_API_KEY = getenv_or_fail('OPENROUTER_API_KEY')
GOOGLE_API_KEY = getenv_or_fail('GOOGLE_API_KEY')

# Validation logic
def _validate_google_model(model_id: str) -> bool:
    """Validate and route Google API models."""
    # Check if model is in Google's API
    parts = model_id.split('/')
    if len(parts) == 2:
        # Handle OpenRouter-style IDs (google/gemini-2.5-flash)
        return parts[0] == 'google' and parts[1] in GOOGLE_API_MODELS
    elif model_id in GOOGLE_API_MODELS:
        # Native Google API IDs (gemini-3-flash)
        return True
    return False
def validate_model(model_id: str) -> bool:
    """Validate model ID with provider-specific rules."""
    # Bypass OpenRouter validation for native Google models
    if model_id == 'gemini-3-flash' and not os.environ.get('PAID_TIER'):
        return _validate_google_model(model_id)
    
    if ':' in model_id:
        # Free model with tag (stepfun/step-3.5-flash:free)
        return model_id in MODEL_PRICING
    
    # Standard OpenRouter model (anthropic/claude-...)
    parts = model_id.split('/')
    return len(parts) == 2 and model_id in MODEL_PRICING

def get_api_endpoint(model_id: str) -> Tuple[str, Optional[str]]:
    """Return the correct API endpoint and API key for the model."""
    if model_id in GOOGLE_API_MODELS or (model_id.startswith('google/') and model_id.split('/')[1] in GOOGLE_API_MODELS):
        return (
            f"{GOOGLE_API_URL}/{model_id.split('/')[-1]}:generateContent",
            GOOGLE_API_KEY
        )
    return (OPENROUTER_API_URL, OPENROUTER_API_KEY)
