"""All Google Sheets access: logins, weekly tasks, attendance log, meeting log."""
import datetime as dt
import json
import logging
import re
import threading
import time
from zoneinfo import ZoneInfo

import gspread

from . import config

TZ = ZoneInfo(config.TIMEZONE)
LOG_HEADER = ["Date", "Name", "Check In", "Check Out", "Hours", "Note"]
N = len(LOG_HEADER)
MEETING_HEADER = ["Date", "Started By", "Started At", "Ended By", "Ended At", "Meeting ID"]
WEEK_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2})\s*$")

_lock = threading.RLock()
_book = None
_logins_book = None
_cache: dict[str, tuple[float, object]] = {}
_tabs: dict[str, object] = {}


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def _client():
    if config.SERVICE_ACCOUNT_JSON:
        return gspread.service_account_from_dict(json.loads(config.SERVICE_ACCOUNT_JSON))
    return gspread.service_account(filename=config.SERVICE_ACCOUNT_FILE)


def book():
    global _book
    if _book is None:
        _book = _client().open_by_key(config.SHEET_ID)
    return _book


def logins_book():
    """Spreadsheet holding the names + PINs (same file by default, or LOGINS_SHEET_ID)."""
    global _logins_book
    if not config.LOGINS_SHEET_ID:
        return book()
    if _logins_book is None:
        _logins_book = _client().open_by_key(config.LOGINS_SHEET_ID)
    return _logins_book


