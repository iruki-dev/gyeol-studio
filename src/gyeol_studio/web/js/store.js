// Per-browser preferences (current user, latency calibration, recording conditions, volumes).
// Wrapped in try/catch: private windows can refuse storage, and the app must still work.
const KEY = "gyeol-studio";

function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; }
}
function save(v) {
  try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* storage unavailable */ }
}

let state = load();
const listeners = new Set();

export const store = {
  get(k, d) { return state[k] === undefined ? d : state[k]; },
  set(k, v) { state = { ...state, [k]: v }; save(state); listeners.forEach((f) => f(k, v)); },
  userId() { return state.user || null; },
  setUser(id) { this.set("user", id); },
  on(f) { listeners.add(f); return () => listeners.delete(f); },
  // latency per output route: { wired: {ms, method, at}, bluetooth: …, speaker: … }
  latency(route) { return (state.latency || {})[route] || null; },
  setLatency(route, v) { this.set("latency", { ...(state.latency || {}), [route]: v }); },
  conditions() {
    return { device: "", earphone: "wired", backing: "on", place: "", ...(state.conditions || {}) };
  },
  setConditions(c) { this.set("conditions", c); },
};
