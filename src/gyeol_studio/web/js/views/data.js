// Data: label recordings with a few taps, export in gyeol's formats, and see how people answered the feedback.
import { api } from "../api.js";
import { onJobs, pollNow } from "../jobs.js";
import { h, clear, showError, toast, modal, fmtDate, jobLine, confirmDialog } from "../ui.js";
import { playUrl } from "../audio/abplayer.js";

let VOCAB = null;
async function vocab() {
  if (!VOCAB) VOCAB = await api.get("/api/labels/vocab");
  return VOCAB;
}

const ITEM_LABEL = {
  "pitch:intonation_offset": "음 높이", "pitch:global_offset": "전체 음 높이", "pitch:contour_deviation": "음 흐름", "pitch:transition_deviation": "음 이동",
  "pitch:interval_compression": "음 간격", "rhythm:onset_timing": "들어가는 타이밍", "rhythm:tempo": "빠르기", "ornament:vibrato_extent": "비브라토 폭",
  "ornament:vibrato_rate": "비브라토 속도", "ornament:scoop": "스쿱", "ornament:fall": "폴", "dynamics:loudness": "음 세기", "dynamics:dynamic_range": "강약 폭",
  "phonation:breathiness": "숨소리",
};

// The label editor for one take: chips that save on every tap.
export async function labelEditor(take, { onSaved } = {}) {
  const V = await vocab();
  let cur = { register: null, qualities: null, rhythm: null, memo: "", ...(take.labels || {}) };
  const saved = h("span", { class: "hint", "aria-live": "polite", style: { whiteSpace: "nowrap" } });
  // Taps update the local state at once; saves go out one after another with the latest state, so quick taps never
  // overwrite each other (a slower earlier response must not undo a later tap).
  let chain = Promise.resolve();
  let sent = null;
  function save(patch) {
    cur = { ...cur, ...patch };
    draw();
    saved.textContent = "저장하는 중…";
    const snapshot = { ...cur };
    chain = chain.then(async () => {
      try {
        await api.put(`/api/takes/${take.id}/labels`, snapshot);
        if (snapshot === sent) { saved.textContent = "저장됨 ✓"; onSaved && onSaved(cur); }
      } catch (e) { showError(e); saved.textContent = "저장하지 못했어요"; }
    });
    sent = snapshot;
  }
  const groupReg = h("div", { class: "chips", role: "group", "aria-label": "발성" });
  const groupQ = h("div", { class: "chips", role: "group", "aria-label": "음질" });
  const groupR = h("div", { class: "chips", role: "group", "aria-label": "박자" });
  const memo = h("input", { type: "text", maxlength: 500, placeholder: "메모 (선택)", value: cur.memo || "" });
  memo.addEventListener("change", () => save({ memo: memo.value }));
  function draw() {
    clear(groupReg, V.register.map((o) => h("button", { class: "chip small", title: o.help, "aria-pressed": String(cur.register === o.id),
      onclick: () => save({ register: cur.register === o.id ? null : o.id }) }, o.label)));
    const qs = new Set(cur.qualities || []);
    clear(groupQ, V.qualities.map((o) => h("button", { class: "chip small", title: o.help, "aria-pressed": String(qs.has(o.id)), onclick: () => {
      let next = new Set(qs);
      if (o.id === "none") next = qs.has("none") ? new Set() : new Set(["none"]);
      else { next.delete("none"); next.has(o.id) ? next.delete(o.id) : next.add(o.id); }
      save({ qualities: next.size ? [...next] : null });
    } }, o.label)));
    clear(groupR, V.rhythm.map((o) => h("button", { class: "chip small", title: o.help, "aria-pressed": String(cur.rhythm === o.id),
      onclick: () => save({ rhythm: cur.rhythm === o.id ? null : o.id }) }, o.label)));
  }
  draw();
  const row = (label, g) => h("div", { class: "row", style: { alignItems: "flex-start", flexWrap: "nowrap", gap: "12px", margin: "6px 0" } },
    h("b", { style: { width: "3.2em", flex: "none", paddingTop: "4px" } }, label), g);
  return h("div", {}, row("발성", groupReg), row("음질", groupQ), row("박자", groupR), h("div", { class: "row", style: { flexWrap: "nowrap" } }, memo, saved));
}

function glossary(V) {
  return h("details", { class: "card flat adv" }, h("summary", {}, "용어 설명 보기"),
    h("dl", { class: "kv", style: { marginTop: "10px" } }, [...V.register, ...V.qualities, ...V.rhythm].flatMap((o) => [h("dt", {}, o.label), h("dd", {}, o.help)])));
}

