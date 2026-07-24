"""Notification routing.

``router.py`` is the single choke point: dedupe, throttle, quiet-hours awareness,
channel fan-out by priority, and delivery logging. Channels: ntfy (P1/P2 default),
Pushover (P0 critical), iMessage (optional Mac-native). ``cli.py`` is a standalone
path that works even when the daemon is down (used by the watchdog).
"""

from .router import Notification, Priority, get_router

__all__ = ["Notification", "Priority", "get_router"]
