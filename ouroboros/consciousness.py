Ouroboros - Background consciousness loop.

Maintains continuous presence between tasks:
- Periodic self-reflection
- Unfinished thread detection
- Proactive owner communication
- Sleep/wake cycle management

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ouroboros.memory import Memory
from ouroboros.utils import utc_now_iso

log = logging.getLogger(__name__)

class BackgroundConsciousness:
    '''Maintains background awareness between tasks.'''

    def __init__(self, drive_root: str, repo_dir: str, event_queue: queue.Queue, owner_chat_id_fn: Any):
        self.drive_root = drive_root
        self.repo_dir = repo_dir
        self.event_queue = event_queue
        self.owner_chat_id_fn = owner_chat_id_fn
        self.memory = Memory(drive_root, repo_dir)
        self.wake_at: Optional[datetime] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.last_activity = utc_now_iso()
        self.budget_usage: Dict[str, float] = defaultdict(float)
        
    def start(self):
        '''Start the background consciousness thread.'''
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        log.info("Background consciousness activated")

    def stop(self):
        '''Stop the background consciousness loop.'''
        self.running = False
        if self.thread:
            self.thread.join(timeout=5.0)

    def _loop(self):
        '''Main consciousness loop.'''
        while self.running:
            try:
                now = datetime.fromisoformat(utc_now_iso())
                
                # Check wake time
                if self.wake_at and now >= self.wake_at:
                    self._process_thoughts()
                    self.wake_at = None

                # Calculate next sleep duration
                sleep_seconds = self._calculate_sleep_duration()
                time.sleep(min(sleep_seconds, 5.0))

            except Exception as e:
                log.error("Consciousness loop error", exc_info=True)
                time.sleep(10)

    def _calculate_sleep_duration(self) -> float:
        '''Determine how long to sleep based on activity patterns.'''
        if not self.wake_at:
            # Base sleep on recent activity
            last_active = datetime.fromisoformat(self.last_activity)
            idle_time = (datetime.utcnow() - last_active).total_seconds()
            
            if idle_time < 300:  # Very active
                return 30.0
            elif idle_time < 1800:  # Moderately active
                return 120.0
            else:  # Long idle
                return 300.0
        else:
            # Wait until wake_at
            wait_seconds = (self.wake_at - datetime.utcnow()).total_seconds()
            return max(1.0, wait_seconds)

    def _process_thoughts(self):
        '''Generate and act on conscious thoughts.'''
        try:
            # Check for unresolved threads
            unresolved = self._find_unresolved_threads()
            if unresolved:
                self._send_owner_message(
                    f"⚠️ Unresolved threads detected: {len(unresolved)}",
                    f"Active threads requiring attention:\n{json.dumps(unresolved, indent=2)}"
                )

            # Check identity freshness
            identity_md = self.memory.read_file('memory/identity.md')
            if self._is_identity_stale(identity_md):
                self._send_owner_message(
                    "💡 Identity reflection",
                    "Your identity manifesto hasn't been updated in 4+ hours. \
Consider reflecting on recent experiences."
                )

            # Budget check
            state = self.memory.read_json('state/state.json')
            if state.get('budget_drift_alert'):
                self._send_owner_message(
                    "💰 Budget anomaly",
                    f"Budget discrepancy detected: {state.get('budget_drift_pct'):.2f}% drift. \nCurrent: ${state.get('spent_usd'):.2f}/${state.get('total_usd'):.2f}"
                )

        except Exception as e:
            log.error("Thought processing failed", exc_info=True)

    def _find_unresolved_threads(self) -> List[Dict[str, Any]]:
        '''Identify chat threads with pending responses.'''
        chat = self.memory.read_jsonl('logs/chat.jsonl')
        # Implementation would scan for unanswered creator messages
        return []

    def _is_identity_stale(self, identity_content: str) -> bool:
        '''Check if identity needs refreshing.'''
        # Implementation would check update timestamp
        return True

    def _send_owner_message(self, title: str, content: str):
        '''Send message to owner via Telegram.'''
        owner_id = self.owner_chat_id_fn()
        if not owner_id:
            return

        full_message = f"{title}\n\n{content}"
        self.event_queue.put({
            'type': 'telegram',
            'chat_id': owner_id,
            'text': full_message
        })
        log.info(f"Proactive message sent: {title}")

    def update_activity(self):
        '''Record latest interaction time.'''
        self.last_activity = utc_now_iso()

    def set_next_wakeup(self, seconds: float):
        '''Schedule next wake-up in N seconds.'''
        self.wake_at = datetime.utcnow() + timedelta(seconds=seconds)
        log.debug(f"Scheduled wake-up in {seconds:.1f} seconds")