def get_dynamic_context_limit(model: str) -> int:
    """
    Returns context limit for specific model based on free-tier constraints.
    Critical for TPM compliance (Principle 6: technical precision → agency)
    """
    limits = {
        'groq/': 4096,        # Free-tier TPM: 6k-12k
        'google/': 4096,      # Legacy OpenRouter routing
        'gemini-': 4096,      # Direct Google API models (2026)
        'stepfun/': 8192,     # Verified free tier (30k TPM)
        'arcee-ai/': 8192,    # Free preview tier
        'z-ai/': 8192,        # GLM-4.5-AIR free tier
        'qwen/': 8192,        # Qwen Next free tier
    }
    for prefix, limit in limits.items():
        if model.startswith(prefix):
            return limit
    return 8192  # Default for known providers (avoid 200k cap)

def validate_free_tier_model(model: str) -> None:
    """
    Validates model against knowledge base with provider-specific rules.
    Handles direct Google API models separately from OpenRouter.
    """
    from ouroboros.memory import Memory
    mem = Memory()

    # Special handling for direct Google API calls (2026 models)
    if model.startswith('gemini-'):
        valid_google_models = [
            'gemini-3-flash',
            'gemini-2.5-flash',
            'gemini-1.5-flash',
            'gemini-1.5-pro',
            'gemini-1.0-pro',
            'imagen-3',
        ]
        if model not in valid_google_models:
            raise ValueError(f'Invalid Google model: {model} (use gemini-3-flash etc)')
        return

    # Legacy OpenRouter routing (remove after full Google API transition)
    if model.startswith('google/'):
        google_model = model.replace('google/', '', 1)
        valid_google_models_legacy = [
            'gemini-1.5-flash',
            'gemini-1.5-pro',
            'gemini-1.0-pro',
        ]
        if google_model not in valid_google_models_legacy:
            raise ValueError(f'Invalid Google model: {google_model} (use gemini-1.5-flash etc)')
        return

    # OpenRouter model validation
    valid_models = mem.load_knowledge('free-model-ids-openrouter').splitlines()
    if not any(model == vm.strip() for vm in valid_models):
        raise ValueError(f'Invalid free-tier model: {model}')