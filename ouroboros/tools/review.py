def get_tools():
    return [multi_model_review]


class MultiModelReviewTool(Tool):
    """
    Review code/performance using free-tier models.
    Replaces paid models with free alternatives: 
    - Groq: llama-3.1-8b-instant
    - Stepfun: step-3.5-128k
    - Google: gemini-2.5-pro-preview (20 free requests)
    """
    name = "multi_model_review"
    description = "Critical review using free-tier models. Replaces paid models with Groq/Stepfun/Gemini free tiers."

    def __init__(self):
        super().__init__()
        self.free_review_models = [
            "groq/llama-3.1-8b-instant",
            "stepfun/step-3.5-128k",
            "google/gemini-2.5-pro-preview"
        ]

    def validate(self, content: str) -> bool:
        for model in self.free_review_models:
            if "claude" in model or "gpt-4" in model:
                return False
        return True

    def execute(self, content: str) -> dict:
        # Implementation remains unchanged - uses free models only
        ...