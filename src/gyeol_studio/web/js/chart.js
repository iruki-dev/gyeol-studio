// Pitch evidence chart: target and take pitch curves (cents re A4) on the take's time axis, lyric syllables underneath,
// highlighted spans of the selected item, "cannot judge" spans, and a playhead.
const NOTE = ["도", "도#", "레", "레#", "미", "파", "파#", "솔", "솔#", "라", "라#", "시"];
const NOTE_EN = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

export function noteName(cents) {
  const midi = Math.round(69 + cents / 100);
  return `${NOTE_EN[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}
export function noteNameKo(cents) {
  const midi = Math.round(69 + cents / 100);
  return `${NOTE[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

export class PitchChart {
  constructor(canvas, ev, { height = 230 } = {}) {
    this.c = canvas;
    this.ev = ev;
    this.height = height;
    this.spans = [];
    this.playhead = null;
    canvas.style.height = `${height}px`;
    const vals = [...ev.user_cents, ...ev.target_cents].filter((v) => v !== null);
    const lo = vals.length ? Math.min(...vals) : -1200, hi = vals.length ? Math.max(...vals) : 0;
    this.y0 = Math.floor((lo - 150) / 100) * 100;
    this.y1 = Math.ceil((hi + 150) / 100) * 100;
    this.hover = null;
    this._ro = new ResizeObserver(() => this.draw());
    this._ro.observe(canvas);
    canvas.addEventListener("pointermove", (e) => this._move(e));
    canvas.addEventListener("pointerleave", () => { this.hover = null; this._tip && (this._tip.style.display = "none"); this.draw(); });
  }
  destroy() { this._ro.disconnect(); }

  _move(e) {
    const ev = this.ev;
    const r = this.c.getBoundingClientRect();
    const left = 44, right = 8;
    const T = ev.duration_s || 1;
    const t = ((e.clientX - r.left - left) / (r.width - left - right)) * T;
    let i = 0;
    for (let k = 0; k < ev.times.length; k++) if (Math.abs(ev.times[k] - t) < Math.abs(ev.times[i] - t)) i = k;
    this.hover = i;
    this.draw();
    if (!this._tip) {
      this._tip = document.createElement("div");
      Object.assign(this._tip.style, { position: "absolute", pointerEvents: "none", background: "var(--ink)", color: "var(--bg)", padding: "6px 10px",
        borderRadius: "8px", fontSize: ".85rem", whiteSpace: "nowrap", transform: "translate(-50%, -100%)", zIndex: 5 });
      this.c.parentElement.append(this._tip);
    }
    const u = ev.user_cents[i], g = ev.target_cents[i];
    const syl = (ev.syllables || []).find((s) => ev.times[i] >= s.start && ev.times[i] < s.end);
    const lines = [`${ev.times[i].toFixed(1)}초${syl ? ` · '${syl.text}'` : ""}`,
      g !== null ? `목표 ${noteName(g)}` : "목표: 소리 없음",
      u !== null ? `내 노래 ${noteName(u)}${g !== null ? ` (${u - g >= 0 ? "+" : ""}${Math.round(u - g)}센트)` : ""}` : "내 노래: 소리 없음"];
    this._tip.replaceChildren(...lines.map((l, k) => { const d = document.createElement("div"); d.textContent = l; if (!k) d.style.fontWeight = "700"; return d; }));
    this._tip.style.display = "block";
    this._tip.style.left = `${e.clientX - r.left}px`;
    this._tip.style.top = `${8}px`;
  }
  setSpans(s) { this.spans = s || []; this.draw(); }
  setPlayhead(t) { this.playhead = t; this.draw(); }

  draw() {
    const c = this.c, ev = this.ev;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, H = this.height;
    if (!w) return;
    c.width = Math.round(w * dpr); c.height = Math.round(H * dpr);
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const css = getComputedStyle(document.documentElement);
    const col = (n, d) => css.getPropertyValue(n).trim() || d;
    const left = 44, right = 8, top = 8, bottom = 30;
    const T = ev.duration_s || (ev.times.length ? ev.times[ev.times.length - 1] : 1);
    const x = (t) => left + (t / T) * (w - left - right);
    const y = (v) => top + (1 - (v - this.y0) / (this.y1 - this.y0)) * (H - top - bottom);
    // spans of the item
    for (const [a, b] of this.spans) { g.fillStyle = col("--accent", "#c94f35") + "22"; g.fillRect(x(a), top, Math.max(2, x(b) - x(a)), H - top - bottom); }
    // cannot judge
    for (const [a, b] of ev.cannot_judge || []) { g.fillStyle = "rgba(128,128,128,.12)"; g.fillRect(x(a), top, x(b) - x(a), H - top - bottom); }
    // semitone grid
    const range = this.y1 - this.y0;
    const step = range > 1800 ? 200 : 100;
    g.font = "11px sans-serif";
    for (let v = this.y0; v <= this.y1; v += step) {
      g.fillStyle = col("--line", "#ddd");
      g.fillRect(left, y(v), w - left - right, 1);
      const midi = Math.round(69 + v / 100);
      if (step === 100 && ![0, 2, 4, 5, 7, 9, 11].includes(((midi % 12) + 12) % 12)) continue;
      g.fillStyle = col("--muted", "#777");
      g.fillText(noteName(v), 4, y(v) + 4);
    }
    const line = (vals, color, width) => {
      g.strokeStyle = color; g.lineWidth = width; g.lineJoin = "round"; g.lineCap = "round";
      g.beginPath();
      let pen = false;
      vals.forEach((v, i) => {
        if (v === null) { pen = false; return; }
        const X = x(ev.times[i]), Y = y(v);
        if (!pen) { g.moveTo(X, Y); pen = true; } else g.lineTo(X, Y);
      });
      g.stroke();
    };
    line(ev.target_cents, col("--target", "#2a78d6"), 5);
    line(ev.user_cents, col("--user", "#c94f35"), 2.2);
    // syllables
    g.font = "13px sans-serif";
    g.textAlign = "center";
    let lastEnd = -Infinity;
    for (const s of ev.syllables || []) {
      g.fillStyle = col("--line", "#ddd");
      g.fillRect(x(s.start), H - bottom + 4, 1, 22);
      const cx = (x(s.start) + x(s.end)) / 2;
      const tw = g.measureText(s.text).width;
      if (cx - tw / 2 < lastEnd + 3) continue; // no room: skip rather than overlap
      g.fillStyle = col("--ink", "#111");
      g.fillText(s.text, cx, H - 10);
      lastEnd = cx + tw / 2;
    }
    g.textAlign = "start";
    if (this.playhead !== null) { g.fillStyle = col("--ink", "#111"); g.fillRect(x(this.playhead) - 1, top, 2, H - top - bottom); }
    if (this.hover !== null && this.hover < ev.times.length) {
      g.fillStyle = col("--muted", "#777");
      g.fillRect(x(ev.times[this.hover]) - 0.5, top, 1, H - top - bottom);
      for (const [v, c] of [[ev.target_cents[this.hover], col("--target", "#2a78d6")], [ev.user_cents[this.hover], col("--user", "#c94f35")]]) {
        if (v === null) continue;
        g.beginPath(); g.arc(x(ev.times[this.hover]), y(v), 4.5, 0, Math.PI * 2); g.fillStyle = c; g.fill();
        g.lineWidth = 2; g.strokeStyle = col("--surface", "#fff"); g.stroke();
      }
    }
  }
}
