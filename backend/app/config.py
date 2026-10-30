import os

from dotenv import load_dotenv

load_dotenv()


def _list(name: str) -> list[str]:
    return [x.strip().lower() for x in os.getenv(name, "").split(",") if x.strip()]


SHEET_ID = os.environ.get("SHEET_ID", "")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", "service_account.json")
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me")
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "12"))

TIMEZONE = os.getenv("TIMEZONE", "America/Chicago")
LOG_TAB = os.getenv("LOG_TAB", "Attendance Log")
# Tab with each member's teams (Mechanical, Electrical, ...) and Lead status. Read-only.
MEMBERS_TAB = os.getenv("MEMBERS_TAB", "Member Information")
# Records who started and who ended each meeting (sheet only, not shown in the app).
MEETING_LOG_TAB = os.getenv("MEETING_LOG_TAB", "Meeting Log")
# A meeting someone forgot to end is closed automatically after this many hours.
MEETING_MAX_HOURS = float(os.getenv("MEETING_MAX_HOURS", "12"))
# Who started/ended each meeting. This tab is also where the app remembers whether a meeting is open.
MEETING_LOG_TAB = os.getenv("MEETING_LOG_TAB", "Meeting Log")
# A meeting someone forgot to end stops accepting check-ins after this many hours.
MEETING_MAX_HOURS = float(os.getenv("MEETING_MAX_HOURS", "12"))
MEETING_TAB = os.getenv("MEETING_TAB", "Meeting")

# Where names + PINs live. By default a tab called "Logins" in the same spreadsheet.
# To use a completely separate spreadsheet file, set LOGINS_SHEET_ID (share it with the service account too).
LOGINS_TAB = os.getenv("LOGINS_TAB", "Logins")
LOGINS_SHEET_ID = os.getenv("LOGINS_SHEET_ID", "")

# Sandbox account for looking around: pick "Demo" and enter this PIN. Nothing is saved to the sheet.
# Set DEMO_PIN to nothing to turn it off.
DEMO_PIN = os.getenv("DEMO_PIN", "0000")
if DEMO_PIN.strip().lower() in ("off", "none", "disabled"):
    DEMO_PIN = ""

# Officers (by name, exactly as in Member Information) who can start/end meetings.
ADMIN_NAMES = _list("ADMIN_NAMES")

# Optional: only allow check-in from these public IPs (your school/club Wi-Fi).
ALLOWED_IPS = [x.strip() for x in os.getenv("ALLOWED_IPS", "").split(",") if x.strip()]
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() == "true"

CODE_STEP_SECONDS = int(os.getenv("CODE_STEP_SECONDS", "30"))

# Hours logged by hand before the app existed: every column headed with a date (10/21, 10/24, ...)
# in this tab is added to that member's total on the Hours tab.
PAST_HOURS_TAB = os.getenv("PAST_HOURS_TAB", MEMBERS_TAB)
