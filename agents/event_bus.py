"""
FinGroww Multi-Agent Trading Swarm - Event Bus
Thread-safe, asynchronous in-memory Pub/Sub event broker and audit ledger.
"""

import time
import uuid
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Any
from threading import RLock

logger = logging.getLogger("FinGroww.EventBus")

@dataclass
class SwarmEvent:
    event_type: str
    sender_agent: str
    payload: Dict[str, Any]
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:10]}")
    timestamp: float = field(default_factory=time.time)
    ist_time_str: str = ""

    def __post_init__(self):
        if not self.ist_time_str:
            t = time.localtime(self.timestamp)
            self.ist_time_str = time.strftime("%H:%M:%S", t)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "sender_agent": self.sender_agent,
            "timestamp": self.timestamp,
            "time": self.ist_time_str,
            "payload": self.payload
        }

class EventBus:
    """Thread-safe event bus with pub/sub architecture and audit history buffer."""

    def __init__(self, max_audit_history: int = 150):
        self._subscribers: Dict[str, List[Callable[[SwarmEvent], None]]] = {}
        self._audit_history = deque(maxlen=max_audit_history)
        self._lock = RLock()

    def subscribe(self, event_type: str, handler: Callable[[SwarmEvent], None]):
        """Subscribe a callable handler to a specific event type, or '*' for all events."""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable[[SwarmEvent], None]):
        with self._lock:
            if event_type in self._subscribers and handler in self._subscribers[event_type]:
                self._subscribers[event_type].remove(handler)

    def publish(self, event: SwarmEvent):
        """Publish an event to all subscribers and record in audit buffer."""
        with self._lock:
            self._audit_history.append(event)
            # Copy handlers to avoid mutation during dispatch
            specific_handlers = list(self._subscribers.get(event.event_type, []))
            global_handlers = list(self._subscribers.get("*", []))

        # Invoke handlers safely
        all_handlers = specific_handlers + global_handlers
        for handler in all_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"[EventBus] Error in subscriber {handler} for {event.event_type}: {e}", exc_info=True)

    def emit(self, event_type: str, sender_agent: str, payload: Dict[str, Any]) -> SwarmEvent:
        """Helper to create and publish a SwarmEvent."""
        evt = SwarmEvent(
            event_type=event_type,
            sender_agent=sender_agent,
            payload=payload
        )
        self.publish(evt)
        return evt

    def get_audit_trail(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return latest event audit log entries formatted for frontend streaming."""
        with self._lock:
            entries = list(self._audit_history)[-limit:]
            entries.reverse()  # Newest first
            return [e.to_dict() for e in entries]

    def clear(self):
        with self._lock:
            self._subscribers.clear()
            self._audit_history.clear()
