// Practice history: how each phrase changed (one small chart per measure — never two scales on one chart),
// daily singing time against the recommended limit, and fatigue signs with a suggestion to rest.
import { api } from "../api.js";
import { go } from "../router.js";
import { h, clear, fmtDate, fmtDay } from "../ui.js";

const NS = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) el.setAttribute(k, v);
  kids.flat().forEach((k) => k && el.append(k instanceof Node ? k : document.createTextNode(String(k))));
  return el;
}

// Charts are drawn at the container's real pixel width (and again when it changes), so labels keep their size.
function responsive(wrap, build) {
  const holder = h("div");
  wrap.append(holder);
  let lastW = 0;
  const ro = new ResizeObserver(() => {
    const w = Math.round(holder.clientWidth);
    if (!w || Math.abs(w - lastW) < 4) return;
    lastW = w;
    clear(holder, build(w));
  });
  ro.observe(holder);
  return wrap;
}

function tooltip(wrap) {
  const tip = h("div", { style: { position: "absolute", pointerEvents: "none", background: "var(--ink)", color: "var(--bg)", padding: "6px 10px",
    borderRadius: "8px", fontSize: ".85rem", whiteSpace: "nowrap", transform: "translate(-50%, -110%)", display: "none", zIndex: 5 } });
  wrap.append(tip);
  return {
    show(x, y, lines) { clear(tip, lines.map((l, i) => h("div", { style: i ? { opacity: .85 } : { fontWeight: 700 } }, l))); tip.style.left = `${x}px`; tip.style.top = `${y}px`; tip.style.display = "block"; },
    hide() { tip.style.display = "none"; },
  };
}

// One measure over takes: 2px line, 8px markers, recessive grid, hover tooltip.
function lineChart(points, { title, unit, height = 170 }) {
  const wrap = h("div", { class: "card flat", style: { position: "relative" } });
  const vals = points.map((p) => p.v).filter((v) => v !== null);
  wrap.append(h("div", { class: "row between" }, h("b", {}, title), h("span", { class: "hint" }, `낮을수록 목표와 가까워요 · 단위 ${unit}`)));
  if (vals.length < 1) { wrap.append(h("p", { class: "hint" }, "아직 이 항목을 잴 수 있는 녹음이 없어요.")); return wrap; }
  const tip = tooltip(wrap);
  return responsive(wrap, (W) => {
    const H = height, L = 40, R = 12, T = 12, B = 26;
    const max = Math.max(...vals) * 1.15 || 1;
    const n = points.length;
    const x = (i) => L + (n === 1 ? (W - L - R) / 2 : (i / (n - 1)) * (W - L - R));
    const y = (v) => T + (1 - v / max) * (H - T - B);
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": `${title} 변화 그래프` });
    for (const f of [0, 0.5, 1]) {
      svg.append(s("line", { x1: L, x2: W - R, y1: y(max * f / 1.15), y2: y(max * f / 1.15), stroke: "var(--line)", "stroke-width": 1 }));
      svg.append(s("text", { x: L - 6, y: y(max * f / 1.15) + 4, "text-anchor": "end", "font-size": 11, fill: "var(--muted)" }, Math.round(max * f / 1.15)));
    }
    let d = "";
    points.forEach((p, i) => { if (p.v === null) return; d += `${d ? "L" : "M"}${x(i)},${y(p.v)}`; });
    svg.append(s("path", { d, fill: "none", stroke: "var(--user)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    points.forEach((p, i) => { if (p.v !== null) svg.append(s("circle", { cx: x(i), cy: y(p.v), r: 4, fill: "var(--user)", stroke: "var(--surface)", "stroke-width": 2 })); });
    // session boundaries as x labels
    let lastDay = "";
    points.forEach((p, i) => {
      const dday = new Date(p.t * 1000).toLocaleDateString("ko-KR", { month: "numeric", day: "numeric" });
      if (dday !== lastDay) { svg.append(s("text", { x: x(i), y: H - 6, "text-anchor": "middle", "font-size": 11, fill: "var(--muted)" }, dday)); lastDay = dday; }
  });
  const hit = s("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" });
  const guide = s("line", { y1: T, y2: H - B, stroke: "var(--muted)", "stroke-width": 1, "stroke-dasharray": "3 3", visibility: "hidden" });
  svg.append(guide, hit);
  hit.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    let best = 0;
    points.forEach((_p, i) => { if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i; });
    const p = points[best];
    guide.setAttribute("x1", x(best)); guide.setAttribute("x2", x(best)); guide.setAttribute("visibility", "visible");
    const wr = wrap.getBoundingClientRect();
    tip.show((x(best) / W) * r.width + (r.left - wr.left), (y(p.v ?? 0) / H) * r.height + (r.top - wr.top),
      [`${best + 1}번째 녹음 · ${p.v === null ? "잴 수 없음" : `${p.v}${unit}`}`, fmtDate(p.t), p.primary ? `먼저 들은 부분: ${p.primary.label}` : ""].filter(Boolean));
  });
  hit.addEventListener("pointerleave", () => { tip.hide(); guide.setAttribute("visibility", "hidden"); });
  return svg;
  });
}