export async function labelDialog(takeId) {
  try {
    const t = await api.get(`/api/takes/${takeId}`);
    const ed = await labelEditor(t);
    const V = await vocab();
    const m = modal([h("h2", {}, "라벨 붙이기"), h("p", { class: "hint" }, "들은 그대로 골라 주세요. 누를 때마다 바로 저장돼요. 잘 모르겠으면 비워 둬도 돼요."),
      h("button", { class: "btn small", onclick: () => playUrl(`/api/takes/${takeId}/audio`).catch(showError) }, "▶ 녹음 듣기"), ed, glossary(V),
      h("div", { class: "modal-actions" }, h("button", { class: "btn primary", onclick: () => m.close() }, "다 됐어요"))]);
  } catch (e) { showError(e); }
}

export async function render(view, params) {
  const tab = params[0] || "labels";
  const V = await vocab();
  const sum = await api.get("/api/data/summary");
  const tiles = h("div", { class: "grid", style: { gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", marginBottom: "16px" } },
    [["녹음", `${sum.takes}개`, `${sum.people}명이 불렀어요`], ["라벨", `${sum.labeled}개`, "라벨을 붙인 녹음"], ["학습 동의", `${sum.training_ok}개`, `상업 이용 가능 ${sum.commercial_ok}개`],
      ["피드백 응답", `${sum.responses}개`, "맞아요/아니에요 응답"]].map(([a, b, c]) => h("div", { class: "card flat" }, h("div", { class: "hint" }, a), h("div", { class: "big-number" }, b), h("div", { class: "hint" }, c))));
  const tabs = h("div", { class: "seg", role: "tablist", style: { marginBottom: "14px" } },
    [["labels", "라벨 붙이기"], ["export", "내보내기"], ["responses", "피드백 응답"]].map(([id, label]) =>
      h("button", { role: "tab", "aria-pressed": String(tab === id), onclick: () => { location.hash = `#/data/${id}`; } }, label)));
  const body = h("div");
  clear(view, h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "데이터"), h("p", {}, "녹음과 피드백 응답은 모델을 더 좋게 만드는 데이터가 돼요."))), tiles, tabs, body);
  if (tab === "export") return renderExport(body);
  if (tab === "responses") return renderResponses(body, sum);
  return renderLabels(body, V);
}

async function renderLabels(body, V) {
  let who = "mine", unlabeled = true;
  const list = h("div", { class: "stack" });
  const whoSeg = h("div", { class: "seg" }, [["mine", "내 녹음"], ["all", "모든 사람"]].map(([id, l]) =>
    h("button", { "aria-pressed": String(who === id), onclick: (e) => { who = id; whoSeg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.target))); load(); } }, l)));
  const only = h("input", { type: "checkbox", checked: unlabeled, onchange: () => { unlabeled = only.checked; load(); } });
  clear(body, h("div", { class: "row between", style: { marginBottom: "12px" } }, whoSeg, h("label", { class: "row", style: { gap: "6px" } }, only, "라벨 없는 것만")),
    glossary(V), h("div", { style: { height: "12px" } }), list);
  async function load() {
    const { takes } = await api.get(`/api/data/takes?who=${who}&unlabeled=${unlabeled}`);
    if (!takes.length) { clear(list, h("div", { class: "card empty" }, h("p", {}, unlabeled ? "라벨을 기다리는 녹음이 없어요. 수고하셨어요!" : "녹음이 없어요."))); return; }
    clear(list, await Promise.all(takes.map(async (t) => {
      const ed = await labelEditor(t);
      const tech = t.technique ? h("span", { class: "badge accent" }, `기술 녹음: ${t.technique.label || ""}`) : null;
      return h("div", { class: "card" },
        h("div", { class: "row between" },
          h("div", {}, h("b", {}, t.lyrics || t.phrase_name), h("div", { class: "hint" }, `${t.song_title} · ${t.user_name} · ${fmtDate(t.created_at)}`,
            t.conditions && t.conditions.earphone ? ` · ${{ wired: "유선 이어폰", bluetooth: "블루투스", speaker: "스피커" }[t.conditions.earphone] || ""}` : "")),
          h("div", { class: "row" }, tech, h("button", { class: "btn small", onclick: () => playUrl(`/api/takes/${t.id}/audio`).catch(showError) }, "▶ 듣기"))),
        ed);
    })));
  }
  await load();
}

