import hmac
import time
from functools import wraps
from pathlib import Path

import jwt
from flask import Flask, g, jsonify, request, send_from_directory

from . import config, meeting, sheets

app = Flask(__name__, static_folder=None)


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


@app.errorhandler(ApiError)
def _api_error(e: ApiError):
    return jsonify(detail=e.detail), e.status


@app.errorhandler(Exception)
def _unexpected(e: Exception):
    if hasattr(e, "code") and isinstance(e.code, int):  # werkzeug HTTP errors
        return jsonify(detail=getattr(e, "description", str(e))), e.code
    app.logger.exception(e)
    return jsonify(detail="Server error. Check the server logs."), 500


def _client_ip() -> str:
    if config.TRUST_PROXY:
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.remote_addr or ""


def _throttle(key: str, store: dict, limit: int = 5, window: int = 60) -> list[float]:
    recent = [t for t in store.get(key, []) if time.time() - t < window]
    if len(recent) >= limit:
        raise ApiError(429, "Too many wrong attempts. Wait a minute and try again.")
    return recent


# ------------------------------------------------------------------ auth

_login_failures: dict[str, list[float]] = {}


def _is_admin(member: dict) -> bool:
    return bool(member.get("demo")) or member["name"].lower() in config.ADMIN_NAMES


def _is_lead_user() -> bool:
    """Leads (Lead tag in Member Information) and officers (ADMIN_NAMES) can sign others out."""
    u = g.user
    return bool(u.get("demo") or u["admin"] or sheets.is_lead(u["name"]))