function dayBars(days, warnS) {
  const wrap = h("div", { class: "card", style: { position: "relative" } });
  wrap.append(h("div", { class: "row between" }, h("b", {}, "하루 노래한 시간"), h("span", { class: "hint" }, "실제로 소리를 낸 시간만 셌어요")));
  const tip = tooltip(wrap);
  return responsive(wrap, (W) => {
    const H = 200, L = 44, R = 12, T = 14, B = 26;
    const mins = days.map((d) => d.voiced_s / 60);
    const warn = warnS / 60;
    const max = Math.max(warn * 1.2, ...mins, 1);
    const n = days.length;
    const bw = (W - L - R) / n;
    const y = (v) => T + (1 - v / max) * (H - T - B);
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "하루 노래한 시간 막대그래프" });
    for (const v of [0, Math.round(max / 2), Math.round(max)]) {
      svg.append(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: "var(--line)" }));
      svg.append(s("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end", "font-size": 11, fill: "var(--muted)" }, `${v}분`));
    }
    days.forEach((d, i) => {
      const v = mins[i];
      const x0 = L + i * bw + 2;
      const hgt = Math.max(0, y(0) - y(v));
      const bar = s("path", { d: v > 0 ? roundedTop(x0, y(v), bw - 4, hgt, Math.min(4, hgt)) : "", fill: "var(--user)" });
      svg.append(bar);
      const label = new Date(d.day + "T00:00:00").toLocaleDateString("ko-KR", { day: "numeric" });
      if (i % 2 === (n - 1) % 2) svg.append(s("text", { x: x0 + (bw - 4) / 2, y: H - 6, "text-anchor": "middle", "font-size": 11, fill: "var(--muted)" }, label));
      const hit = s("rect", { x: L + i * bw, y: T, width: bw, height: H - T - B, fill: "transparent" });
      hit.addEventListener("pointerenter", () => {
        const r = svg.getBoundingClientRect(), wr = wrap.getBoundingClientRect();
        tip.show(((x0 + bw / 2) / W) * r.width + (r.left - wr.left), (y(v) / H) * r.height + (r.top - wr.top),
          [fmtDay(new Date(d.day + "T12:00:00").getTime() / 1000), `소리 낸 시간 ${v.toFixed(1)}분 · 녹음 ${d.takes}개`]);
      });
      hit.addEventListener("pointerleave", () => tip.hide());
      svg.append(hit);
  });
  svg.append(s("line", { x1: L, x2: W - R, y1: y(warn), y2: y(warn), stroke: "var(--warn)", "stroke-width": 1.5, "stroke-dasharray": "5 4" }));
  svg.append(s("text", { x: W - R, y: y(warn) - 5, "text-anchor": "end", "font-size": 11, fill: "var(--muted)" }, `하루 권장 상한 ${Math.round(warn)}분`));
  return svg;
  });
}

function roundedTop(x, y, w, hgt, r) {
  return `M${x},${y + hgt}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hgt}Z`;
}

export async function render(view, params) {
  const [{ phrases }, wb] = await Promise.all([api.get("/api/history/phrases"), api.get("/api/history/wellbeing")]);
  const top = h("div", { class: "stack" });
  const restCard = h("div", { class: "card" });
  const mm = (sec) => `${Math.floor(sec / 60)}분 ${Math.round(sec % 60)}초`;
  clear(restCard, h("h2", {}, "오늘의 목 상태"),
    h("div", { class: "grid", style: { gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" } },
      h("div", {}, h("div", { class: "hint" }, "오늘 노래한 시간"), h("div", { class: "big-number" }, mm(wb.today_s))),
      h("div", {}, h("div", { class: "hint" }, "이번 연습"), h("div", { class: "big-number" }, mm(wb.session_s)))),
    wb.notices.length ? wb.notices.map((n) => h("div", { class: "notice warn" }, h("span", { class: "ico" }, "☕"), n.text))
      : h("div", { class: "notice ok" }, h("span", { class: "ico" }, "✓"), wb.session_takes >= wb.fatigue_min_attempts ? "피로 신호는 보이지 않아요. 그래도 중간중간 물을 마셔 주세요."
        : `피로 신호는 한 번 연습에서 ${wb.fatigue_min_attempts}번 이상 녹음하면 살펴봐요.`),
    h("p", { class: "hint" }, wb.referral));
  top.append(restCard, dayBars(wb.days, wb.norms.daily_warn_s));

  const phraseBox = h("div", { class: "stack" });
  const pid = params[0] || (phrases[0] && phrases[0].id);
  const pick = h("div", { class: "chips" }, phrases.map((p) => h("button", { class: "chip", "aria-pressed": String(p.id === pid),
    onclick: () => go(`#/history/${p.id}`) }, `${p.song_title} · ${p.lyrics || p.name}`)));
  clear(view, h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "연습 기록"), h("p", {}, "소절별로 무엇이 좋아졌는지, 오늘 얼마나 노래했는지 볼 수 있어요."))),
    top, h("h2", { style: { marginTop: "22px" } }, "소절별 변화"),
    phrases.length ? pick : h("div", { class: "card empty" }, h("p", {}, "아직 녹음이 없어요. 곡 보관함에서 소절을 골라 연습해 보세요.")), phraseBox);
  if (!pid) return;
  const hist = await api.get(`/api/history/phrase/${pid}`);
  const charts = Object.entries(hist.tracks).map(([k, t]) => lineChart(hist.points.map((p) => ({ v: p.metrics[k] ?? null, t: p.t, primary: p.primary })),
    { title: t.label, unit: t.unit }));
  const counts = {};
  hist.points.forEach((p) => { if (p.primary) counts[p.primary.label] = (counts[p.primary.label] || 0) + 1; });
  clear(phraseBox, h("p", { class: "hint" }, `녹음 ${hist.points.length}개. 점 위에 손가락이나 마우스를 올리면 자세히 보여요.`),
    h("div", { class: "grid", style: { gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" } }, charts),
    Object.keys(counts).length ? h("div", { class: "card flat" }, h("b", {}, "가장 먼저 짚은 부분"), h("div", { class: "chips", style: { marginTop: "8px" } },
      Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => h("span", { class: "badge" }, `${k} ${v}번`)))) : null);
}
