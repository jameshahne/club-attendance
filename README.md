# Club Hours

Attendance site for the club. Members sign in with their name and PIN, hit I'm here / I'm out, and see
their tasks for the week. Everything is stored in our Google Sheet, so there's no database.

- Backend: Python (Flask) in `backend/`
- Frontend: TypeScript (Vite) in `frontend/`

## Keeping attendance honest

A check-in only counts if the server agrees with all of this:

1. A meeting is open. An officer starts it from the Officer tab.
2. The member typed the current 6-digit code. It changes every 30 seconds and is shown on the Officer tab, so put
   it on the projector. A code texted to a friend is dead within a minute. Signing out doesn't need a code.
3. Optional: set `ALLOWED_IPS` to the room's public IP so check-ins from anywhere else are rejected.
4. Name and PIN match. Everyone has their own PIN.
5. Five wrong PINs or codes in a minute locks that person out for a bit.

Signing in also checks you in. When a meeting is open the login screen has a meeting code box, so name + PIN + code
does both at once. Leave the code blank if you only want to look around, and use I'm here later.

Hours are rounded to the nearest half hour at check-out (1h 20m is 1.5, 1h 10m is 1.0, under 15 minutes is 0).

If someone forgets to sign out, leads (tagged Lead in Member Information) and officers get a "Sign others out" card on
the Home tab. The log notes who did it, like "signed out by Kai Landen". Ending a meeting also checks out anyone still
in, and flags it in the Note column.

It isn't perfect. Someone in the room could read the code to a friend on the same Wi-Fi. `ALLOWED_IPS` plus keeping
the screen inside the room covers nearly every real case.

## Hours tab

Everyone can see the whole club's hours: a bar chart, a leaderboard (click a header to sort), the club total and
their own rank. Advisors are listed at the top and left out of the chart and ranking.

A member's total is their Attendance Log hours plus any hours logged by hand before the app. Those come from every
column headed with a date (`10/21`, `10/24`, ...) in the `Member Information` tab, matched by name (full name, or
first name if it's unique). Use `PAST_HOURS_TAB` to read them from a different tab. Only keep dates from before the
app in there, or those meetings get counted twice.

## Sheet setup

| Tab | What the app needs |
| --- | --- |
| `Logins` | New tab just for sign-in. Header row with **Name** and **PIN**, one row per member. Put `Advisor` in any other column for advisors. `Member Information` isn't used for this. If you'd rather keep it in a separate file, set `LOGINS_SHEET_ID` in `.env` and share that file with the service account. |
| Weekly tabs (like `10/25-10/31`) | Named `M/D-M/D`. The tab whose range includes today is used. Needs **Task** and **People** columns (Due Date, Status, Tools Needed, Notes are optional). |
| `Member Information` | Read-only. Used for teams and leads. A cell saying Mechanical, Electrical, Telemetry or Social Media marks a team (comma separate if there's more than one), and a cell saying Lead marks a lead. It looks at cell contents, so column order doesn't matter. Needs a Name column in the header row. |
| `Attendance Log` | Created automatically. Date, Name, Check In, Check Out, Hours, Note. |
| `Meeting Log` | Created automatically. One row per meeting: who started it, who ended it, and when. Not shown in the app. A meeting nobody ends closes itself after 12 hours (`(auto: timed out)`). |

A task shows up for someone when their name is in **People**, or when People names a group they're in:

| In People | Shown to |
| --- | --- |
| `Whole team` (also `All`, `Everyone`) | every member |
| `Mechanical team`, `Electrical team`, `Telemetry team`, `Social Media team` | members on that team in Member Information |
| `Leads` | members tagged Lead |

Group tasks say "For Whole team" (etc.) on the task. The app switches to the new week's tab by itself, checking
every minute for the tab whose dates include today, so just name each new tab in that format. If no tab covers
today, members see "No task list for this week yet."

A name in People matches the full name or the first name from the Logins tab, so "Gowtham" matches
"Gowtham Kumar". If two members share a first name, use full names.

PINs are stored as plain text, so anyone who can open the Logins tab can read them. Lock that tab down to
officers (or use a separate spreadsheet) and tell people not to reuse a PIN from somewhere else.

## Demo account

Pick Demo on the login screen and enter `DEMO_PIN` (default `0000`). It has sample tasks and sample hours, lets you
press I'm here / I'm out with any code, and shows the Officer tab with a fake rotating code. Nothing touches the real
sheet or real meetings. Set `DEMO_PIN=` (blank) in `.env` before going live if you don't want it.

## Google setup (for the sheet only)

1. In the [Google Cloud Console](https://console.cloud.google.com), create a project.
2. Enable the Google Sheets API.
3. IAM & Admin > Service Accounts > create one, then Keys > add a JSON key. Save it as
   `backend/service_account.json`.
4. Open the Google Sheet, hit Share, and add the service account's `client_email` as an Editor. If your tabs are
   locked, it also needs permission on the protected `Attendance Log`. The other tabs only need read access.
5. The sheet ID is the long string in the sheet's URL between `/d/` and `/edit`.

## Running it locally

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # fill in SHEET_ID, JWT_SECRET, ADMIN_NAMES   (Windows: copy)
flask --app app.main run --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                 # open http://localhost:5173
```

## What the server keeps

Nothing on disk. The open meeting lives in memory and is copied to the `Meeting Log` tab, so if the server restarts
(or a free host puts it to sleep) mid-meeting, it picks the meeting back up from the sheet. The code's secret comes
from `JWT_SECRET` and is never written anywhere. The attendance log is read once and cached in memory, refreshed
every 60 seconds, so a room full of people checking in at once doesn't hit Google's rate limits. Run a single worker,
since the cache and meeting state live in that process.

## Deploying on Render (free)

1. Push the project to a private GitHub repo. Upload the contents of the `club-attendance` folder so `render.yaml` is
   at the top level. The built frontend is already in `frontend/dist`, so Render doesn't need Node. Never upload
   `.env` or `service_account.json`.
2. On [render.com](https://render.com), sign up with GitHub, then New > Blueprint and pick the repo.
3. Render will ask for the values marked in `render.yaml`:
   - `SHEET_ID`: from the sheet URL
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: open `service_account.json` in Notepad, select all, paste it in
   - `ADMIN_NAMES`: officers' full names, comma separated
   - `DEMO_PIN`: a PIN for the Demo account, or `off`
4. Apply it. When the build finishes, open the `https://club-hours-....onrender.com` address.

Free services sleep after about 15 minutes with no visits and take around a minute to wake up, so have an officer
open the site a few minutes before each meeting.

After changing the frontend, run `npm run build` in `frontend/` and upload the new `dist` folder.

To skip the Blueprint, create a Web Service by hand with the build command
`pip install -r backend/requirements.txt` and the start command
`cd backend && gunicorn --workers 1 --threads 4 -b 0.0.0.0:$PORT app.main:app`, plus the same environment
variables and `TRUST_PROXY=true`.

## Running it on a laptop in the meeting room

```bash
cd frontend && npm install && npm run build
cd ../backend && pip install waitress && waitress-serve --port 8000 app.main:app
```

Members on the same Wi-Fi open `http://<that computer's IP>:8000`. Only people on that network can reach it.
