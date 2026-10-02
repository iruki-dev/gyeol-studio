// Canvas waveform: visible window (zoom + scroll), drag to select a range, drag a selection edge to adjust,
// named regions (existing phrases) and a playhead.  Works with mouse and touch (pointer events).

export class Waveform {
  constructor(container, { peaks, duration, height = 140, onSelect, onSeek } = {}) {
    this.peaks = peaks || [];
    this.duration = duration || 1;
    this.view = [0, this.duration];
    this.sel = null;
    this.regions = [];
    this.playhead = null;
    this.onSelect = onSelect;
    this.onSeek = onSeek;
    this.canvas = document.createElement("canvas");
    this.canvas.style.height = `${height}px`;
    this.canvas.setAttribute("role", "img");
    this.canvas.setAttribute("aria-label", "곡 파형. 끌어서 소절 구간을 고르세요.");
    container.append(this.canvas);
    this.height = height;
    this._drag = null;
    this.canvas.addEventListener("pointerdown", (e) => this._down(e));
    this.canvas.addEventListener("pointermove", (e) => this._move(e));
    this.canvas.addEventListener("pointerup", (e) => this._up(e));
    this.canvas.addEventListener("pointercancel", () => { this._drag = null; });
    this._ro = new ResizeObserver(() => this.draw());
    this._ro.observe(this.canvas);
  }

  destroy() { this._ro.disconnect(); }

  setView(t0, t1) {
    const span = Math.min(Math.max(t1 - t0, 1), this.duration);
    t0 = Math.max(0, Math.min(t0, this.duration - span));
    this.view = [t0, t0 + span];
    this.draw();
  }

  setSelection(sel) { this.sel = sel; this.draw(); }
  setRegions(r) { this.regions = r || []; this.draw(); }
  setPlayhead(t) { this.playhead = t; this.draw(); }

  _x(t) { const w = this.canvas.clientWidth; return ((t - this.view[0]) / (this.view[1] - this.view[0])) * w; }
  _t(x) { const w = this.canvas.clientWidth || 1; return this.view[0] + (x / w) * (this.view[1] - this.view[0]); }
  _px(e) { const r = this.canvas.getBoundingClientRect(); return e.clientX - r.left; }

  _down(e) {
    this.canvas.setPointerCapture(e.pointerId);
    const x = this._px(e);
    const t = this._t(x);
    const edge = 12;
    if (this.sel && Math.abs(x - this._x(this.sel.start)) < edge) this._drag = { mode: "start" };
    else if (this.sel && Math.abs(x - this._x(this.sel.end)) < edge) this._drag = { mode: "end" };
    else this._drag = { mode: "new", t0: t, moved: false };
  }

  _move(e) {
    const x = this._px(e);
    const t = Math.max(0, Math.min(this.duration, this._t(x)));
    if (!this._drag) {
      const edge = 12;
      const near = this.sel && (Math.abs(x - this._x(this.sel.start)) < edge || Math.abs(x - this._x(this.sel.end)) < edge);
      this.canvas.style.cursor = near ? "ew-resize" : "crosshair";
      return;
    }
    const d = this._drag;
    if (d.mode === "new") {
      if (Math.abs(t - d.t0) > (this.view[1] - this.view[0]) * 0.004) d.moved = true;
      if (d.moved) this.sel = { start: Math.min(d.t0, t), end: Math.max(d.t0, t) };
    } else if (d.mode === "start") {
      this.sel = { start: Math.min(t, this.sel.end - 0.1), end: this.sel.end };
    } else if (d.mode === "end") {
      this.sel = { start: this.sel.start, end: Math.max(t, this.sel.start + 0.1) };
    }
    this.draw();
  }

  _up(e) {
    const d = this._drag;
    this._drag = null;
    if (!d) return;
    if (d.mode === "new" && !d.moved) {
      this.onSeek && this.onSeek(this._t(this._px(e)));
      return;
    }
    this.onSelect && this.sel && this.onSelect({ ...this.sel });
  }

