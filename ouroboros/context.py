def apply_message_token_soft_cap(messages: List[Dict[str, Any]], soft_cap_tokens: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    # Implementation unchanged
    ...

def build_llm_messages(env: Any, memory: Memory, task: Dict[str, Any], review_context_builder: Optional[Any] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    ...
    # --- Soft-cap token trimming ---
    task_type = str(task.get('type') or 'user')
    actual_cap = 4096 if task_type == 'evolution' else 200000
    messages, cap_info = apply_message_token_soft_cap(messages, actual_cap)
    return messages, cap_info