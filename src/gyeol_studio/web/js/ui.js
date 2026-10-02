// Small DOM helpers, toasts, modals, progress lines and formatting.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") el.innerHTML = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function clear(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

export const icons = {
  play: '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l13-7.5z" fill="currentColor"/></svg>',
  pause: '<svg viewBox="0 0 24 24"><rect x="6" y="4.5" width="4" height="15" rx="1" fill="currentColor"/><rect x="14" y="4.5" width="4" height="15" rx="1" fill="currentColor"/></svg>',
  stop: '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  mic: '<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor"/><path d="M6 11a6 6 0 0 0 12 0M12 17v4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>',
  back: '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7" stroke="currentColor" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M5 7h14M10 7V4.5h4V7M7 7l1 13h8l1-13" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linejoin="round"/></svg>',
  headphones: '<svg viewBox="0 0 24 24"><path d="M4 15v-3a8 8 0 0 1 16 0v3" stroke="currentColor" stroke-width="1.8" fill="none"/><rect x="3" y="14" width="5" height="7" rx="2" fill="currentColor"/><rect x="16" y="14" width="5" height="7" rx="2" fill="currentColor"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

export function icon(name) {
  const span = h("span", { class: "ico-svg", "aria-hidden": "true" });
  span.innerHTML = icons[name] || "";
  span.style.display = "inline-flex";
  return span;
}

// ---------- toasts ----------
export function toast(message, { error = false, detail = "", ms = 4500 } = {}) {
  const box = document.getElementById("toasts");
  const t = h("div", { class: "toast" + (error ? " err" : ""), role: error ? "alert" : "status" }, message);
  if (detail) t.append(h("details", {}, h("summary", {}, "자세히 보기"), h("pre", {}, detail)));
  box.append(t);
  setTimeout(() => t.remove(), detail ? ms * 3 : ms);
}

export function showError(e) {
  console.error(e);
  toast(e && e.message ? e.message : "처리하는 중에 문제가 생겼어요. 다시 시도해 주세요.", { error: true, detail: (e && e.detail) || "" });
}

// ---------- modal ----------
export function modal(content, { wide = false, onClose } = {}) {
  const back = h("div", { class: "modal-back" });
  const box = h("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true" });
  back.append(box);
  append(box, [content]);
  const close = () => { back.remove(); document.removeEventListener("keydown", onKey); onClose && onClose(); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  back.addEventListener("click", (e) => { if (e.target === back) close(); });
  document.addEventListener("keydown", onKey);
  document.body.append(back);
  const first = box.querySelector("input, select, textarea, button");
  first && setTimeout(() => first.focus(), 30);
  return { close, box };
}

export function confirmDialog(title, body, { ok = "확인", danger = false, input = null } = {}) {
  return new Promise((resolve) => {
    let field = null;
    if (input) field = h("input", { type: "text", placeholder: input.placeholder || "" });
    const okBtn = h("button", { class: "btn " + (danger ? "danger" : "primary") }, ok);
    const cancel = h("button", { class: "btn" }, "취소");
    const m = modal([h("h2", {}, title), h("p", {}, body), field ? h("label", { class: "field" }, h("span", {}, input.label), field) : null,
      h("div", { class: "modal-actions" }, cancel, okBtn)], { onClose: () => resolve(null) });
    cancel.onclick = () => { m.close(); };
    okBtn.onclick = () => { const v = field ? field.value : true; m.close(); resolve(v); };
  });
}

// ---------- formatting ----------
export function fmtTime(s) {
  if (s === null || s === undefined || !isFinite(s)) return "-";
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(1).padStart(4, "0")}`;
}

export function fmtEta(s) {
  if (s === null || s === undefined || !isFinite(s)) return "";
  if (s < 5) return "곧 끝나요";
  if (s < 60) return `약 ${Math.ceil(s / 5) * 5}초 남음`;
  if (s < 3600) return `약 ${Math.round(s / 60)}분 남음`;
  const hh = Math.floor(s / 3600);
  const mm = Math.round((s - hh * 3600) / 60);
  return `약 ${hh}시간${mm ? " " + mm + "분" : ""} 남음`;
}

export function fmtDate(t) {
  const d = new Date(t * 1000);
  return d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function fmtDay(t) {
  return new Date(t * 1000).toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "short" });
}

// ---------- job progress line ----------
export function jobLine(job, { title = true } = {}) {
  const pct = Math.round((job.progress || 0) * 100);
  const running = job.status === "running";
  const bar = h("div", { class: "progress" + (running && !job.progress ? " indeterminate" : "") }, h("i", { style: { width: `${Math.max(3, pct)}%` } }));
  const state = { queued: "차례를 기다리는 중", running: job.message || "진행 중", done: "끝났어요", failed: job.error || "실패했어요",
    cancelled: "취소했어요", paused: job.message || "멈춤" }[job.status];
  return h("div", { class: "job-line" },
    title ? h("b", {}, job.title) : null,
    job.status === "done" || job.status === "failed" ? null : bar,
    h("div", { class: "meta" }, h("span", {}, state), h("span", {}, running ? `${pct}% · ${fmtEta(job.eta_s)}` : "")));
}

export function initials(name) {
  return (name || "?").trim().slice(0, 1);
}

export function termHint(word, explanation) {
  return h("span", { class: "term", title: explanation, tabindex: "0", "aria-label": `${word}: ${explanation}` }, word);
}
