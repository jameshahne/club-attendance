import "./style.css";
import { api, getToken, setToken, Hours, HoursRow, Status, Task } from "./api";

const root = document.getElementById("app")!;

// ---------------------------------------------------------------- helpers

type Kid = Node | string | null;
function h(tag: string, attrs: Record<string, string> = {}, ...kids: Kid[]): HTMLElement {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  for (const k of kids) if (k !== null) e.append(k);
  return e;
}

/** Replace the page: optional top bar, then content in a centered column. */
function render(top: Node | null, cls: string, content: Node[]) {
  const wrap = h("div", { class: cls });
  wrap.append(...content);
  root.replaceChildren(...(top ? [top] : []), wrap);
}

function show(top: Node | null, ...content: Node[]) {
  render(top, "wrap", content);
}

function showWide(top: Node | null, ...content: Node[]) {
  render(top, "wrap wide", content);
}

type Tab = "home" | "hours" | "admin";

function topbar(active: Tab, admin: boolean): HTMLElement {
  const out = h("button", { class: "link" }, "Sign out");
  out.onclick = () => { setToken(null); loginView(); };

  const bar = h("header", { class: "topbar" },
    h("div", { class: "brand" },
      h("img", { src: "/tiger.png", alt: "" }),
      h("div", {}, "Stony Point Solar ", h("span", {}, "Hours"))),
    h("div", {}, out));

  const tabs = h("nav", { class: "tabs" });
  const entries: [Tab, string, () => void][] = [["home", "Home", homeView], ["hours", "Hours", hoursView]];
  if (admin) entries.push(["admin", "Officer", adminView]);
  for (const [id, label, go] of entries) {
    const b = h("button", { class: id === active ? "tab on" : "tab" }, label);
    b.onclick = go;
    tabs.append(b);
  }
  return h("div", {}, bar, h("div", { class: "stripe" }), tabs);
}

function fmtTime(t: string | null): string {
  if (!t) return "";
  const [hh, mm] = t.split(":").map(Number);
  return `${((hh + 11) % 12) + 1}:${String(mm).padStart(2, "0")} ${hh >= 12 ? "PM" : "AM"}`;
}

let adminTimer: number | undefined;
function stopAdminTimer() {
  if (adminTimer !== undefined) clearInterval(adminTimer);
  adminTimer = undefined;
}

// ------------------------------------------------------------------ login

async function loginView(message = "") {
  stopAdminTimer();
  const select = h("select", { class: "field" }) as HTMLSelectElement;
  select.append(h("option", { value: "" }, "Select your name"));
  const pin = h("input", { class: "field", type: "password", inputmode: "numeric",
    autocomplete: "current-password", placeholder: "PIN" }) as HTMLInputElement;
  const code = h("input", { class: "field", inputmode: "numeric", maxlength: "6",
    autocomplete: "off", placeholder: "Meeting code" }) as HTMLInputElement;
  const btn = h("button", { class: "primary field" }, "Sign in") as HTMLButtonElement;
  const err = h("p", { class: "err" }, message);
  code.hidden = true;
  show(null, h("div", { class: "login" },
    h("img", { src: "/tiger.png", alt: "Stony Point tiger" }),
    h("h1", {}, "Stony Point Solar ", h("span", {}, "Hours")),
    h("div", { class: "stack" }, select, pin, code, btn), err));

  let meetingOn = false;
  const sync = () => { code.hidden = !(meetingOn || select.value === "Demo"); };
  select.onchange = sync;

  try {
    const r = await api.names();
    for (const n of r.names) select.append(h("option", { value: n }, n));
    meetingOn = r.meeting;
    sync();
  } catch (e) {
    err.textContent = (e as Error).message;
  }

  const go = async () => {
    if (!select.value || !pin.value) {
      err.textContent = "Choose your name and enter your PIN.";
      return;
    }
    btn.disabled = true;
    try {
      const r = await api.login(select.value, pin.value, code.hidden ? "" : code.value);
      setToken(r.token);
      homeView();
    } catch (e) {
      err.textContent = (e as Error).message;
      btn.disabled = false;
    }
  };
  btn.onclick = go;
  pin.onkeydown = code.onkeydown = (ev) => { if (ev.key === "Enter") go(); };
}

