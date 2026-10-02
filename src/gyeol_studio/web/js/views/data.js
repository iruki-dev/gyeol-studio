import { h, clear } from "../ui.js";

export async function render(view) {
  clear(view, h("div", { class: "card empty" }, h("h2", {}, "곧 열려요"), h("p", {}, "이 화면은 다음 단계에서 만들어요.")));
}

export function labelDialog() {}
