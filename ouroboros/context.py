# Corrected context cap logic to respect free-tier TPM limits

def get_dynamic_context_limit(model_id: str) -> int:
    """Returns safe context limit for model to avoid TPM errors"""
    limits = {
        'groq/': 4096,  # Matches 6k TPM free tier
        'google/': 4096, # Verified gemini-2.0-flash
        'stepfun/': 8192  # Confirmed with knowledge_base/free-model-ids
    }
    return next((v for k, v in limits.items() if model_id.startswith(k)), 8192)

# Existing code now uses this for ALL requests:
messages, cap_info = apply_message_token_soft_cap(messages, get_dynamic_context_limit(model_id))