// ------------------------------------------------------------------- home

async function homeView() {
  stopAdminTimer();
  show(null, h("p", { class: "muted" }, "Loading…"));
  let me, tasks, status;
  try {
    [me, tasks, status] = await Promise.all([api.me(), api.tasks(), api.status()]);
  } catch (e) {
    return loginView((e as Error).message);
  }

  const attendance = h("div", { class: "card" });
  renderAttendance(attendance, status);

  const list = h("div", { class: "card" });
  if (!tasks.week) list.append(h("p", { class: "muted", style: "margin:0" }, "No task list for this week yet."));
  else if (tasks.tasks.length === 0) list.append(h("p", { class: "muted", style: "margin:0" }, "Nothing assigned to you this week."));
  else for (const t of tasks.tasks) list.append(taskRow(t));

  const banner = me.demo
    ? h("div", { class: "card", style: "margin-bottom:16px;font-size:16px" },
        "Demo mode: sample data only, nothing is saved.")
    : null;

  let leadCard: HTMLElement | null = null;
  if (me.lead) {
    leadCard = h("div", { class: "card", style: "margin-top:16px" });
    renderLead(leadCard);
  }

  show(topbar("home", me.admin),
    h("h1", {}, `Hi, ${me.name.split(" ")[0]}`),
    ...(banner ? [banner] : []),
    attendance,
    ...(leadCard ? [leadCard] : []),
    h("h2", {}, tasks.week ? `Your tasks · ${tasks.week}` : "Your tasks"),
    list);
}

function statusClass(s: string): string {
  const v = s.toLowerCase();
  if (v === "completed") return "chip done";
  if (v.includes("partial")) return "chip part";
  if (v.includes("progress")) return "chip prog";
  return "chip";
}

function taskRow(t: Task): HTMLElement {
  const meta = [t.group && `For ${t.group}`, t.due && `Due ${t.due}`, t.tools && `Tools: ${t.tools}`, t.notes]
    .filter(Boolean).join(" · ");
  return h("div", { class: "task" },
    h("div", { class: "task-top" }, h("span", {}, t.task),
      t.status ? h("span", { class: statusClass(t.status) }, t.status) : null),
    meta ? h("div", { class: "muted meta" }, meta) : null);
}

function renderAttendance(card: HTMLElement, s: Status) {
  card.replaceChildren();

  // Signing out never needs a code.
  if (s.checked_in) {
    const btn = h("button", { class: "primary", style: "flex:1" }, "I'm out") as HTMLButtonElement;
    const msg = h("div", {});
    card.append(h("div", { style: "font-size:22px;font-weight:600" }, `Checked in since ${fmtTime(s.since)}`),
      h("div", { class: "row" }, btn), msg);
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        const r = await api.checkOut();
        renderAttendance(card, await api.status());
        card.append(h("div", { class: "ok" }, `Checked out. ${r.hours} hours logged.`));
      } catch (e) {
        msg.replaceChildren(h("div", { class: "err" }, (e as Error).message));
        btn.disabled = false;
      }
    };
    return;
  }

  if (!s.meeting_active) {
    card.append(h("p", { class: "muted", style: "margin:0" }, "No meeting is in progress."));
    return;
  }
  card.append(h("div", { style: "font-size:22px;font-weight:600" }, "Meeting in progress"));

  const input = h("input", { class: "code", inputmode: "numeric", maxlength: "6", placeholder: "••••••" }) as HTMLInputElement;
  const btn = h("button", { class: "primary" }, "I'm here") as HTMLButtonElement;
  const msg = h("div", {});
  card.append(h("div", { class: "row" }, input, btn), msg);

  const go = async () => {
    btn.disabled = true;
    try {
      await api.checkIn(input.value);
      renderAttendance(card, await api.status());
    } catch (e) {
      msg.replaceChildren(h("div", { class: "err" }, (e as Error).message));
      btn.disabled = false;
    }
  };
  btn.onclick = go;
  input.onkeydown = (ev) => { if (ev.key === "Enter") go(); };
}