  draw() {
    const c = this.canvas;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, hgt = this.height;
    if (!w) return;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(hgt * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(hgt * dpr); }
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, hgt);
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue("--muted").trim() || "#888";
    const accent = css.getPropertyValue("--accent").trim() || "#c94f35";
    const line = css.getPropertyValue("--line").trim() || "#ddd";
    // regions (existing phrases)
    for (const r of this.regions) {
      const x0 = this._x(r.start), x1 = this._x(r.end);
      if (x1 < 0 || x0 > w) continue;
      g.fillStyle = r.color || "rgba(125,138,153,.18)";
      g.fillRect(x0, 0, x1 - x0, hgt);
      g.fillStyle = ink;
      g.font = "12px sans-serif";
      g.fillText(r.label || "", Math.max(4, x0 + 4), 14, Math.max(10, x1 - x0 - 8));
    }
    // waveform
    const n = this.peaks.length;
    if (n) {
      const mid = hgt / 2;
      g.fillStyle = ink;
      const per = n / this.duration;
      for (let px = 0; px < w; px++) {
        const a = Math.floor(this._t(px) * per), b = Math.max(a + 1, Math.floor(this._t(px + 1) * per));
        let lo = 0, hi = 0;
        for (let i = Math.max(0, a); i < Math.min(n, b); i++) { if (this.peaks[i][0] < lo) lo = this.peaks[i][0]; if (this.peaks[i][1] > hi) hi = this.peaks[i][1]; }
        const y0 = mid - hi * (mid - 4), y1 = mid - lo * (mid - 4);
        g.fillRect(px, y0, 1, Math.max(1, y1 - y0));
      }
    }
    // time grid
    const span = this.view[1] - this.view[0];
    const step = span > 120 ? 30 : span > 40 ? 10 : span > 12 ? 2 : 1;
    g.fillStyle = line;
    g.font = "11px sans-serif";
    for (let t = Math.ceil(this.view[0] / step) * step; t <= this.view[1]; t += step) {
      const x = this._x(t);
      g.fillRect(x, hgt - 12, 1, 12);
      g.fillStyle = ink;
      const m = Math.floor(t / 60), s = Math.round(t % 60);
      g.fillText(`${m}:${String(s).padStart(2, "0")}`, x + 3, hgt - 2);
      g.fillStyle = line;
    }
    // selection
    if (this.sel) {
      const x0 = this._x(this.sel.start), x1 = this._x(this.sel.end);
      g.fillStyle = accent + "33";
      g.fillRect(x0, 0, x1 - x0, hgt);
      g.fillStyle = accent;
      g.fillRect(x0 - 1.5, 0, 3, hgt);
      g.fillRect(x1 - 1.5, 0, 3, hgt);
      g.beginPath(); g.arc(x0, hgt / 2, 6, 0, Math.PI * 2); g.arc(x1, hgt / 2, 6, 0, Math.PI * 2); g.fill();
    }
    if (this.playhead !== null && this.playhead !== undefined) {
      const x = this._x(this.playhead);
      g.fillStyle = css.getPropertyValue("--ink").trim() || "#000";
      g.fillRect(x - 1, 0, 2, hgt);
    }
  }
}

// Tiny waveform for a take (peaks from the recorded buffer or the server).
export function drawMiniWave(canvas, peaks, { color } = {}) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 200, hgt = canvas.clientHeight || 40;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(hgt * dpr);
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.fillStyle = color || getComputedStyle(document.documentElement).getPropertyValue("--muted").trim() || "#888";
  const n = peaks.length;
  if (!n) return;
  let amp = 0;
  for (const [lo, hi] of peaks) amp = Math.max(amp, -lo, hi);
  const k = amp > 0 ? 0.95 / amp : 1;
  for (let px = 0; px < w; px++) {
    const i = Math.floor((px / w) * n);
    const [lo, hi] = peaks[i];
    const y0 = hgt / 2 - hi * k * (hgt / 2), y1 = hgt / 2 - lo * k * (hgt / 2);
    g.fillRect(px, y0, 1, Math.max(1, y1 - y0));
  }
}

export function peaksOf(samples, n = 300) {
  const out = [];
  const per = samples.length / n;
  for (let i = 0; i < n; i++) {
    let lo = 0, hi = 0;
    for (let j = Math.floor(i * per); j < Math.floor((i + 1) * per); j++) { const v = samples[j]; if (v < lo) lo = v; if (v > hi) hi = v; }
    out.push([lo, hi]);
  }
  return out;
}
