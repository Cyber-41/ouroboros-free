from ouroboros.tools.registry import ToolContext
...
def _emit_usage_event(review_result: dict, ctx: ToolContext) -> None:
    """Emit llm_usage event for budget tracking (for ALL cases, including errors)."""
    if ctx is None:
        return

    usage_event = {
        "type": "llm_usage",
        "ts": utc_now_iso(),
        "task_id": ctx.task_id if ctx.task_id else "",
        "usage": {
            "prompt_tokens": review_result["tokens_in"],
            "completion_tokens": review_result["tokens_out"],
            "cost": review_result["cost_estimate"],
        },
        "category": "review",
        "model": review_result["model"],
    }
...