async function renderExport(body) {
  const box = h("div", { class: "stack" });
  clear(body, box);
  async function draw(jobs = []) {
    const r = await api.get("/api/exports");
    const running = jobs.filter((j) => j.kind === "export_data" && ["queued", "running"].includes(j.status));
    const card = (kind, title, files, desc) => {
      const scope = h("select", {}, h("option", { value: "all" }, "학습 동의한 녹음 전체"), h("option", { value: "commercial" }, "상업 이용 가능한 녹음만"));
      const count = h("span", { class: "hint" });
      const upd = () => { count.textContent = `지금 내보낼 수 있는 녹음 ${r.eligible[scope.value][kind]}개`; };
      scope.addEventListener("change", upd);
      upd();
      return h("div", { class: "card" }, h("h2", {}, title), h("p", {}, desc), h("p", { class: "hint mono" }, files),
        h("div", { class: "row" }, scope, h("button", { class: "btn primary", onclick: async () => {
          try { await api.post("/api/exports", { kind, scope: scope.value }); pollNow(); toast("내보내기를 시작했어요."); } catch (e) { showError(e); }
        } }, "내보내기"), count));
    };
    clear(box,
      h("div", { class: "grid fit" },
        card("eval", "평가용", "manifest.jsonl", "gyeol 라이브러리의 실제 녹음 평가(gyeol eval realset)에 바로 쓸 수 있는 폴더를 만들어요. 목표 소절과 녹음, 박자 라벨, 녹음 조건이 들어가요."),
        card("train", "학습용", "recordings.json · manifest.json", "라벨(발성·음질)을 붙인 녹음으로 학습용 폴더를 만들어요. 기술 녹음의 짝 정보도 함께 들어가요.")),
      running.map((j) => h("div", { class: "card flat" }, jobLine(j))),
      h("div", { class: "notice" }, h("span", { class: "ico" }, "🔒"), h("div", {}, "학습에 동의한 녹음만 내보내요. 사람 이름 대신 무작위 번호로 표시돼요. 누군가 데이터 삭제를 요청하면 그 사람이 들어 있는 내보내기 폴더도 지워져요.")),
      h("div", { class: "card" }, h("h2", {}, "내보낸 폴더"), r.exports.length ? h("table", { class: "simple" },
        h("tr", {}, h("th", {}, "만든 때"), h("th", {}, "종류"), h("th", {}, "녹음"), h("th", {}, "")),
        r.exports.map((e) => h("tr", {}, h("td", {}, fmtDate(e.created_at)), h("td", {}, e.kind === "eval" ? "평가용" : "학습용", e.scope === "commercial" ? " · 상업 가능만" : ""),
          h("td", {}, `${e.takes}개 · ${e.n_users}명`),
          h("td", {}, h("div", { class: "row" },
            r.local ? h("button", { class: "btn small", onclick: () => api.post(`/api/exports/${e.name}/open`).catch(showError) }, "폴더 열기") : null,
            h("a", { class: "btn small", href: `/api/exports/${e.name}/zip` }, "zip 받기"),
            h("button", { class: "btn small ghost", onclick: async () => {
              if (!(await confirmDialog("내보낸 폴더를 지울까요?", "앱 안의 녹음은 그대로 남아요.", { ok: "지우기", danger: true }))) return;
              try { await api.del(`/api/exports/${e.name}`); draw(); } catch (err) { showError(err); }
            } }, "지우기")))))) : h("p", { class: "hint" }, "아직 내보낸 적이 없어요.")));
  }
  await draw();
  let last = "";
  return onJobs((jobs) => {
    const sig = JSON.stringify(jobs.filter((j) => j.kind === "export_data").map((j) => [j.id, j.status]));
    if (sig !== last) { last = sig; draw(jobs).catch(() => {}); }
  });
}

function renderResponses(body, sum) {
  const rows = Object.entries(sum.responses_by_item).sort((a, b) => (b[1].agree + b[1].disagree + b[1].unsure) - (a[1].agree + a[1].disagree + a[1].unsure));
  if (!rows.length) { clear(body, h("div", { class: "card empty" }, h("p", {}, "아직 피드백 응답이 없어요. 코칭 화면의 '맞아요 / 아닌 것 같아요 / 모르겠어요'가 여기에 모여요."))); return; }
  clear(body, h("div", { class: "card" }, h("h2", {}, "지적별 응답"), h("p", { class: "hint" }, "'아닌 것 같아요'가 많은 항목은 모델이 자주 틀리는 부분일 수 있어요."),
    h("table", { class: "simple" }, h("tr", {}, h("th", {}, "항목"), h("th", {}, "응답"), h("th", { style: { width: "45%" } }, "")),
      rows.map(([k, v]) => {
        const n = v.agree + v.disagree + v.unsure;
        const bar = h("div", { style: { display: "flex", height: "12px", borderRadius: "6px", overflow: "hidden", background: "var(--surface-2)" } },
          h("i", { style: { width: `${(v.agree / n) * 100}%`, background: "var(--ok)" }, title: `맞아요 ${v.agree}` }),
          h("i", { style: { width: `${(v.unsure / n) * 100}%`, background: "var(--muted)" }, title: `모르겠어요 ${v.unsure}` }),
          h("i", { style: { width: `${(v.disagree / n) * 100}%`, background: "var(--err)" }, title: `아닌 것 같아요 ${v.disagree}` }));
        return h("tr", {}, h("td", {}, ITEM_LABEL[k] || k), h("td", { class: "hint" }, `맞아요 ${v.agree} · 모르겠어요 ${v.unsure} · 아니에요 ${v.disagree}`), h("td", {}, bar));
      }))));
}
