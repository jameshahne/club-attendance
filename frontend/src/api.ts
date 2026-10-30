const KEY = "club_token";

export const getToken = () => localStorage.getItem(KEY);
export const setToken = (t: string | null) =>
  t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY);

export interface Task {
  task: string;
  people: string[];
  due: string;
  status: string;
  tools: string;
  notes: string;
  group?: string; // set when the task is for a team (e.g. "Whole team") rather than the person by name
}
export interface Status {
  meeting_active: boolean;
  checked_in: boolean;
  since: string | null;
}
export interface HoursRow {
  name: string;
  hours: number;
  days: number;
}
export interface Hours {
  people: HoursRow[];
  advisors: string[];
}
export interface AdminMeeting {
  active: boolean;
  code?: string;
  seconds_left?: number;
  step?: number;
}

async function req<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const token = getToken();
  const res = await fetch("/api" + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && token && path !== "/auth/login") {
    setToken(null);
    location.reload();
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Something went wrong");
  }
  return res.json();
}

export const api = {
  names: () => req<{ names: string[]; meeting: boolean }>("/members"),
  login: (name: string, pin: string, code: string) =>
    req<{ token: string; name: string; admin: boolean; checked_in: boolean }>(
      "/auth/login", "POST", { name, pin, code }),
  hours: () => req<Hours>("/hours"),
  me: () => req<{ name: string; admin: boolean; demo: boolean; lead: boolean }>("/me"),
  tasks: () => req<{ week: string | null; tasks: Task[] }>("/tasks"),
  status: () => req<Status>("/attendance/status"),
  checkIn: (code: string) => req<{ time: string }>("/attendance/check-in", "POST", { code }),
  checkOut: () => req<{ hours: number }>("/attendance/check-out", "POST"),
  leadList: () => req<{ people: { name: string; since: string }[] }>("/lead/checked-in"),
  leadCheckOut: (name: string) => req<{ hours: number }>("/lead/check-out", "POST", { name }),
  adminMeeting: () => req<AdminMeeting>("/admin/meeting"),
  startMeeting: () => req<AdminMeeting>("/admin/meeting/start", "POST"),
  endMeeting: () => req<{ auto_checked_out: number }>("/admin/meeting/end", "POST"),
};
