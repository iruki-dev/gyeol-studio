// A short guided tour: 곡 추가 → 소절 지정 → 녹음 → 피드백.
// Each step is a speech bubble pointing at the real control on the screen where it lives; the tour follows the user
// across screens (a step shows when its control appears) and moves on when they use that control or press "다음".
import { store } from "./store.js";
import { currentRoute } from "./router.js";
import { h, modal, toast } from "./ui.js";

const STEPS = [
  { routes: ["library"], target: "add-song", title: "곡 추가",
    text: "연습할 노래 파일(mp3·wav 등)을 올려요. 목소리와 반주는 뒤에서 알아서 나눠요. 몇 분 걸리니 그동안 다른 걸 해도 돼요." },
  { routes: ["song"], target: "phrase-wave", title: "소절 지정",
    text: "파형에서 연습할 부분을 손가락이나 마우스로 끌어서 고르고, 가사를 적은 뒤 '소절 저장'을 눌러요." },
  { routes: ["phrase", "take"], target: "record", title: "녹음",
    text: "이어폰을 끼고 누르면 딸깍 소리 뒤에 반주가 나와요. 반주에 맞춰 부르면 끝날 때 저절로 멈춰요." },
  { routes: ["phrase", "take"], target: "feedback", title: "피드백",
    text: "먼저 무엇이 달랐다고 느꼈는지 골라 보세요. 그다음 가장 중요한 한 가지와, 내 목소리로 만든 시범을 들려 드려요." },
];

let bubble = null, ring = null, scheduled = false, observer = null;
const stepNow = () => store.get("tour_step", 0);

export function maybeStartTour() {
  if (!store.get("tour_done")) startTour();
}

export function startTour() {
  const m = modal([
    h("h2", {}, "처음 쓰는 방법을 4단계로 알려 드릴게요"),
    h("ol", { class: "tour-list" }, STEPS.map((s) => h("li", {}, h("b", {}, s.title), " — ", s.text.split(".")[0] + "."))),
    h("p", { class: "hint" }, "각 화면에서 해당 버튼 옆에 말풍선이 나와요. 설정에서 언제든 다시 볼 수 있어요."),
    h("div", { class: "modal-actions" },
      h("button", { class: "btn ghost", onclick: () => { finish(false); m.close(); } }, "건너뛰기"),
      h("button", { class: "btn primary", onclick: () => { store.set("tour_step", 0); store.set("tour_on", true); store.set("tour_done", false); m.close(); watch(); } }, "시작하기")),
  ]);
}

function finish(done) {
  store.set("tour_on", false);
  store.set("tour_done", true);
  remove();
  if (observer) { observer.disconnect(); observer = null; }
  if (done) toast("안내를 마쳤어요. 설정 화면에서 다시 볼 수 있어요.");
}

function advance() {
  const next = stepNow() + 1;
  if (next >= STEPS.length) { finish(true); return; }
  store.set("tour_step", next);
  schedule();
}

function remove() {
  if (bubble) bubble.remove();
  if (ring) ring.remove();
  bubble = ring = null;
}

function schedule() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => { scheduled = false; update(); });
}

function visible(el) {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

function update() {
  if (!store.get("tour_on")) { remove(); return; }
  const route = (currentRoute() || {}).name;
  // jump ahead to the first step of this screen if the user got here another way (e.g. the song already existed)
  let i = stepNow();
  const firstHere = STEPS.findIndex((s, k) => k >= i && s.routes.includes(route));
  if (firstHere > i && !STEPS[i].routes.includes(route)) { i = firstHere; store.set("tour_step", i); }
  const step = STEPS[i];
  const el = step && step.routes.includes(route) ? document.querySelector(`[data-tour="${step.target}"]`) : null;
  if (!el || !visible(el) || document.querySelector(".modal-back")) { remove(); return; }
  if (!bubble || bubble.dataset.step !== String(i)) {
    remove();
    ring = h("div", { class: "tour-ring", "aria-hidden": "true" });
    bubble = h("div", { class: "tour-bubble", role: "dialog", "aria-label": `안내 ${i + 1}/${STEPS.length}`, "data-step": String(i) },
      h("div", { class: "tour-count" }, `${i + 1} / ${STEPS.length}`),
      h("h3", {}, step.title), h("p", {}, step.text),
      h("div", { class: "row between" },
        h("button", { class: "btn small ghost", onclick: () => finish(false) }, "안내 끝내기"),
        h("button", { class: "btn small primary", onclick: advance }, i === STEPS.length - 1 ? "다 봤어요" : "다음")));
    document.body.append(ring, bubble);
    // using the control itself also moves the tour on (the next bubble shows when its screen opens)
    el.addEventListener("click", () => { if (stepNow() === i && store.get("tour_on")) advance(); }, { once: true, capture: true });
  }
  place(el);
}

function place(el) {
  const r = el.getBoundingClientRect();
  const pad = 6;
  Object.assign(ring.style, { left: `${r.left - pad}px`, top: `${r.top - pad}px`, width: `${r.width + 2 * pad}px`, height: `${r.height + 2 * pad}px` });
  const bw = Math.min(320, window.innerWidth - 24);
  bubble.style.width = `${bw}px`;
  const bh = bubble.offsetHeight;
  const below = r.bottom + 12 + bh < window.innerHeight || r.top < bh + 24;
  const left = Math.max(12, Math.min(window.innerWidth - bw - 12, r.left + r.width / 2 - bw / 2));
  Object.assign(bubble.style, { left: `${left}px`, top: `${below ? r.bottom + 12 : r.top - bh - 12}px` });
  bubble.classList.toggle("above", !below);
}

function watch() {
  if (observer) return;
  observer = new MutationObserver(schedule);
  observer.observe(document.getElementById("view") || document.body, { childList: true, subtree: true });
  window.addEventListener("hashchange", schedule);
  window.addEventListener("resize", schedule);
  window.addEventListener("scroll", schedule, { passive: true });
  document.addEventListener("click", () => setTimeout(schedule, 50), true);
  schedule();
}

// a tour in progress continues after a reload
if (store.get("tour_on")) watch();
