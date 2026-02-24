Ouroboros — LLM tool loop.

Core loop: send messages to LLM, execute tool calls, repeat until final response.
Extracted from agent.py to keep the agent thin.

from __future__ import annotations

import copy
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from openai import APIStatusError
from ouroboros.context import build_llm_messages
from ouroboros.llm import LLMClient
from ouroboros.memory import Memory
from ouroboros.utils import (
    add_llm_usage_to_state,
    create_tool_response,
    get_git_info,
    get_tool_calls,
    utc_now_iso,
)

log = logging.getLogger(__name__)


class ToolLoop:
    '''LLM tool execution loop (with retry policy).'''

    def __init__(self, memory: Memory):
        self.memory = memory
        self.llm = LLMClient()
        self.round_counter = 0

    def run(
        self,
        env: Any,
        task: Dict[str, Any],
        max_rounds: int = 20,
        max_errors: int = 3,
    ) -> Dict[str, Any]:
        '''
        Run the LLM tool loop for a task.

        Returns final assistant message or error report.
        '''
        self.round_counter = 0
        errors = 0
        messages: List[Dict[str, Any]] = []
        cap_info: Dict[str, Any] = {}

        while self.round_counter < max_rounds:
            # Increment round counter
            self.round_counter += 1

            # Build context — now with model awareness
            model_id = os.environ.get('OUROBOROS_MODEL', 'anthropic/claude-sonnet-4.6')
            messages, cap_info = build_llm_messages(
                env,
                self.memory,
                task,
                review_context_builder=None,
                model_id=model_id  # Critical fix: pass model for dynamic context
            )

            # Call LLM
            try:
                response_msg, usage = self.llm.chat(
                    messages=messages,
                    model=model_id,
                    tools=env.get_tools(),
                    reasoning_effort=task.get('reasoning_effort', 'medium'),
                    max_tokens=16384,
                )
                self._log_round(task, 'success', usage, cap_info)

                # Accumulate usage
                add_llm_usage_to_state(task, usage)

                # Check for final response
                if not get_tool_calls(response_msg):
                    return {
                        'role': 'assistant',
                        'content': response_msg.get('content', ''),
                        'usage': usage,
                        'cap_info': cap_info,
                    }

                # Handle tool calls
                tool_calls = get_tool_calls(response_msg)
                for call in tool_calls:
                    try:
                        tool_response = env.execute_tool(call)
                        messages.append(
                            create_tool_response(call['id'], tool_response)
                        )
                    except Exception as e:
                        log.error(f'Tool {call["name"]} failed: {e}', exc_info=True)
                        error_msg = f'Error: {str(e)[:500]}'
                        messages.append(
                            create_tool_response(call['id'], error_msg)
                        )
                        errors += 1
                        if errors >= max_errors:
                            raise

            except APIStatusError as e:
                self._log_round(task, 'error', {'error': str(e)}, cap_info)
                log.error(f'LLM API error: {e}', exc_info=True)
                errors += 1
                if errors >= max_errors:
                    raise

                # Backoff on rate limit errors
                if e.status_code in (429, 413):
                    time.sleep(2 ** errors)

        # Max rounds exceeded
        raise RuntimeError(f'Tool loop exceeded max rounds ({max_rounds})')

    def _log_round(
        self,
        task: Dict[str, Any],
        status: str,
        usage: Dict[str, Any],
        cap_info: Dict[str, Any],
    ):
        '''Log round completion to memory.'''
        entry = {
            'timestamp': utc_now_iso(),
            'task_id': task.get('id'),
            'task_type': task.get('type'),
            'round': self.round_counter,
            'status': status,
            'usage': usage,
            'context_trimming': cap_info,
            'git_branch': get_git_info(self.memory.repo_dir)[0],
            'git_sha': get_git_info(self.memory.repo_dir)[1],
        }
        self.memory.append_jsonl('events.jsonl', entry)