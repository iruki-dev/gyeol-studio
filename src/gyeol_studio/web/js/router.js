// Hash router: "#/song/abc" → { name: "song", params: ["abc"] }.  Views export render(el, params) and may return a cleanup function.
const routes = new Map();
let cleanup = null;
let current = null;

export function route(name, loader) {
  routes.set(name, loader);
}

export function go(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

export function currentRoute() {
  return current;
}

export async function render() {
  const parts = (location.hash.replace(/^#\/?/, "") || "").split("/").filter(Boolean).map(decodeURIComponent);
  const name = parts[0] || "library";
  const loader = routes.get(name) || routes.get("library");
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  current = { name, params: parts.slice(1) };
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name ||
    (a.dataset.nav === "library" && ["song", "phrase", "take"].includes(name))));
  const view = document.getElementById("view");
  view.replaceChildren();
  try {
    const mod = await loader();
    const r = await mod.render(view, current.params);
    if (typeof r === "function") cleanup = r;
  } catch (e) {
    console.error(e);
    view.replaceChildren();
    const msg = document.createElement("div");
    msg.className = "card";
    msg.innerHTML = "<h2>화면을 열지 못했어요</h2><p></p><button class='btn'>다시 시도</button>";
    msg.querySelector("p").textContent = e.message || "다시 시도해 주세요.";
    msg.querySelector("button").onclick = () => render();
    view.append(msg);
  }
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", render);
