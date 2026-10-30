"""Meeting sessions and the rotating check-in code.

An officer starts a meeting and shows the code on the room's screen. The code
changes every CODE_STEP_SECONDS, so it only works for people who can see the
screen right now (a code texted to a friend at home expires in seconds).

Nothing is written to disk. The current meeting is kept in memory and mirrored
to the "Meeting Log" tab in the Google Sheet (who started it, who ended it),
so a server restart picks the open meeting back up from the sheet. The code
secret is never stored: it is derived from JWT_SECRET and the meeting's ID.
"""
import hashlib
import hmac
import threading
import time

from . import config, sheets

_lock = threading.RLock()
_state: dict | None = None  # None = not loaded from the sheet yet


def _secret(meeting_id: str) -> str:
    return hmac.new(config.JWT_SECRET.encode(), f"meeting:{meeting_id}".encode(),
                    hashlib.sha256).hexdigest()


def state() -> dict:
    global _state
    with _lock:
        if _state is None:
            _state = sheets.load_open_meeting() or {"active": False}
        if _state.get("active") and time.time() - _state["started"] > config.MEETING_MAX_HOURS * 3600:
            sheets.log_meeting_end(_state["id"], "(auto: timed out)")
            _state = {"active": False}
        return _state


def start(by: str) -> dict:
    global _state
    with _lock:
        if state().get("active"):
            return _state
        mid = str(int(time.time() * 1000))
        sheets.log_meeting_start(mid, by)
        _state = {"active": True, "id": mid, "started": int(mid) / 1000, "by": by}
        return _state


def end(by: str) -> None:
    global _state
    with _lock:
        s = state()
        if s.get("active"):
            sheets.log_meeting_end(s["id"], by)
        _state = {"active": False}


def _code(secret: str, window: int) -> str:
    digest = hmac.new(secret.encode(), str(window).encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 1_000_000:06d}"


def current() -> tuple[str, int]:
    """Return (code, seconds until it changes). Only call while a meeting is active."""
    s = state()
    step = config.CODE_STEP_SECONDS
    now = time.time()
    return _code(_secret(s["id"]), int(now // step)), int(step - (now % step))


def verify(submitted: str) -> bool:
    s = state()
    if not s.get("active"):
        return False
    secret = _secret(s["id"])
    window = int(time.time() // config.CODE_STEP_SECONDS)
    # Accept the current and previous window so a code isn't rejected mid-typing.
    return any(
        hmac.compare_digest(_code(secret, window - o), submitted.strip())
        for o in (0, 1)
    )
