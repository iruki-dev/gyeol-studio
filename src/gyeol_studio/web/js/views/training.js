// Training: start a run on the chosen data (all / commercially usable only), watch progress and validation,
// stop and resume, compare the new model with the current one, apply or roll back, and see where the data came from.
import { api } from "../api.js";
import { onJobs, pollNow } from "../jobs.js";
import { h, clear, showError, toast, jobLine, fmtDate, confirmDialog } from "../ui.js";

const STATUS = { queued: ["준비 중", "accent"], running: ["학습 중", "accent"], paused: ["멈춤", "warn"], done: ["끝남", "ok"], failed: ["실패", "err"] };
const SCOPE = { all: "전체 데이터", commercial: "상업 이용 가능한 데이터만" };
const SCOPE_SHORT = { all: "전체", commercial: "상업 이용 가능만" };
const LABEL_KO = { "register:chest": "흉성", "register:mixed": "믹스", "register:falsetto": "가성", "phonation:none": "맑은 소리(해당 없음)",
  "phonation:breathy": "숨섞임", "phonation:pressed_belt": "압착·벨팅", "phonation:pharyngeal_twang": "트왱", "phonation:fry": "프라이", "phonation:rough": "거침" };
const pct = (v) => (v === null || v === undefined || !isFinite(v) ? "-" : `${Math.round(v * 100)}%`);
const NS = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}, ...kids) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); kids.forEach((x) => el.append(x)); return el; };