/** Leads/officers: sign out people who forgot. */
async function renderLead(card: HTMLElement, note = "") {
  card.replaceChildren(h("div", { style: "font-size:20px;font-weight:600" }, "Sign others out"));
  if (note) card.append(h("div", { class: "err" }, note));
  let people: { name: string; since: string }[] = [];
  try {
    people = (await api.leadList()).people;
  } catch (e) {
    card.append(h("div", { class: "err" }, (e as Error).message));
    return;
  }
  if (people.length === 0) {
    card.append(h("p", { class: "muted", style: "margin:12px 0 0" }, "Nobody is checked in right now."));
    return;
  }
  for (const p of people) {
    const btn = h("button", {}, "Sign out") as HTMLButtonElement;
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await api.leadCheckOut(p.name);
        renderLead(card);
      } catch (e) {
        renderLead(card, (e as Error).message);
      }
    };
    card.append(h("div", { class: "person" }, h("span", {}, `${p.name} · since ${fmtTime(p.since)}`), btn));
  }
}

// ------------------------------------------------------------------ hours

const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag: string, attrs: Record<string, string | number> = {}, text?: string): SVGElement {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text !== undefined) e.textContent = text;
  return e;
}

const fmtHours = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));

function shortNames(rows: HoursRow[]): string[] {
  const firsts = rows.map((r) => r.name.split(" ")[0]);
  return rows.map((r, i) => {
    if (firsts.filter((f) => f === firsts[i]).length < 2) return firsts[i];
    const last = r.name.split(" ").slice(1).join(" ");
    return last ? `${firsts[i]} ${last[0]}.` : firsts[i];
  });
}

function hoursChart(rows: HoursRow[], me: string): HTMLElement {
  const labels = shortNames(rows);
  const top = Math.max(...rows.map((r) => r.hours), 1);
  const step = top <= 10 ? 2 : top <= 25 ? 5 : 10;
  const max = Math.ceil(top / step) * step;
  const left = 40, right = 12, up = 24, down = 84, slot = 38, bar = 24, plotH = 240;
  const width = Math.max(left + right + rows.length * slot, 320);
  const y = (v: number) => up + plotH - (v / max) * plotH;

  const s = svg("svg", { width, height: up + plotH + down, role: "img",
    "aria-label": "Total hours per member" });
  for (let v = 0; v <= max; v += step) {
    s.append(
      svg("line", { x1: left, x2: width - right, y1: y(v), y2: y(v), class: "gridline" }),
      svg("text", { x: left - 8, y: y(v) + 4, class: "tick", "text-anchor": "end" }, String(v)));
  }

  rows.forEach((r, i) => {
    const cx = left + i * slot + slot / 2;
    const g = svg("g", { class: r.name === me ? "bar me" : "bar" });
    g.append(
      svg("title", {}, `${r.name}: ${fmtHours(r.hours)} hours`),
      svg("rect", { x: cx - bar / 2, y: y(r.hours), width: bar, height: Math.max(y(0) - y(r.hours), 1), rx: 3 }),
      svg("text", { x: cx, y: y(r.hours) - 6, class: "val", "text-anchor": "middle" }, fmtHours(r.hours)),
      svg("text", { x: cx + 4, y: y(0) + 16, class: "name", "text-anchor": "end",
        transform: `rotate(-45 ${cx + 4} ${y(0) + 16})` }, labels[i]));
    s.append(g);
  });
  return h("div", { class: "chart" }, s);
}

function hoursTable(rows: HoursRow[], me: string): HTMLElement {
  const rank = new Map(rows.map((r) => [r.name, 1 + rows.filter((o) => o.hours > r.hours).length]));
  let key: "name" | "hours" | "days" = "hours";
  let asc = false;

  const table = h("table", { class: "hours-table" });

  const paint = () => {
    const list = [...rows].sort((a, b) => {
      const d = key === "name" ? a.name.localeCompare(b.name) : a[key] - b[key];
      return (asc ? d : -d) || a.name.localeCompare(b.name);
    });

    const th = (label: string, k?: typeof key, cls = "") => {
      const c = h("th", { class: cls }, k && k === key ? `${label} ${asc ? "▲" : "▼"}` : label);
      if (k) {
        c.classList.add("sortable");
        c.onclick = () => {
          asc = k === key ? !asc : k === "name";
          key = k;
          paint();
        };
      }
      return c;
    };

    const body = h("tbody", {});
    for (const r of list) {
      body.append(h("tr", { class: r.name === me ? "me" : "" },
        h("td", { class: "num muted" }, String(rank.get(r.name))),
        h("td", {}, r.name),
        h("td", { class: "num" }, fmtHours(r.hours)),
        h("td", { class: "num" }, String(r.days))));
    }
    table.replaceChildren(
      h("thead", {}, h("tr", {}, th("#", undefined, "num"), th("Name", "name"),
        th("Hours", "hours", "num"), th("Days", "days", "num"))),
      body);
  };
  paint();
  return h("div", { class: "table-wrap" }, table);
}

