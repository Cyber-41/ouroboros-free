def _validate_google_model(model_id: str) -> bool:
    """Validate Google AI Studio model names (2026 free tier)"""
    return model_id == 'gemini-3-flash'

def get_llm_client(model_id: str):
    if model_id.startswith('google/'):
        # Strip OpenRouter prefix
        clean_id = model_id.split('/', 1)[1]
        if _validate_google_model(clean_id):
            return GoogleAIClient(clean_id)
    elif _validate_google_model(model_id):
        return GoogleAIClient(model_id)
    # OpenRouter models
    return OpenRouterClient(model_id)

# GoogleAIClient and OpenRouterClient implementations follow...