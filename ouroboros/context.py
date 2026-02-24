def build_llm_messages(
    env: Any,
    memory: Memory,
    task: Dict[str, Any],
    review_context_builder: Optional[Any] = None,
    soft_cap_tokens: int = 200000  # New parameter: dynamic context limit
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    # ... existing function body ...

    # System message with 3 content blocks for optimal caching
    # ... existing code ...

    # --- Soft-cap token trimming ---
    messages, cap_info = apply_message_token_soft_cap(messages, soft_cap_tokens)

    return messages, cap_info

def apply_message_token_soft_cap(...):
    # ... existing implementation ...