async function hoursView() {
  stopAdminTimer();
  show(null, h("p", { class: "muted" }, "Loading…"));
  let me, data: Hours;
  try {
    [me, data] = await Promise.all([api.me(), api.hours()]);
  } catch (e) {
    return loginView((e as Error).message);
  }

  const rows = data.people;
  const total = rows.reduce((a, r) => a + r.hours, 0);
  const mine = rows.find((r) => r.name === me.name);
  const place = mine ? 1 + rows.filter((r) => r.hours > mine.hours).length : null;
  const average = rows.length ? Math.round((total / rows.length) * 10) / 10 : 0;

  const stat = (label: string, value: string) =>
    h("div", { class: "card stat" }, h("div", { class: "stat-value" }, value), h("div", { class: "muted" }, label));

  const stats = h("div", { class: "stats" },
    stat("Your hours", mine ? fmtHours(mine.hours) : "–"),
    stat("Your rank", place ? `#${place} of ${rows.length}` : "–"),
    stat("Club total", fmtHours(Math.round(total * 10) / 10)),
    stat("Average per member", fmtHours(average)));

  const advisors = data.advisors.length
    ? [h("h2", {}, "Advisors"),
       h("div", { class: "card advisors" }, ...data.advisors.map((n) => h("span", {}, n)))]
    : [];

  showWide(topbar("hours", me.admin),
    h("h1", {}, "Everyone's hours"),
    ...advisors,
    h("h2", {}, "Overview"),
    stats,
    h("h2", {}, "Total hours"),
    h("div", { class: "card" }, hoursChart(rows, me.name)),
    h("h2", {}, "Leaderboard"),
    h("div", { class: "card flush" }, hoursTable(rows, me.name)));
}

// ------------------------------------------------------------------ admin

async function adminView() {
  stopAdminTimer();
  const body = h("div", {});
  show(topbar("admin", true), h("h1", {}, "Meeting code"), body);

  let remaining = 0;
  let tick = 0;

  const paint = (m: { active: boolean; code?: string; seconds_left?: number }) => {
    body.replaceChildren();
    if (!m.active) {
      const start = h("button", { class: "primary" }, "Start meeting");
      start.onclick = async () => paint(await api.startMeeting());
      body.append(h("div", { class: "card center" },
        h("p", { class: "muted", style: "margin-top:0" }, "No meeting in progress."), start));
      return;
    }
    remaining = m.seconds_left ?? 0;
    const countdown = h("div", { class: "muted center", id: "cd" }, `New code in ${remaining}s`);
    const end = h("button", {}, "End meeting");
    end.onclick = async () => {
      if (!confirm("End the meeting? Anyone still checked in will be checked out now.")) return;
      await api.endMeeting();
      paint({ active: false });
    };
    body.append(
      h("div", { class: "card" }, h("div", { class: "big-code" }, m.code ?? ""), countdown),
      h("div", { class: "center", style: "margin-top:16px" }, end));
  };

  const refresh = async () => {
    try { paint(await api.adminMeeting()); } catch { /* ignore transient errors */ }
  };
  await refresh();

  adminTimer = window.setInterval(() => {
    tick++;
    remaining--;
    const cd = document.getElementById("cd");
    if (cd) cd.textContent = `New code in ${Math.max(remaining, 0)}s`;
    if (remaining <= 0 || tick % 10 === 0) refresh();
  }, 1000);
}

// ------------------------------------------------------------------ start

if (getToken()) homeView();
else loginView();
