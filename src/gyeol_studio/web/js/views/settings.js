// Settings: my profile and consent, model weights, data folder, CPU threads, and "고급" coaching options.
import { api } from "../api.js";
import { store } from "../store.js";
import { go } from "../router.js";
import { onJobs, pollNow } from "../jobs.js";
import { h, clear, showError, toast, confirmDialog, jobLine, initials } from "../ui.js";
import { consentForm } from "./welcome.js";
import { refreshUser } from "../main.js";

export async function render(view, params) {
  const [s, st] = await Promise.all([api.get("/api/settings"), api.get("/api/status")]);
  const uid = store.userId();
  const user = uid ? await api.get(`/api/users/${uid}`).catch(() => null) : null;
  const sections = [];

  // ---------- profile & consent
  if (user) {
    const text = await api.get("/api/consent");
    const name = h("input", { type: "text", value: user.name, maxlength: 40 });
    const level = h("select", {}, [["beginner", "처음 배우는 중"], ["intermediate", "어느 정도 불러 봤어요"], ["advanced", "많이 불러 봤어요"]]
      .map(([v, l]) => h("option", { value: v, selected: user.level === v }, l)));
    const cf = await consentForm(text, { analysis: user.consent_analysis, training: user.consent_training, commercial: user.consent_commercial,
      retention_days: user.retention_days });
    sections.push(h("section", { class: "card", id: "profile" },
      h("div", { class: "row" }, h("span", { class: "avatar", style: { width: "40px", height: "40px", fontSize: "1.1rem" } }, initials(user.name)), h("h2", { style: { margin: 0 } }, "내 정보")),
      h("label", { class: "field", style: { marginTop: "12px" } }, h("span", {}, "이름"), name),
      h("label", { class: "field" }, h("span", {}, "노래 경험"), level, h("small", { class: "muted" }, "처음 배우는 중이면 목에 부담이 될 수 있는 지적(거친 소리, 높은 벨팅 등)은 하지 않아요.")),
      h("h3", {}, "동의"), cf.el,
      user.consent_at ? h("p", { class: "hint" }, `마지막으로 동의한 날: ${new Date(user.consent_at * 1000).toLocaleDateString("ko-KR")} (문구 버전 ${user.consent_version})`) : null,
      h("div", { class: "row" },
        h("button", { class: "btn primary", onclick: async () => {
          try {
            await api.patch(`/api/users/${uid}`, { name: name.value, level: level.value, consent: cf.value() });
            toast("저장했어요."); refreshUser();
          } catch (e) { showError(e); }
        } }, "저장"),
        h("button", { class: "btn danger", onclick: async () => {
          const typed = await confirmDialog("내 데이터를 모두 지울까요?",
            `${user.name}님의 녹음 ${user.n_takes}개와 분석 결과, 피드백 응답, 라벨, 검사 결과, 동의 기록이 모두 지워져요. 되돌릴 수 없어요.`,
            { ok: "모두 지우기", danger: true, input: { label: "확인을 위해 이름을 입력해 주세요", placeholder: user.name } });
          if (typed === null) return;
          try {
            await api.del(`/api/users/${uid}`, { confirm_name: typed });
            store.setUser(null); toast("모두 지웠어요."); go("#/welcome");
          } catch (e) { showError(e); }
        } }, "내 데이터 모두 지우기"))));
  }

  // ---------- model weights
  const wBox = h("div");
  function drawWeights(jobs) {
    const w = st.weights[0];
    const job = (jobs || []).find((j) => j.kind === "fetch_weights" && ["queued", "running"].includes(j.status));
    clear(wBox, h("dl", { class: "kv" },
      h("dt", {}, w.label), h("dd", {}, w.present ? h("span", { class: "badge ok" }, "받음") : h("span", { class: "badge warn" }, "아직 받지 않음")),
      h("dt", {}, "위치"), h("dd", { class: "mono" }, s.weights_dir),
      h("dt", {}, "라이선스"), h("dd", {}, w.license)),
      job ? h("div", { style: { marginTop: "10px" } }, jobLine(job, { title: false })) :
        !w.present ? h("button", { class: "btn primary", style: { marginTop: "10px" }, onclick: async () => {
          try { await api.post("/api/weights/fetch"); pollNow(); } catch (e) { showError(e); }
        } }, "받기 (약 640MB)") : null,
      h("p", { class: "hint" }, "음정 분석은 따로 모델이 필요 없어요. ",
        st.thresholds.synthetic ? "피드백에 쓰는 표시 기준은 지금 합성 데이터로 정한 임시 기준이에요." : ""));
  }
  sections.push(h("section", { class: "card" }, h("h2", {}, "모델"), wBox));

  // ---------- data folder & CPU
  const dir = h("input", { type: "text", value: s.data_dir });
  const move = h("input", { type: "checkbox", checked: true });
  const threads = h("input", { type: "number", min: 0, max: s.cpu_count || 64, value: s.threads });
  const pick = s.local ? h("button", { class: "btn small", onclick: async () => {
    try { const r = await api.post("/api/settings/pick-folder"); if (r.path) dir.value = r.path; else if (!r.available) toast("이 PC에서는 폴더 고르기 창을 열 수 없어요. 경로를 직접 입력해 주세요."); } catch (e) { showError(e); }
  } }, "폴더 고르기") : null;
  sections.push(h("section", { class: "card" }, h("h2", {}, "저장 위치와 성능"),
    h("label", { class: "field" }, h("span", {}, "데이터 폴더"), h("div", { class: "row", style: { flexWrap: "nowrap" } }, dir, pick),
      h("small", { class: "muted" }, `곡, 녹음, 분석 결과가 모두 이 폴더 하나에 저장돼요. 남은 공간 ${s.disk_free_gb}GB.`)),
    h("label", { class: "row", style: { gap: "8px", marginBottom: "12px" } }, move, "지금 데이터를 새 폴더로 옮기기 (새 폴더는 비어 있어야 해요)"),
    h("label", { class: "field" }, h("span", {}, "CPU 스레드 수"), threads,
      h("small", { class: "muted" }, `0이면 모든 코어(${s.cpu_count}개)를 써요. 숫자를 줄이면 분석이 느려지는 대신 PC가 덜 바빠요.`)),
    h("div", { class: "row" }, h("button", { class: "btn primary", onclick: async () => {
      try {
        const body = { threads: Number(threads.value) };
        if (dir.value.trim() !== s.data_dir) Object.assign(body, { data_dir: dir.value.trim(), move: move.checked });
        const r = await api.patch("/api/settings", body);
        if (r.pending_restart) restartPrompt();
        else toast("저장했어요.");
      } catch (e) { showError(e); }
    } }, "저장"))));

  // ---------- advanced
  const a = s.advanced;
  const chk = (key, label, help) => {
    const c = h("input", { type: "checkbox", checked: a[key] });
    c.addEventListener("change", () => save({ [key]: c.checked }));
    return h("label", { class: "check" }, c, h("div", {}, h("b", {}, label), h("small", {}, help)));
  };
  const num = (key, label, help, min, max, step) => {
    const i = h("input", { type: "number", min, max, step, value: a[key] });
    i.addEventListener("change", () => save({ [key]: Number(i.value) }));
    return h("label", { class: "field" }, h("span", {}, label), i, h("small", { class: "muted" }, help));
  };
  async function save(patch) {
    try { await api.patch("/api/settings", { advanced: patch }); toast("저장했어요."); } catch (e) { showError(e); }
  }
  sections.push(h("details", { class: "card adv", style: { marginTop: "14px" } }, h("summary", {}, "고급"),
    h("div", { style: { marginTop: "12px" } },
      chk("show_unverified_items", "검증 기준이 없는 항목도 보기 (실험)", "강약·꾸밈음처럼 아직 표시 기준을 맞추지 않은 차이도 '참고용'으로 보여줘요. 틀릴 수 있어요."),
      chk("audibility", "들리는 차이 순으로 정렬", "차이마다 내 녹음을 고쳐 다시 만들어 보고, 귀에 잘 들리는 것부터 보여줘요. 분석이 10초쯤 더 걸려요."),
      num("count_in_beats", "카운트인 횟수", "녹음 전에 울리는 딸깍 소리 횟수 (0–8)", 0, 8, 1),
      num("preroll_s", "앞부분 반주 길이(초)", "소절 앞에서 미리 틀어 주는 반주 길이 (0–6초)", 0, 6, 0.5),
      num("max_session_takes", "함께 비교할 녹음 수", "같은 연습에서 최근 몇 번의 녹음을 함께 보고 습관인지 판단할지 (1–10)", 1, 10, 1),
      num("session_gap_min", "연습 묶음 간격(분)", "녹음 사이가 이보다 길면 새 연습으로 봐요", 5, 240, 5))));

  sections.push(h("section", { class: "card flat" }, h("h2", {}, "정보"), h("dl", { class: "kv" },
    h("dt", {}, "버전"), h("dd", {}, st.version), h("dt", {}, "데이터 폴더"), h("dd", { class: "mono" }, st.data_dir)),
  h("div", { class: "row", style: { marginTop: "10px" } }, h("button", { class: "btn small", onclick: () => import("../tour.js").then((m) => m.startTour()) }, "안내 투어 다시 보기"))));

  clear(view, h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "설정"))), h("div", { class: "stack", style: { maxWidth: "760px" } }, sections));
  if (params && params[0] === "profile") document.getElementById("profile")?.scrollIntoView();
  drawWeights([]);
  const off = onJobs((jobs) => { api.get("/api/status").then((x) => { Object.assign(st, x); drawWeights(jobs); }).catch(() => {}); });
  return off;
}

function restartPrompt() {
  confirmDialog("다시 시작해야 적용돼요", "데이터 폴더나 CPU 설정은 앱을 다시 시작해야 적용돼요. 지금 다시 시작할까요? 진행 중인 작업은 다시 열면 이어서 해요.", { ok: "다시 시작" })
    .then(async (ok) => {
      if (!ok) return;
      try {
        const r = await api.post("/api/restart");
        if (!r.ok) { toast("앱 창을 닫았다가 다시 열어 주세요."); return; }
        toast("다시 시작하는 중이에요…");
        setTimeout(() => location.reload(), 6000);
      } catch (e) { showError(e); }
    });
}
