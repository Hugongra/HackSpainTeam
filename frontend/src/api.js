// Talks to the AngryRobot service. The shared secret lives in sessionStorage only (never in the URL,
// never in the build), so a static page on GitHub Pages can hold no credentials of its own.
export const DEFAULT_API = import.meta.env.VITE_ANGRYROBOT_API || "https://hackspainteam.onrender.com";

const read = (store, key, fallback = "") => { try { return window[store].getItem(key) ?? fallback; } catch { return fallback; } };
const write = (store, key, value) => { try { value ? window[store].setItem(key, value) : window[store].removeItem(key); } catch { /* blocked storage */ } };

export const settings = {
  get api() { return read("localStorage", "ar_api", DEFAULT_API) || DEFAULT_API; },
  set api(v) { write("localStorage", "ar_api", (v || "").replace(/\/+$/, "")); },
  get secret() { return read("sessionStorage", "ar_secret"); },
  set secret(v) { write("sessionStorage", "ar_secret", v); },
};

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function call(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && settings.secret) headers["X-AngryRobot-Secret"] = settings.secret;
  let res;
  try {
    res = await fetch(settings.api + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError("The service did not answer. On the free plan it sleeps after 15 minutes idle; the first request wakes it in about 30 seconds.", 0);
  }
  if (res.status === 401) throw new ApiError("The shared secret was rejected. Check it under Connection.", 401);
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail; } catch { /* not json */ }
    throw new ApiError(`${res.status}: ${detail || res.statusText}`, res.status);
  }
  return res.json();
}

export const api = {
  health: () => call("/health", { auth: false }),
  signals: () => call("/v1/signals", { auth: false }),
  runs: (limit = 50) => call(`/v1/runs?limit=${limit}`),
  run: (id) => call(`/v1/runs/${encodeURIComponent(id)}`),
  alerts: (limit = 100) => call(`/alerts?limit=${limit}`),
  audit: (body) => call("/v1/audit", { method: "POST", body }),
  feedback: (body) => call("/v1/feedback", { method: "POST", body }),
  // Platform: connected workflows, escalations, kill switch
  workflows: () => call("/v1/workflows"),
  workflow: (id) => call(`/v1/workflows/${encodeURIComponent(id)}`),
  createWorkflow: (body) => call("/v1/workflows", { method: "POST", body }),
  updateWorkflow: (id, body) => call(`/v1/workflows/${encodeURIComponent(id)}`, { method: "PATCH", body }),
  control: (id, action, note = "") => call(`/v1/workflows/${encodeURIComponent(id)}/control`, { method: "POST", body: { action, note } }),
  controlAll: (action, note = "") => call("/v1/workflows/control-all", { method: "POST", body: { action, note } }),
  escalations: (status) => call(`/v1/escalations${status ? `?status=${status}` : ""}`),
  // Providers: agents that already exist on a platform (HappyRobot first)
  providers: () => call("/v1/providers"),
  hrWorkflows: () => call("/v1/providers/happyrobot/workflows"),
  hrConnect: (body) => call("/v1/providers/happyrobot/connect", { method: "POST", body }),
  providerLink: (id) => call(`/v1/providers/links/${encodeURIComponent(id)}`),
  resolve: (id, decision, note = "") => call(`/v1/escalations/${encodeURIComponent(id)}/resolve`, { method: "POST", body: { decision, note } }),
  // Rounds: random agents through the 5-seat workflow, one malicious at 50 %, step by step (angryrobot/rounds.py)
  roundConfig: () => call("/v1/rounds/config"),
  startRound: (body) => call("/v1/rounds", { method: "POST", body }),
  round: (id) => call(`/v1/rounds/${encodeURIComponent(id)}`),
  rounds: () => call("/v1/rounds"),
  roundNext: (id) => call(`/v1/rounds/${encodeURIComponent(id)}/next`, { method: "POST" }),
  roundPace: (id, pace, delay) => call(`/v1/rounds/${encodeURIComponent(id)}/pace`, { method: "POST", body: { pace, delay } }),
  roundStop: (id) => call(`/v1/rounds/${encodeURIComponent(id)}/stop`, { method: "POST" }),
  roundReveal: (id) => call(`/v1/rounds/${encodeURIComponent(id)}/reveal`, { method: "POST" }),
  roundStats: () => call("/v1/rounds/stats"),
};