// validation loss over training steps — one series, so the title names it and no legend is needed
function lossChart(history) {
  const pts = history.filter((x) => isFinite(x.loss));
  if (pts.length < 2) return null;
  const W = 520, H = 120, L = 40, R = 10, T = 10, B = 22;
  const xs = pts.map((p) => p.step), ys = pts.map((p) => p.loss);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y1 = Math.max(...ys) * 1.1, y0 = Math.min(0, Math.min(...ys));
  const X = (v) => L + ((v - x0) / Math.max(1, x1 - x0)) * (W - L - R);
  const Y = (v) => T + (1 - (v - y0) / Math.max(1e-9, y1 - y0)) * (H - T - B);
  const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", style: "max-width:520px", role: "img", "aria-label": "검증 손실 변화" });
  for (const f of [0, 0.5, 1]) {
    const v = y0 + (y1 - y0) * f;
    s.append(svg("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: "var(--line)" }), svg("text", { x: L - 6, y: Y(v) + 4, "text-anchor": "end", "font-size": 11, fill: "var(--muted)" }, v.toFixed(2)));
  }
  s.append(svg("path", { d: pts.map((p, i) => `${i ? "L" : "M"}${X(p.step)},${Y(p.loss)}`).join(""), fill: "none", stroke: "var(--user)", "stroke-width": 2 }));
  pts.forEach((p) => { const c = svg("circle", { cx: X(p.step), cy: Y(p.loss), r: 4, fill: p.best ? "var(--user)" : "var(--surface)", stroke: "var(--user)", "stroke-width": 2 }); c.append(svg("title", {}, `${p.step}단계: ${p.loss.toFixed(3)}${p.best ? " (가장 좋음)" : ""}`)); s.append(c); });
  s.append(svg("text", { x: L, y: H - 4, "font-size": 11, fill: "var(--muted)" }, `${x0}단계`), svg("text", { x: W - R, y: H - 4, "text-anchor": "end", "font-size": 11, fill: "var(--muted)" }, `${x1}단계`));
  return h("div", {}, h("div", { class: "hint" }, "검증 손실 (낮을수록 좋음, 채운 점은 그때까지 가장 좋은 모델)"), s);
}

export async function render(view) {
  const box = h("div", { class: "stack", style: { maxWidth: "900px" } });
  clear(view, h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "학습"),
    h("p", {}, "라벨을 붙인 녹음으로 발성(흉성·믹스·가성)과 음질(숨섞임 등)을 알아듣는 모델을 학습해요."))), box);
  let scope = "all", preset = "quick";
  const openRuns = new Set(); // keep opened run details open across redraws

  async function draw() {
    const o = await api.get("/api/training");
    const runs = o.runs;
    const live = runs.find((r) => ["queued", "running", "paused"].includes(r.status));
    const lastDone = runs.find((r) => r.status === "done");
    const active = runs.find((r) => r.id === o.active);
    const parts = [];

    parts.push(h("div", { class: "notice warn" }, h("span", { class: "ico" }, "ⓘ"), h("div", {},
      "지금 gyeol 라이브러리에는 학습한 모델을 녹음 분석에 바로 쓰는 방법이 없어요. 그래서 '적용'은 어떤 모델을 쓸지 기록해 두는 것까지만 하고, ",
      "코칭 화면의 결과는 아직 바뀌지 않아요. 라이브러리가 지원하면 바로 이어 쓸 수 있어요.")));

    // start
    const el = o.eligible[scope];
    const enough = el.users >= o.min_singers;
    const scopeSeg = h("div", { class: "seg" }, Object.entries(SCOPE_SHORT).map(([id, l]) => h("button", { "aria-pressed": String(scope === id), onclick: () => { scope = id; draw(); } }, l)));
    const presetSeg = h("div", { class: "seg" }, Object.entries(o.presets).map(([id, l]) => h("button", { "aria-pressed": String(preset === id), onclick: () => { preset = id; draw(); } }, l)));
    parts.push(h("div", { class: "card" }, h("h2", {}, "새로 학습하기"),
      h("div", { class: "field" }, h("span", { style: { fontWeight: 600, display: "block", marginBottom: "6px" } }, "학습 데이터 범위"), scopeSeg,
        h("small", { class: "muted", style: { display: "block", marginTop: "4px" } }, "학습에 동의한 녹음만 써요. '상업 이용 가능만'은 상업적 학습에도 동의한 사람의 녹음만 골라요.")),
      h("p", {}, `이 범위에서 쓸 수 있는 녹음: ${el.takes}개 · ${el.users}명 · 기술 녹음 짝 ${el.pairs}개`),
      !enough ? h("div", { class: "notice" }, h("span", { class: "ico" }, "👥"), `학습·검증·평가에 서로 다른 사람이 필요해서, 라벨을 붙인 녹음이 ${o.min_singers}명 이상 있어야 해요.`) : null,
      h("div", { class: "field" }, h("span", { style: { fontWeight: 600, display: "block", marginBottom: "6px" } }, "방식"), presetSeg),
      h("button", { class: "btn primary", disabled: !enough || !!(live && live.status !== "paused"), onclick: async () => {
        try { await api.post("/api/training/runs", { scope, preset }); pollNow(); toast("학습을 시작했어요. 앱을 닫아도 다음에 열면 이어서 해요."); draw(); } catch (e) { showError(e); }
      } }, "학습 시작")));

    // live run
    if (live) {
      const pr = live.progress || {};
      const lv = pr.last_val || {};
      parts.push(h("div", { class: "card" }, h("div", { class: "row between" }, h("h2", { style: { margin: 0 } }, `진행 중인 학습 — ${SCOPE[live.scope]}`),
        h("span", { class: `badge ${STATUS[live.status][1]}` }, STATUS[live.status][0])),
      live.job && live.status !== "paused" ? h("div", { style: { margin: "10px 0" } }, jobLine(live.job, { title: false })) : null,
      live.status === "paused" ? h("p", {}, live.job ? live.job.message : "멈췄어요.") : null,
      lv.step ? h("dl", { class: "kv" }, h("dt", {}, "최근 검증"), h("dd", {}, `${lv.step}단계`),
        h("dt", {}, o.metric_labels.loss), h("dd", {}, isFinite(lv.loss) ? lv.loss.toFixed(3) : "-"),
        ...(["register_acc", "phonation_acc"].filter((k) => k in lv).flatMap((k) => [h("dt", {}, o.metric_labels[k]), h("dd", {}, pct(lv[k]))]))) : null,
      lossChart(pr.history || []),
      h("div", { class: "row", style: { marginTop: "10px" } },
        live.status === "paused" ? h("button", { class: "btn primary", onclick: async () => { try { await api.post(`/api/training/runs/${live.id}/resume`); pollNow(); draw(); } catch (e) { showError(e); } } }, "이어서 학습")
          : h("button", { class: "btn", onclick: async () => { try { await api.post(`/api/training/runs/${live.id}/stop`); toast("지금 단계까지 저장하고 멈출게요."); } catch (e) { showError(e); } } }, "멈추기"),
        h("span", { class: "hint" }, "멈춰도 그때까지 배운 것은 저장돼요."))));
    }

    // compare
    if (lastDone) {
      const keys = [...new Set([...Object.keys(lastDone.metrics), ...Object.keys(active ? active.metrics : {})])].filter((k) => o.metric_labels[k] || k.startsWith("test_"));
      const isActive = lastDone.id === o.active;
      parts.push(h("div", { class: "card" }, h("h2", {}, "새 모델과 지금 모델 비교"),
        h("p", { class: "hint" }, "학습에 쓰지 않은 사람의 녹음으로 평가한 결과예요. 모델마다 평가에 쓴 사람이 다를 수 있어요."),
        ((lastDone.report || {}).test_singers || []).length < 3 ? h("div", { class: "notice" }, h("span", { class: "ico" }, "👥"),
          `평가에 쓴 사람이 ${((lastDone.report || {}).test_singers || []).length}명뿐이라 점수가 사람에 따라 크게 달라질 수 있어요. 녹음한 사람이 늘수록 믿을 만해져요.`) : null,
        h("table", { class: "simple" }, h("tr", {}, h("th", {}, "항목"), h("th", {}, active ? `지금 모델 (${fmtDate(active.created_at)})` : "지금: gyeol 기본 분석"),
          h("th", {}, `새 모델 (${fmtDate(lastDone.created_at)})`)),
        keys.map((k) => h("tr", {}, h("td", {}, o.metric_labels[k] || k), h("td", {}, active ? fmtMetric(k, active.metrics[k]) : "-"), h("td", {}, fmtMetric(k, lastDone.metrics[k]))))),
        h("div", { class: "row", style: { marginTop: "12px" } },
          h("button", { class: "btn primary", disabled: isActive, onclick: async () => { try { await api.post(`/api/training/runs/${lastDone.id}/apply`); toast("새 모델을 적용했어요."); draw(); } catch (e) { showError(e); } } },
            isActive ? "적용됨" : "새 모델 적용"),
          h("button", { class: "btn", disabled: !o.active, onclick: async () => { try { await api.post("/api/training/rollback"); toast("이전 모델로 되돌렸어요."); draw(); } catch (e) { showError(e); } } }, "되돌리기"))));
    }

    // all runs with provenance
    parts.push(h("div", { class: "card" }, h("h2", {}, "학습 기록과 출처"), runs.length ? runs.map((r) => runItem(r, o)) : h("p", { class: "hint" }, "아직 학습한 적이 없어요.")));
    clear(box, parts);
  }

  function fmtMetric(k, v) {
    if (v === undefined || v === null || !isFinite(v)) return "-";
    return k.endsWith("_acc") ? pct(v) : v.toFixed(3);
  }

  function runItem(r, o) {
    const ds = r.data_summary || {};
    const [label, tone] = STATUS[r.status] || [r.status, ""];
    const det = h("details", { class: "coach-item", style: { marginBottom: "8px" }, open: openRuns.has(r.id) || undefined,
      ontoggle: (e) => { if (e.target.open) openRuns.add(r.id); else openRuns.delete(r.id); } },
      h("summary", {}, h("span", { class: `badge ${tone}` }, label), `${fmtDate(r.created_at)} · ${SCOPE[r.scope]}`, r.id === o.active ? h("span", { class: "badge ok" }, "적용됨") : null),
      h("div", {},
        h("dl", { class: "kv" },
          h("dt", {}, "데이터"), h("dd", {}, ds.takes !== undefined ? `녹음 ${ds.takes}개 · ${ds.users.length}명 · 기술 녹음 짝 ${ds.pairs}개` : "준비 전"),
          h("dt", {}, "라벨"), h("dd", {}, Object.entries(ds.label_counts || {}).map(([k, n]) => `${LABEL_KO[k] || k} ${n}`).join(", ") || "-"),
          h("dt", {}, "출처"), h("dd", {}, (r.provenance && r.provenance.sources_info || []).map((s) => `${s.source_ko || s.name} — ${s.license_ko || s.license}`).join(", ") || "학습이 끝나면 표시돼요"),
          h("dt", {}, "동의 범위"), h("dd", {}, r.scope === "commercial" ? "상업적 학습에 동의한 녹음만" : "학습에 동의한 녹음 전체"),
          r.report ? h("dt", {}, "학습") : null, r.report ? h("dd", {}, `${r.report.steps}단계, ${Math.round(r.report.elapsed_s)}초, 평가에 쓴 사람 ${(r.report.test_singers || []).length}명`,
            r.report.status === "early_stopped" ? h("div", { class: "hint" }, `검증 점수가 더 나아지지 않아 일찍 끝냈어요. 가장 좋았던 ${r.report.best_step}단계의 모델을 남겼어요.`) : null) : null),
        r.data_removed ? h("p", { class: "hint" }, "이 학습에 쓰인 녹음 중 일부를 주인이 지워서, 복사해 둔 녹음과 준비한 데이터는 지웠어요. 이미 학습한 모델은 남아 있어요.") : null,
        r.status === "failed" && r.job ? h("p", { class: "hint" }, r.job.error) : null,
        !["queued", "running"].includes(r.status) && r.id !== o.active ? h("button", { class: "btn small ghost", onclick: async () => {
          if (!(await confirmDialog("이 학습 기록을 지울까요?", "모델 파일과 준비한 데이터가 함께 지워져요.", { ok: "지우기", danger: true }))) return;
          try { await api.del(`/api/training/runs/${r.id}`); draw(); } catch (e) { showError(e); }
        } }, "지우기") : null));
    return det;
  }

  await draw();
  let last = "";
  return onJobs((jobs) => {
    const sig = JSON.stringify(jobs.filter((j) => j.kind === "train").map((j) => [j.id, j.status, Math.round((j.progress || 0) * 50)]));
    if (sig !== last) { last = sig; draw().catch(() => {}); }
  });
}
