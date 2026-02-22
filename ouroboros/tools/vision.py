def _emit_usage(ctx: ToolContext, usage: Dict[str, Any], model: str) -> None:
    """Emit LLM usage event for budget tracking."""
    if ctx.event_queue is None:
        return
    try:
        event = {
            "type": "llm_usage",
            "model": model or "unspecified",  # Ensure non-empty model for breakdown
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "cached_tokens": usage.get("cached_tokens", 0),
            "cost": usage.get("cost", 0.0),
            "task_id": ctx.task_id,
            "task_type": ctx.current_task_type or "task",
        }
        ctx.event_queue.put_nowait(event)
    except Exception:
        log.debug("Failed to emit VLM usage event", exc_info=True)