def _cached(key: str, ttl: int, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def _tab(title: str, header: list[str]):
    """Get a tab (creating it with a header row if missing). Handles are reused to save API calls."""
    ws = _tabs.get(title)
    if ws is None:
        try:
            ws = book().worksheet(title)
        except gspread.WorksheetNotFound:
            ws = book().add_worksheet(title, rows=1000, cols=len(header))
            ws.append_row(header, value_input_option="RAW")
        _tabs[title] = ws
    return ws


# ---------------------------------------------------------------- logins

def members() -> list[dict]:
    """Rows of the Logins tab: needs a 'Name' column and a 'PIN' column."""
    def load():
        rows = logins_book().worksheet(config.LOGINS_TAB).get_all_values()
        if not rows:
            return []
        header = [h.strip().lower() for h in rows[0]]
        ni = next((i for i, h in enumerate(header) if "name" in h), None)
        pi = next((i for i, h in enumerate(header) if h == "pin" or "pin" in h.split()), None)
        if ni is None:
            raise RuntimeError(f"'{config.LOGINS_TAB}' needs a header row with a Name column.")
        out = []
        for r in rows[1:]:
            r = r + [""] * (len(header) - len(r))
            name = r[ni].strip()
            if name:
                pin = r[pi].strip() if pi is not None else ""
                if pin.isdigit() and len(pin) < 4:
                    pin = pin.zfill(4)  # Sheets drops leading zeros (0568 -> 568)
                advisor = any("advis" in c.lower() for i, c in enumerate(r) if i not in (ni, pi))
                out.append({"name": name, "pin": pin, "advisor": advisor})
        return out

    return _cached("members", 60, load)


def find_member(name: str) -> dict | None:
    name = name.strip().lower()
    return next((m for m in members() if m["name"].lower() == name), None)


def member_names() -> list[str]:
    return sorted({m["name"] for m in members()}, key=str.lower)


# ----------------------------------------------------------------- roster
# Teams and Lead status come from the Member Information tab. Columns are found by
# content, not position: any cell that says Mechanical / Electrical / Telemetry /
# Social Media is a team, and any cell that says Lead marks a lead.

TEAMS = {"mechanical", "electrical", "telemetry", "social media"}
_log_ = logging.getLogger(__name__)


def roster() -> dict[str, dict]:
    def load():
        try:
            rows = book().worksheet(config.MEMBERS_TAB).get_all_values()
        except Exception as e:  # tasks and check-in must keep working without it
            _log_.error("Can't read '%s' (teams/leads won't work): %s", config.MEMBERS_TAB, e)
            return {}
        if not rows:
            return {}
        header = [h.strip().lower() for h in rows[0]]
        ni = next((i for i, h in enumerate(header) if "name" in h), None)
        out = {}
        for r in rows[1:]:
            cells = [c.strip() for c in r]
            name = cells[ni] if ni is not None and ni < len(cells) else next((c for c in cells if c), "")
            if not name:
                continue
            parts = {p.strip().lower() for c in cells for p in re.split(r"[,;/]", c)}
            out[name.lower()] = {"teams": parts & TEAMS, "lead": bool(parts & {"lead", "leads"})}
        return out

    return _cached("roster", 60, load)


def profile(name: str) -> dict:
    return roster().get(name.strip().lower(), {"teams": set(), "lead": False})


def is_lead(name: str) -> bool:
    return profile(name)["lead"]


# ------------------------------------------------------------------ tasks

def _week_tab(today: dt.date):
    for ws in book().worksheets():
        m = WEEK_RE.match(ws.title)
        if not m:
            continue
        m1, d1, m2, d2 = map(int, m.groups())
        try:
            sy = ey = today.year
            if (m2, d2) < (m1, d1):  # week wraps over New Year
                if today.month >= m1:
                    ey += 1
                else:
                    sy -= 1
            start, end = dt.date(sy, m1, d1), dt.date(ey, m2, d2)
        except ValueError:
            continue
        if start <= today <= end:
            return ws
    return None


def _week_rows() -> dict:
    def load():
        ws = _week_tab(now().date())
        if ws is None:
            return {"week": None, "rows": []}
        values = ws.get_all_values()
        hi = next(
            (i for i, r in enumerate(values)
             if {"task", "people"} <= {c.strip().lower() for c in r}),
            None,
        )
        if hi is None:
            return {"week": ws.title, "rows": []}
        cols = {c.strip().lower(): i for i, c in enumerate(values[hi])}

        def get(r, name):
            i = cols.get(name)
            return r[i].strip() if i is not None and i < len(r) else ""

        rows = []
        for r in values[hi + 1:]:
            if get(r, "task"):
                rows.append({
                    "task": get(r, "task"),
                    "people": [p.strip() for p in re.split(r"[,;]", get(r, "people")) if p.strip()],
                    "due": get(r, "due date"),
                    "status": get(r, "status"),
                    "tools": get(r, "tools needed"),
                    "notes": get(r, "notes"),
                })
        return {"week": ws.title, "rows": rows}

    return _cached("week", 60, load)


EVERYONE = {"whole team", "whole", "all", "everyone", "all team", "entire team", "team", "all members"}
LEADS = {"leads", "lead", "lead team", "leaders"}


def _match(people: list[str], names: set[str], prof: dict) -> str | None:
    """None = not for this person. '' = named directly. Otherwise the group label (e.g. 'Whole team')."""
    group = None
    for p in people:
        k = p.strip().lower()
        if k in names:
            return ""
        base = k[:-5].strip() if k.endswith(" team") else k
        if k in EVERYONE or k in LEADS and prof["lead"] or base in prof["teams"]:
            group = group or p.strip()
    return group


def tasks_for(full_name: str) -> dict:
    data = _week_rows()
    names = {full_name.lower(), full_name.split()[0].lower()}
    prof = profile(full_name)
    mine = []
    for t in data["rows"]:
        g = _match(t["people"], names, prof)
        if g is not None:
            mine.append({**t, "group": g})
    return {"week": data["week"], "tasks": mine}


# ------------------------------------------------------------ meeting log
# Columns: 0 Date, 1 Started By, 2 Started At, 3 Ended By, 4 Ended At, 5 Meeting ID

def log_meeting_start(meeting_id: str, by: str) -> None:
    with _lock:
        t = now()
        _tab(config.MEETING_LOG_TAB, MEETING_HEADER).append_row(
            [t.strftime("%Y-%m-%d"), by, t.strftime("%H:%M:%S"), "", "", meeting_id],
            value_input_option="RAW",
        )


def log_meeting_end(meeting_id: str, by: str) -> None:
    with _lock:
        ws = _tab(config.MEETING_LOG_TAB, MEETING_HEADER)
        rows = ws.get_all_values()
        for i in range(len(rows) - 1, 0, -1):
            r = rows[i] + [""] * (len(MEETING_HEADER) - len(rows[i]))
            if r[5] == meeting_id:
                ws.update(f"D{i + 1}:E{i + 1}", [[by, now().strftime("%H:%M:%S")]],
                          value_input_option="RAW")
                return


def load_open_meeting() -> dict | None:
    """After a restart: the newest Meeting Log row with no 'Ended At' is the open meeting."""
    with _lock:
        rows = _tab(config.MEETING_LOG_TAB, MEETING_HEADER).get_all_values()
        for i in range(len(rows) - 1, 0, -1):
            r = rows[i] + [""] * (len(MEETING_HEADER) - len(rows[i]))
            if r[5].strip():
                if r[4].strip():
                    return None
                try:
                    return {"active": True, "id": r[5].strip(),
                            "started": int(r[5]) / 1000, "by": r[1]}
                except ValueError:
                    return None
        return None


# ------------------------------------------------------------- attendance
# Log columns: 0 Date, 1 Name, 2 Check In, 3 Check Out, 4 Hours, 5 Note
# The whole log is read once and kept in memory; check-ins/outs update the
# memory copy and the sheet together, so a burst of members never hammers the
# Sheets API. It is re-read from the sheet every 60 seconds to catch manual edits.

_rows_cache: list[list[str]] | None = None
_rows_loaded = 0.0


def _log():
    return _tab(config.LOG_TAB, LOG_HEADER)


def _rows() -> list[list[str]]:
    global _rows_cache, _rows_loaded
    if _rows_cache is None or time.time() - _rows_loaded > 60:
        _rows_cache = _log().get_all_values()
        _rows_loaded = time.time()
    return _rows_cache


def _open_row(rows: list[list[str]], name: str, today: str):
    for i in range(len(rows) - 1, 0, -1):
        r = rows[i] + [""] * (N - len(rows[i]))
        if r[1].lower() == name.lower() and r[0] == today and r[2] and not r[3]:
            return i + 1, r
    return None


def status(name: str) -> dict:
    with _lock:
        hit = _open_row(_rows(), name, now().strftime("%Y-%m-%d"))
        return {"checked_in": bool(hit), "since": hit[1][2] if hit else None}


def check_in(name: str) -> str:
    with _lock:
        rows = _rows()
        t = now()
        today, stamp = t.strftime("%Y-%m-%d"), t.strftime("%H:%M:%S")
        if _open_row(rows, name, today):
            raise ValueError("You're already checked in.")
        row = [today, name, stamp, "", "", ""]
        res = _log().append_row(row, value_input_option="RAW")
        m = re.search(r"!A(\d+)", str((res or {}).get("updates", {}).get("updatedRange", "")))
        idx = int(m.group(1)) - 1 if m else len(rows)
        while len(rows) <= idx:
            rows.append([])
        rows[idx] = row
        return stamp


def _hours(start: str, end: str) -> float:
    f = "%H:%M:%S"
    d = dt.datetime.strptime(end, f) - dt.datetime.strptime(start, f)
    hours = max(d.total_seconds(), 0) / 3600
    return round(hours * 2) / 2  # nearest half hour (e.g. 1h20m -> 1.5, 1h10m -> 1.0)


def checked_in_now() -> list[dict]:
    """Everyone with an open row today (for leads who need to sign people out)."""
    with _lock:
        today = now().strftime("%Y-%m-%d")
        out = []
        for r in _rows()[1:]:
            r = r + [""] * (N - len(r))
            if r[0] == today and r[2] and not r[3]:
                out.append({"name": r[1], "since": r[2]})
        return out


def check_out(name: str, by: str | None = None) -> dict:
    """Close today's open row. `by` is set when a lead signs someone else out."""
    with _lock:
        rows = _rows()
        t = now()
        hit = _open_row(rows, name, t.strftime("%Y-%m-%d"))
        if not hit:
            raise ValueError("You're not checked in.")
        row, r = hit
        out = t.strftime("%H:%M:%S")
        hours = _hours(r[2], out)
        note = f"signed out by {by}" if by else ""
        _log().update(f"D{row}:F{row}", [[out, hours, note]], value_input_option="RAW")
        rows[row - 1] = r[:3] + [out, str(hours), note]
        return {"in": r[2], "out": out, "hours": hours}


DATE_HEAD = re.compile(r"^\d{1,2}/\d{1,2}(/\d{2,4})?$")


def _number(cell: str) -> float | None:
    try:
        return float(cell.strip())
    except ValueError:
        return None


def past_hours() -> dict[str, tuple[float, int]]:
    """Hours entered by hand before the app: lowercase member name -> (hours, days attended)."""
    def load():
        try:
            rows = book().worksheet(config.PAST_HOURS_TAB).get_all_values()
        except Exception as e:
            _log_.error("Can't read '%s' (past hours won't be counted): %s", config.PAST_HOURS_TAB, e)
            return {}
        hi = next((i for i, r in enumerate(rows) if any(DATE_HEAD.match(c.strip()) for c in r)), None)
        if hi is None:
            return {}
        header = [c.strip() for c in rows[hi]]
        dates = [i for i, c in enumerate(header) if DATE_HEAD.match(c)]
        ni = next((i for i, c in enumerate(header) if "name" in c.lower()), None)

        names = [m["name"] for m in members()]
        lookup = {n.lower(): n for n in names}
        firsts: dict[str, list[str]] = {}
        for n in names:
            firsts.setdefault(n.split()[0].lower(), []).append(n)
        for f, group in firsts.items():
            if len(group) == 1:
                lookup.setdefault(f, group[0])

        out: dict[str, tuple[float, int]] = {}
        for r in rows[hi + 1:]:
            r = r + [""] * (len(header) - len(r))
            raw = r[ni].strip() if ni is not None else next(
                (c.strip() for c in r if c.strip() and _number(c) is None), "")
            name = lookup.get(raw.lower())
            if not name:
                continue
            vals = [v for v in (_number(r[i]) for i in dates) if v]
            hours, days = out.get(name.lower(), (0.0, 0))
            out[name.lower()] = (hours + sum(vals), days + len(vals))
        return out

    return _cached("past_hours", 60, load)


def hours_summary() -> dict:
    """Hours and days attended per member (past sheet hours + the log), plus the advisors' names."""
    with _lock:
        totals: dict[str, float] = {}
        days: dict[str, set[str]] = {}
        for r in _rows()[1:]:
            r = r + [""] * (N - len(r))
            key = r[1].strip().lower()
            if not key or not r[3]:
                continue
            h = _number(r[4])
            if h is None:
                continue
            totals[key] = totals.get(key, 0.0) + h
            days.setdefault(key, set()).add(r[0])
    past = past_hours()
    seen, people, advisors = set(), [], []
    for m in members():
        key = m["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        if m["advisor"]:
            advisors.append(m["name"])
            continue
        ph, pd = past.get(key, (0.0, 0))
        people.append({"name": m["name"], "hours": round(totals.get(key, 0.0) + ph, 1),
                       "days": len(days.get(key, ())) + pd})
    people.sort(key=lambda p: (-p["hours"], p["name"].lower()))
    return {"people": people, "advisors": sorted(advisors, key=str.lower)}


def close_all_open() -> int:
    """Called when a meeting ends: check out everyone still signed in."""
    with _lock:
        rows = _rows()
        t = now()
        today, out = t.strftime("%Y-%m-%d"), t.strftime("%H:%M:%S")
        updates = []
        for i in range(1, len(rows)):
            r = rows[i] + [""] * (N - len(rows[i]))
            if r[0] == today and r[2] and not r[3]:
                hours = _hours(r[2], out)
                note = "auto checked out at meeting end"
                updates.append({"range": f"D{i + 1}:F{i + 1}", "values": [[out, hours, note]]})
                rows[i] = r[:3] + [out, str(hours), note]
        if updates:
            _log().batch_update(updates, value_input_option="RAW")
        return len(updates)
