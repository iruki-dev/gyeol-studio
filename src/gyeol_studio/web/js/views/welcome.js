// First screen: pick who is singing, or register a new tester with consent (one screen).
import { api } from "../api.js";
import { store } from "../store.js";
import { go } from "../router.js";
import { h, clear, modal, showError, initials, toast } from "../ui.js";

export async function consentForm(text, initial = {}) {
  const boxes = {};
  const items = text.items.map((it) => {
    const cb = h("input", { type: "checkbox", name: it.id });
    cb.checked = initial[it.id] !== undefined ? !!initial[it.id] : !!it.required;
    boxes[it.id] = cb;
    return h("label", { class: "check" }, cb, h("div", {}, h("b", {}, it.label), h("small", {}, it.text)));
  });
  // "commercial" needs "training"
  const sync = () => {
    for (const it of text.items) {
      if (it.requires && boxes[it.requires]) {
        boxes[it.id].disabled = !boxes[it.requires].checked;
        if (!boxes[it.requires].checked) boxes[it.id].checked = false;
      }
    }
  };
  Object.values(boxes).forEach((b) => b.addEventListener("change", sync));
  sync();
  const ret = h("select", { name: "retention" }, text.retention.options.map((o) => h("option", { value: o.days }, o.label)));
  ret.value = String(initial.retention_days ?? text.retention.default);
  const el = h("div", {},
    h("p", {}, text.intro),
    items,
    h("label", { class: "field" }, h("span", {}, text.retention.label), ret, h("small", { class: "muted" }, text.retention.help)),
    h("p", { class: "hint" }, text.footer));
  return {
    el,
    value: () => ({ ...Object.fromEntries(Object.entries(boxes).map(([k, b]) => [k, b.checked])), retention_days: Number(ret.value) }),
  };
}

export async function render(view) {
  const [{ users }, text] = await Promise.all([api.get("/api/users"), api.get("/api/consent")]);
  const name = h("input", { type: "text", maxlength: 40, placeholder: "예: 김결", autocomplete: "off" });
  const form = await consentForm(text);
  const submit = h("button", { class: "btn primary big", type: "submit" }, "동의하고 시작하기");
  const reg = h("form", { class: "card", onsubmit: async (e) => {
    e.preventDefault();
    const v = form.value();
    if (!name.value.trim()) { toast("이름을 입력해 주세요.", { error: true }); name.focus(); return; }
    if (!v.analysis) { toast("분석에 동의해야 녹음과 피드백을 쓸 수 있어요.", { error: true }); return; }
    submit.disabled = true;
    try {
      const u = await api.post("/api/users", { name: name.value.trim(), consent: v });
      store.setUser(u.id);
      toast(`${u.name}님, 환영해요!`);
      go("#/");
      setTimeout(() => import("../tour.js").then((m) => m.maybeStartTour()), 600);
    } catch (err) { showError(err); submit.disabled = false; }
  } },
    h("h2", {}, users.length ? "새 사용자 등록" : "처음 오셨군요! 이름을 알려 주세요"),
    h("label", { class: "field" }, h("span", {}, "이름"), name, h("small", { class: "muted" }, "한 PC를 여러 명이 쓸 때 이름으로 구분해요.")),
    h("h3", {}, text.title), form.el, submit);
  const pick = users.length ? h("div", { class: "card" }, h("h2", {}, "누가 부르나요?"),
    h("div", { class: "grid" }, users.map((u) => h("button", { class: "btn big", style: { justifyContent: "flex-start" }, onclick: () => {
      store.setUser(u.id); go("#/");
    } }, h("span", { class: "avatar" }, initials(u.name)), u.name)))) : null;
  clear(view, h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "결 스튜디오"), h("p", {}, "목표 곡의 한 소절을 따라 부르고, 무엇이 다른지 들어 보세요."))),
    h("div", { class: "stack", style: { maxWidth: "640px" } }, pick, reg));
}

export async function userSwitcher() {
  let users = [];
  try { ({ users } = await api.get("/api/users")); } catch (e) { showError(e); return; }
  const cur = store.userId();
  const m = modal([
    h("h2", {}, "사용자 바꾸기"),
    h("div", { class: "stack" }, users.map((u) => h("button", {
      class: "btn" + (u.id === cur ? " primary" : ""), style: { width: "100%", justifyContent: "flex-start" },
      onclick: () => { store.setUser(u.id); m.close(); go("#/"); toast(`${u.name}님으로 바꿨어요.`); },
    }, h("span", { class: "avatar" }, initials(u.name)), u.name, u.id === cur ? " (지금)" : ""))),
    h("div", { class: "modal-actions" },
      h("button", { class: "btn", onclick: () => { m.close(); go("#/settings/profile"); } }, "내 정보·동의"),
      h("button", { class: "btn primary", onclick: () => { m.close(); store.setUser(null); go("#/welcome"); } }, "새 사용자 등록")),
  ]);
}