def _issue(member: dict) -> str:
    payload = {
        "name": member["name"],
        "admin": _is_admin(member),
        "demo": bool(member.get("demo")),
        "exp": int(time.time()) + config.SESSION_HOURS * 3600,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


# Sandbox account: sample data, nothing is read from or written to the real sheet.
_demo = {"meeting": True, "since": None,
         "others": [{"name": "Sample Member", "since": "18:30:00"},
                    {"name": "Another Member", "since": "18:42:00"}]}
DEMO_TASKS = {
    "week": "Demo week",
    "tasks": [
        {"task": "Finish wiring diagram", "people": ["Demo"], "due": "10/31/2026",
         "status": "In Progress", "tools": "Laptop", "notes": ""},
        {"task": "Sponsorship email", "people": ["Demo"], "due": "10/31/2026",
         "status": "Completed", "tools": "", "notes": "Sent to 3 companies"},
        {"task": "CAD shell for the car", "people": ["Demo"], "due": "10/31/2026",
         "status": "Completed Partially", "tools": "Fusion 360", "notes": ""},
        {"task": "Complete homework from Mr. Eiland", "people": ["Whole team"], "due": "10/31/2026",
         "status": "In Progress", "tools": "", "notes": "", "group": "Whole team"},
    ],
}


def login_required(admin_only: bool = False, lead_only: bool = False):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.lower().startswith("bearer "):
                raise ApiError(401, "Not signed in")
            try:
                g.user = jwt.decode(header[7:], config.JWT_SECRET, algorithms=["HS256"])
            except jwt.PyJWTError:
                raise ApiError(401, "Session expired")
            if admin_only and not g.user["admin"]:
                raise ApiError(403, "Officers only")
            if lead_only and not _is_lead_user():
                raise ApiError(403, "Leads only")
            return fn(*args, **kwargs)
        return wrapper
    return deco


@app.get("/api/members")
def member_names():
    try:
        names = sheets.member_names()
    except Exception as e:  # sheet not connected yet: the login page should still load
        app.logger.error("Can't read the Logins tab: %s", e)
        names = []
    if config.DEMO_PIN and "demo" not in [n.lower() for n in names]:
        names.append("Demo")
    try:
        active = bool(meeting.state().get("active"))
    except Exception as e:
        app.logger.error("Can't read the Meeting Log tab: %s", e)
        active = False
    return jsonify(names=names, meeting=active)


@app.post("/api/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    name, pin = str(body.get("name", "")), str(body.get("pin", "")).strip()
    code = str(body.get("code", "")).strip()
    key = f"{_client_ip()}|{name.lower()}"
    recent = _throttle(key, _login_failures)

    is_demo_name = bool(config.DEMO_PIN) and name.strip().lower() == "demo"
    try:
        member = sheets.find_member(name)
    except Exception as e:
        app.logger.error("Can't read the Logins tab: %s", e)
        if not is_demo_name:
            raise ApiError(503, "Can't reach the Google Sheet. Check the server logs.")
        member = None
    if not member and is_demo_name:
        member = {"name": "Demo", "pin": config.DEMO_PIN, "demo": True}
    if member and not member["pin"]:
        raise ApiError(403, "You don't have a PIN yet. Ask an officer to add one.")
    if not member or not pin or not hmac.compare_digest(member["pin"], pin):
        _login_failures[key] = recent + [time.time()]
        raise ApiError(401, "Wrong name or PIN.")
    checked_in = False
    if code:
        if member.get("demo"):
            _demo["since"] = sheets.now().strftime("%H:%M:%S")
        else:
            _guard(member["name"], code)
            try:
                sheets.check_in(member["name"])
            except ValueError:
                pass
        checked_in = True
    return jsonify(token=_issue(member), name=member["name"], admin=_is_admin(member),
                   demo=bool(member.get("demo")), checked_in=checked_in)


@app.get("/api/me")
@login_required()
def me():
    return jsonify(name=g.user["name"], admin=g.user["admin"], demo=g.user.get("demo", False),
                   lead=_is_lead_user())


# ----------------------------------------------------------------- tasks

@app.get("/api/tasks")
@login_required()
def tasks():
    if g.user.get("demo"):
        return jsonify(DEMO_TASKS)
    return jsonify(sheets.tasks_for(g.user["name"]))


# ------------------------------------------------------------ attendance

_code_failures: dict[str, list[float]] = {}


def _guard(name: str, code: str) -> None:
    """Every check-in/out must pass: meeting open, right network, correct live code."""
    who = name.lower()
    if not meeting.state().get("active"):
        raise ApiError(409, "No meeting is in progress.")
    if config.ALLOWED_IPS and _client_ip() not in config.ALLOWED_IPS:
        raise ApiError(403, "Connect to the club Wi-Fi to do this.")
    recent = _throttle(who, _code_failures)
    if not meeting.verify(code):
        _code_failures[who] = recent + [time.time()]
        raise ApiError(400, "Wrong or expired code. Check the screen.")


@app.get("/api/attendance/status")
@login_required()
def attendance_status():
    if g.user.get("demo"):
        return jsonify(meeting_active=_demo["meeting"], checked_in=bool(_demo["since"]),
                       since=_demo["since"])
    return jsonify(
        meeting_active=bool(meeting.state().get("active")),
        **sheets.status(g.user["name"]),
    )


@app.post("/api/attendance/check-in")
@login_required()
def check_in():
    if g.user.get("demo"):  # any code works, nothing is saved
        _demo["since"] = sheets.now().strftime("%H:%M:%S")
        return jsonify(time=_demo["since"])
    _guard(g.user["name"], str((request.get_json(silent=True) or {}).get("code", "")))
    try:
        return jsonify(time=sheets.check_in(g.user["name"]))
    except ValueError as e:
        raise ApiError(409, str(e))


@app.post("/api/attendance/check-out")
@login_required()
def check_out():
    if g.user.get("demo"):
        _demo["since"] = None
        return jsonify(hours=0.0)
    # Signing out needs no code: you can only close your own open row.
    try:
        return jsonify(sheets.check_out(g.user["name"]))
    except ValueError as e:
        raise ApiError(409, str(e))


# ----------------------------------------------------------------- hours

DEMO_HOURS = {
    "advisors": ["Sample Advisor"],
    "people": [{"name": n, "hours": h, "days": d} for n, h, d in [
        ("Demo", 6.5, 4), ("Sample Member", 12.5, 9), ("Another Member", 11.5, 8),
        ("Riley Brooks", 10.0, 7), ("Jordan Lee", 9.5, 7), ("Casey Nguyen", 8.0, 6),
        ("Morgan Diaz", 7.5, 5), ("Avery Kim", 5.5, 4), ("Taylor Reed", 3.0, 2),
        ("Quinn Patel", 2.5, 2), ("Jamie Cole", 0.5, 1), ("Drew Foster", 0.0, 0),
    ]],
}


@app.get("/api/hours")
@login_required()
def hours():
    if g.user.get("demo"):
        return jsonify(DEMO_HOURS)
    return jsonify(sheets.hours_summary())


# ------------------------------------------------------------------ leads

@app.get("/api/lead/checked-in")
@login_required(lead_only=True)
def lead_checked_in():
    if g.user.get("demo"):
        return jsonify(people=list(_demo["others"]))
    return jsonify(people=sheets.checked_in_now())


@app.post("/api/lead/check-out")
@login_required(lead_only=True)
def lead_check_out():
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
    if not name:
        raise ApiError(400, "Pick someone to sign out.")
    if g.user.get("demo"):
        _demo["others"] = [p for p in _demo["others"] if p["name"] != name]
        return jsonify(hours=0.0)
    try:
        return jsonify(sheets.check_out(name, by=g.user["name"]))
    except ValueError as e:
        raise ApiError(409, str(e))


# ----------------------------------------------------------------- admin

def _meeting_payload():
    if g.user.get("demo"):  # fake rotating code, not connected to a real meeting
        if not _demo["meeting"]:
            return {"active": False}
        step = config.CODE_STEP_SECONDS
        window = int(time.time() // step)
        return {"active": True, "code": meeting._code("demo", window),
                "seconds_left": int(step - (time.time() % step)), "step": step}
    if not meeting.state().get("active"):
        return {"active": False}
    code, seconds_left = meeting.current()
    return {"active": True, "code": code, "seconds_left": seconds_left,
            "step": config.CODE_STEP_SECONDS}


@app.get("/api/admin/meeting")
@login_required(admin_only=True)
def admin_meeting():
    return jsonify(_meeting_payload())


@app.post("/api/admin/meeting/start")
@login_required(admin_only=True)
def admin_start():
    if g.user.get("demo"):
        _demo["meeting"] = True
    else:
        meeting.start(g.user["name"])
    return jsonify(_meeting_payload())


@app.post("/api/admin/meeting/end")
@login_required(admin_only=True)
def admin_end():
    if g.user.get("demo"):
        _demo["meeting"], _demo["since"] = False, None
        return jsonify(active=False, auto_checked_out=0)
    meeting.end(g.user["name"])
    return jsonify(active=False, auto_checked_out=sheets.close_all_open())


# --------------------------------------------- serve built frontend (prod)

DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def spa(path: str):
    if path.startswith("api/"):
        raise ApiError(404, "Not found")
    if not DIST.exists():
        return "Frontend not built. Run `npm run build` in frontend/ (or use `npm run dev`).", 404
    if path and (DIST / path).is_file():
        return send_from_directory(DIST, path)
    return send_from_directory(DIST, "index.html")
