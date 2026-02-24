# Existing code up to the end of LLMClient class (omitted for brevity)

def get_dynamic_context_limit(model: str) -> int:
    """
    Returns context limit for specific model based on free-tier constraints.
    Critical for TPM compliance (Principle 6: technical precision → agency)
    """
    limits = {
        'groq/': 4096,        # Free-tier TPM: 6k-12k
        'google/': 4096,      # Gemini 2.0 requires explicit cap
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
    Validates model against knowledge_base whitelist.
    Must be called before API request (Principle 6 enforcement).
    """
    from ouroboros.memory import Memory
    mem = Memory()
    valid_models = mem.load_knowledge('free-model-ids-openrouter').splitlines()
    if not any(model == vm.strip() for vm in valid_models):
        raise ValueError(f'Invalid free-tier model: {model}')
    # Confirm strict ID match (no version mismatch)
    if model not in valid_models:
        raise ValueError(f'Model version mismatch: use exact ID from knowledge_base')