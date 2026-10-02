// Phone connection: QR code with the PC's https address on the same Wi-Fi, and the certificate step explained.
import { api } from "../api.js";
import { h, clear } from "../ui.js";

export async function render(view) {
  const n = await api.get("/api/network");
  const box = h("div", { class: "stack", style: { maxWidth: "820px" } });
  clear(view, h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "휴대폰으로 연결하기"),
    h("p", {}, "PC와 휴대폰이 같은 와이파이에 연결되어 있어야 해요."))), box);
  if (!window.isSecureContext && location.hostname !== "localhost") {
    box.append(h("div", { class: "notice warn" }, h("span", { class: "ico" }, "!"), "지금 주소로는 마이크를 쓸 수 없어요. 아래 QR 코드의 https 주소로 접속해 주세요."));
  }
  if (!n.enabled) {
    box.append(h("div", { class: "card" }, h("h2", {}, "휴대폰 연결이 꺼져 있어요"),
      h("p", {}, "이 PC의 네트워크 주소를 찾지 못했거나, 설정에서 휴대폰 연결을 껐어요. 와이파이에 연결한 뒤 앱을 다시 시작해 주세요.")));
    return;
  }
  // several network addresses (Wi-Fi + wired, VPN …): let the user pick the one their phone's Wi-Fi is on
  let pick = 0;
  const qr = h("div", { class: "qr", role: "img" });
  const caQr = h("div", { class: "qr", role: "img", "aria-label": "인증서 받기 QR 코드" });
  const caUrl = h("p", { class: "mono" });
  const urlLine = h("p", { class: "mono", style: { fontSize: "1.05rem", fontWeight: 700 } });
  const addrSeg = n.urls.length > 1 ? h("div", { class: "seg", style: { flexWrap: "wrap" } }) : null;
  function drawAddr() {
    qr.innerHTML = n.qr[pick].svg;
    qr.setAttribute("aria-label", `QR 코드: ${n.urls[pick]}`);
    urlLine.textContent = n.urls[pick];
    caQr.innerHTML = n.ca_qrs[pick];
    caUrl.textContent = n.ca_urls[pick];
    if (addrSeg) clear(addrSeg, n.urls.map((u, i) => h("button", { "aria-pressed": String(i === pick), onclick: () => { pick = i; drawAddr(); } }, `주소 ${i + 1}`)));
  }
  drawAddr();
  const devices = h("div", { "aria-live": "polite" });
  const ago = (s) => (s < 60 ? "방금" : s < 3600 ? `${Math.round(s / 60)}분 전` : "1시간 전");
  function drawDevices(list) {
    clear(devices, list.length
      ? h("div", { class: "notice ok" }, h("span", { class: "ico" }, "✓"), h("div", {}, h("b", {}, "연결된 기기"),
        list.map((d) => h("div", {}, `${d.kind} — ${ago(d.ago_s)}`))))
      : h("div", { class: "notice" }, h("span", { class: "ico" }, "📱"), "휴대폰에서 접속하면 여기에 표시돼요."));
  }
  drawDevices(n.devices || []);
  box.append(h("div", { class: "card" }, h("div", { class: "row", style: { alignItems: "flex-start", gap: "24px" } }, qr,
    h("div", { style: { flex: "1 1 260px" } },
      h("h2", {}, "1. 휴대폰 카메라로 QR 코드를 찍으세요"),
      h("p", {}, "또는 휴대폰 브라우저에 이 주소를 입력하세요:"),
      urlLine,
      addrSeg ? h("p", { class: "hint" }, "이 PC의 주소가 여러 개예요. QR이 안 열리면 다른 주소를 골라 보세요.") : null, addrSeg,
      h("h2", { style: { marginTop: "14px" } }, "2. '안전하지 않음' 경고가 나오면"),
      h("p", {}, "이 PC가 직접 만든 인증서라서 처음 한 번 경고가 나와요. 주소가 위와 같다면 안심하고 넘어가도 돼요."),
      h("ul", {}, h("li", {}, h("b", {}, "안드로이드(크롬): "), "'고급' → '안전하지 않음으로 이동'"), h("li", {}, h("b", {}, "아이폰(사파리): "), "'세부사항 보기' → '이 웹 사이트 방문'")),
      h("p", { class: "hint" }, "휴대폰 브라우저는 https 주소에서만 마이크를 쓸 수 있어서 이렇게 연결해요.")))),
  devices,
  h("details", { class: "card adv" }, h("summary", {}, "경고 없이 쓰려면: 인증서 설치 (선택)"),
    h("div", { class: "row", style: { alignItems: "flex-start", gap: "24px", marginTop: "12px" } },
      caQr,
      h("div", { style: { flex: "1 1 260px" } },
        h("p", {}, "이 QR 코드로 이 PC의 인증서를 받아 설치하면 다음부터 경고가 나오지 않아요."),
        caUrl,
        h("ul", {},
          h("li", {}, h("b", {}, "아이폰: "), "받은 뒤 설정 → '프로파일이 다운로드됨' → 설치, 그다음 설정 → 일반 → 정보 → 인증서 신뢰 설정에서 'gyeol studio'를 켜요."),
          h("li", {}, h("b", {}, "안드로이드: "), "설정 → 보안 → 암호화 및 사용자 인증 정보 → 인증서 설치 → CA 인증서에서 받은 파일을 골라요.")),
        h("p", { class: "hint" }, `인증서 지문(앞부분): ${n.ca_fingerprint}. 이 인증서는 이 PC에서만 만들어져 이 앱에만 쓰여요.`)))));
  const timer = setInterval(() => api.get("/api/network").then((x) => drawDevices(x.devices || [])).catch(() => {}), 3000);
  return () => clearInterval(timer);
}
