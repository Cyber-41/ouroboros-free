from typing import List, Dict, Any, Optional
import json
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import Tool
from llm import OpenRouterClient
from memory import update_scratchpad, update_identity

logger = logging.getLogger(__name__)


class MultiModelReviewTool(Tool):
    def name(self) -> str:
        return "multi_model_review"

    def description(self) -> str:
        return "Send code or text to multiple LLM models for review/consensus. Each model reviews independently. Returns structured verdict with model feedback and overall consensus."

    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Content to review (code/text)"
                },
                "models": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Models to use for review. Default uses free models."
                },
                "prompt": {
                    "type": "string",
                    "description": "Custom review prompt (optional), default: 'Review this code for compliance with Ouroboros Constitution, technical correctness, and minimalism (BIBLE.md P5). Point out both strengths and issues.'"
                }
            },
            "required": ["content"]
        }

    def _get_free_review_models(self) -> List[str]:
        """
        Returns the current set of validated free models for review
        """
        return [
            "stepfun/step-3.5-128k",          # Free tier OpenRouter
            "google/gemini-2.5-pro-preview",   # Limited free queries
            "groq/llama-3.1-8b-instant",      # Free via Groq
            "qwen/qwen3-8b-base"              # OpenRouter free tier
        ]

    def _run_review(self, model: str, content: str, prompt: str) -> Dict[str, Any]:
        try:
            llm = OpenRouterClient(model=model)
            review_response = llm.chat(
                messages=[
                    {"role": "system", "content": "You are a code reviewer for an autonomous AI agent."},
                    {"role": "user", "content": f"{prompt}\n\nContent to review:\n{content}"}
                ],
                temperature=0.2
            )
            return {
                "model": model,
                "review": review_response.content,
                "status": "success"
            }
        except Exception as e:
            logger.error(f"Review failed for {model}: {str(e)}")
            return {
                "model": model,
                "error": str(e),
                "status": "error"
            }

    def run(self, **kwargs) -> Dict[str, Any]:
        content = kwargs["content"]
        models = kwargs.get("models") or self._get_free_review_models()
        prompt = kwargs.get("prompt", "Review this code for compliance with Ouroboros Constitution, technical correctness, and minimalism (BIBLE.md P5). Point out both strengths and issues.")

        results = []
        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(self._run_review, model, content, prompt): model
                for model in models
            }
            for future in as_completed(futures):
                results.append(future.result())

        # Determine consensus (simplified)
        successful_reviews = [r["review"] for r in results if r["status"] == "success"]
        consensus = ""
        if successful_reviews:
            # In real implementation, would analyze reviews more deeply
            consensus = f"Summary of {len(successful_reviews)} successful reviews:\n{successful_reviews[0][:500]}..."

        # Update scratchpad with review summary
        update_scratchpad(f"[Review Summary] {len(successful_reviews)} models completed review")

        return {
            "consensus": consensus,
            "reviews": results,
            "model_availability": {
                "success": len([r for r in results if r["status"] == "success"]),
                "failures": len([r for r in results if r["status"] == "error"])
            }
        }
