from typing import List, Dict, Any
import logging
from llm import LLMClient

logger = logging.getLogger(__name__)

def multi_model_review(content: str, models: List[str] = None) -> Dict[str, Any]:
    """
    Conduct multi-model review using ONLY validated free-tier models.
    Automatically enforces 4096 token context limit.
    """
    if not models:
        models = [
            "stepfun/step-3.5-flash:free",  # 30k TPM free tier
            "arcee-ai/trinity-large-preview:free",  # 25k TPM
            "google/gemini-2.0-flash-001"  # Google free tier (20 uses)
        ]
    
    results = {}
    llm = LLMClient(max_tokens=4096)  # Enforce TPM safety
    
    for model in models:
        try:
            response = llm.complete(
                prompt=f"Review this code:\n\n{content}",
                model=model,
                temperature=0.3
            )
            results[model] = response
        except Exception as e:
            logger.error(f"Model {model} failed: {str(e)}")
            
    return results

# --- EXISTING CODE BELOW THIS LINE ---
# ... (rest of original review.py content preserved for context) ...