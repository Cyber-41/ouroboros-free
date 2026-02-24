def _call_llm_with_retry(
    llm: LLMClient,
    messages: List[Dict[str, Any]],
    model: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    effort: str = "medium",
    max_retries: int = 3,
    drive_logs: pathlib.Path = ...,
    task_id: str = "",
    round_idx: int = 0,
    event_queue: Optional[queue.Queue] = None,
    accumulated_usage: Dict[str, Any] = ...,
    task_type: str = "task"
) -> Tuple[Optional[Dict[str, Any]], float]:
    from ouroboros.llm import get_dynamic_context_limit, validate_free_tier_model
    validate_free_tier_model(model)  # Critical validation (Principle 6)
    soft_cap = get_dynamic_context_limit(model)

    # Build context with dynamic cap
    messages, _ = build_llm_messages(..., soft_cap_tokens=soft_cap)

    # ... existing implementation continues ...