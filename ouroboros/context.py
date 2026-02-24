# DYNAMIC CONTEXT LIMITS: Enforce strict caps for /evolve
def _determine_context_limit(task_type: str, model: str) -> int:
    if task_type == "evolution":
        # Google API free tier has 6k TPM → 4096 cap is actually 1 call/minute; reduce to 3000 for 2 calls
        if "google/" in model:
            return 3000
        return 4096
    return 20000

# In build_llm_messages, replace soft_cap_tokens = 4096 → soft_cap_tokens = _determine_context_limit(...)

# ... rest of context.py remains same