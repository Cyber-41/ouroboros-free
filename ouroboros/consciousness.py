...
                # Report usage to supervisor
                if self._event_queue is not None:
                    self._event_queue.put({
                        "type": "llm_usage",
                        "provider": "openrouter",
                        "model": self.model,
                        "usage": usage,
                        "source": "consciousness",
                        "ts": utc_now_iso(),
                        "category": "consciousness",
                    })
...