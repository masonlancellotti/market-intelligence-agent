"""Concrete notification channels: ntfy, Pushover, iMessage.

Each channel is best-effort and self-reporting: ``send`` returns (ok, detail). A
channel that isn't configured returns ``(False, "disabled")`` rather than raising,
so the router can fan out to whatever is available and log the rest.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Protocol

import httpx
from loguru import logger

from ..config import Secrets

_HTTP_TIMEOUT = 12.0


class Channel(Protocol):
    name: str

    def configured(self, secrets: Secrets) -> bool: ...

    def send(
        self, secrets: Secrets, *, title: str, body: str, priority: str, click_url: str, tags: str
    ) -> tuple[bool, str]: ...


class NtfyChannel:
    name = "ntfy"

    def configured(self, secrets: Secrets) -> bool:
        return bool(secrets.ntfy_base_url)

    def send(self, secrets, *, title, body, priority, click_url, tags):  # noqa: ANN001
        topic = secrets.ntfy_topic_alerts if priority == "P0" else secrets.ntfy_topic_briefs
        url = f"{secrets.ntfy_base_url.rstrip('/')}/{topic}"
        # ntfy priority: 5=max,4=high,3=default,2=low,1=min
        prio = {"P0": "5", "P1": "4", "P2": "2"}.get(priority, "3")
        headers = {
            "Title": title.encode("ascii", "ignore").decode() or "Meridian",
            "Priority": prio,
            "Markdown": "yes",
        }
        if tags:
            headers["Tags"] = tags
        if click_url:
            headers["Click"] = click_url
        if secrets.ntfy_token:
            headers["Authorization"] = f"Bearer {secrets.ntfy_token}"
        try:
            r = httpx.post(url, data=body.encode("utf-8"), headers=headers, timeout=_HTTP_TIMEOUT)
            if r.status_code < 300:
                return True, f"ntfy {r.status_code}"
            return False, f"ntfy HTTP {r.status_code}: {r.text[:120]}"
        except Exception as e:  # noqa: BLE001
            return False, f"ntfy error: {e}"


class PushoverChannel:
    name = "pushover"

    def configured(self, secrets: Secrets) -> bool:
        return bool(secrets.pushover_token and secrets.pushover_user)

    def send(self, secrets, *, title, body, priority, click_url, tags):  # noqa: ANN001
        if not self.configured(secrets):
            return False, "disabled"
        data = {
            "token": secrets.pushover_token,
            "user": secrets.pushover_user,
            "title": title[:250],
            "message": body[:1024],
        }
        if priority == "P0":
            # emergency priority requires retry/expire; critical-alert sound bypasses focus
            data.update({"priority": "2", "retry": "60", "expire": "3600", "sound": "alien"})
        elif priority == "P1":
            data["priority"] = "0"
        else:
            data["priority"] = "-1"
        if click_url:
            data["url"] = click_url
            data["url_title"] = "Open Meridian"
        try:
            r = httpx.post(
                "https://api.pushover.net/1/messages.json", data=data, timeout=_HTTP_TIMEOUT
            )
            if r.status_code < 300:
                return True, "pushover ok"
            return False, f"pushover HTTP {r.status_code}: {r.text[:120]}"
        except Exception as e:  # noqa: BLE001
            return False, f"pushover error: {e}"


class IMessageChannel:
    """Mac-native iMessage via osascript. No-op on non-Mac (degrades cleanly)."""

    name = "imessage"

    def configured(self, secrets: Secrets) -> bool:
        return bool(secrets.imessage_to) and shutil.which("osascript") is not None

    def send(self, secrets, *, title, body, priority, click_url, tags):  # noqa: ANN001
        if not self.configured(secrets):
            return False, "disabled"
        text = f"{title}\n{body}"
        if click_url:
            text += f"\n{click_url}"
        script = (
            'tell application "Messages"\n'
            "  set targetService to 1st service whose service type = iMessage\n"
            f'  set targetBuddy to buddy "{secrets.imessage_to}" of targetService\n'
            f"  send {_applescript_str(text)} to targetBuddy\n"
            "end tell"
        )
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=15)
            return True, "imessage ok"
        except Exception as e:  # noqa: BLE001
            return False, f"imessage error: {e}"


def _applescript_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", '" & return & "') + '"'


ALL_CHANNELS: dict[str, Channel] = {
    "ntfy": NtfyChannel(),
    "pushover": PushoverChannel(),
    "imessage": IMessageChannel(),
}


def channels_for(priority: str, secrets: Secrets) -> list[Channel]:
    """Channel fan-out policy by priority."""
    if priority == "P0":
        order = ["pushover", "ntfy", "imessage"]
    else:  # P1/P2 -> ntfy only
        order = ["ntfy"]
    chosen = [ALL_CHANNELS[n] for n in order if ALL_CHANNELS[n].configured(secrets)]
    if not chosen:
        logger.warning("no notification channel configured for {} — will log dry_run", priority)
    return chosen
