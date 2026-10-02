// Phase 5 end-to-end: a new tester follows the guided tour (곡 추가 → 소절 지정 → 녹음 → 피드백) with a real voice,
// a phone (iPhone browser emulation) opens the app over the local https address, the PC's connect screen shows it,
// and a few everyday mistakes show their Korean "what happened + what to do" messages.
//   BASE=… AUDIO=… SHOTS=docs/screenshots/phase-5 node tests/e2e/phase5.mjs   (AUDIO: make_technique_material.py output)
import { chromium, devices } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE || "http://127.0.0.1:8765";
const { AUDIO, SHOTS = "shots" } = process.env;
fs.mkdirSync(SHOTS, { recursive: true });
const plan = JSON.parse(fs.readFileSync(path.join(AUDIO, "technique_plan.json"), "utf8"));
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = async (p, init) => (await fetch(BASE + p, init)).json();
async function until(fn, timeoutS, what) {
  const t0 = Date.now();
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() - t0 > timeoutS * 1000) throw new Error(`timed out: ${what}`);
    await sleep(1000);
  }
}
const shot = async (page, name, opts = {}) => { await sleep(opts.wait ?? 700); if (opts.full) await page.addStyleTag({ content: ".topbar, .sidenav { position: static !important; }" }); await (opts.el ? page.locator(opts.el).first() : page).screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: !!opts.full }); log("shot", name); };

const NAME = "하은";
for (const u of (await api("/api/users")).users.filter((x) => x.name === NAME)) {
  await fetch(`${BASE}/api/users/${u.id}`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm_name: NAME }) });
}
for (const s of (await api("/api/songs")).songs.filter((x) => x.title === "아르페지오 연습")) await fetch(`${BASE}/api/songs/${s.id}`, { method: "DELETE" });

// direct connections: the phone step opens the PC's LAN https address, which a system proxy must not intercept
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required", "--no-proxy-server"] });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, locale: "ko-KR" });
await ctx.addInitScript({ path: path.join(here, "singer.js") });
await ctx.addInitScript((v) => { if (!localStorage.getItem("gyeol-studio")) localStorage.setItem("gyeol-studio", v); },
  JSON.stringify({ headphone_seen: true, latency: { wired: { ms: 80, method: "default" } } }));
await ctx.route("**/__test_audio/**", (r) => r.fulfill({ path: path.join(AUDIO, path.basename(new URL(r.request().url()).pathname)) }));
const page = await ctx.newPage();
page.on("pageerror", (e) => log("[pageerror]", e.message));

// ---------- 1. register → the tour offers itself
await page.goto(BASE + "/#/welcome");
await page.waitForSelector("text=새 사용자 등록");
await page.fill("input[maxlength='40']", NAME);
await page.check("input[name=training]");
await page.click("text=동의하고 시작하기");
await page.waitForSelector("text=처음 쓰는 방법을 4단계로");
await shot(page, "01-tour-intro");
await page.click(".modal button:has-text('시작하기')");
await page.waitForSelector(".tour-bubble:has-text('곡 추가')");
await shot(page, "02-tour-add-song");

// ---------- 2. 곡 추가 (the tour moves on when the button is used)
await page.click("[data-tour='add-song']");
await page.setInputFiles("input[type=file]", path.join(AUDIO, plan.song.file));
await page.fill("input[placeholder='예: 너의 의미']", "아르페지오 연습");
await page.click(".modal details.adv summary");
await page.click("label:has-text('목소리만 있는 파일이에요')");
await page.click("button:has-text('올리기')");
await page.waitForSelector("text=소절 만들기");
const songId = page.url().split("/").pop();
await page.waitForSelector(".tour-bubble:has-text('소절 지정')");
await shot(page, "03-tour-phrase");

// ---------- 3. 소절 지정: drag on the waveform
const LEAD_IN = 0.12;
const start = plan.song.onset_s - LEAD_IN, end = start + 6.2;
const canvas = await page.$(".wave-wrap canvas");
const box = await canvas.boundingBox();
const dur = (await api(`/api/songs/${songId}`)).duration_s;
const x = (t) => box.x + (t / dur) * box.width;
await page.mouse.move(x(start), box.y + box.height / 2);
await page.mouse.down();
await page.mouse.move(x(end), box.y + box.height / 2, { steps: 12 });
await page.mouse.up();
await page.fill("input[placeholder='예: 사랑해요 그대']", "아 아 아 아 아 아 아 아 아");
await page.click("button:has-text('소절 저장')");
const phrase = await until(async () => (await api(`/api/songs/${songId}`)).phrases.find((p) => p.status === "ready"), 300, "phrase ready");
log("phrase", phrase.id);

// ---------- 4. 녹음 → 피드백
await page.goto(`${BASE}/#/phrase/${phrase.id}`);
await page.waitForSelector(".tour-bubble:has-text('녹음')");
await shot(page, "04-tour-record");
const take = plan.singers.female2[0].off;
await page.evaluate(([f, l]) => { window.__singer.queue.push(`/__test_audio/${f}`); window.__singer.armed = true; window.__singer.lead = l; },
  [take.file, 3.0 + 0.08 - (take.onset_s - LEAD_IN)]);
await page.click(".rec-btn");
await page.waitForSelector(".tour-bubble:has-text('피드백')", { timeout: 90000 });
await shot(page, "05-tour-feedback");
await page.click(".tour-bubble button:has-text('다 봤어요')");
await sleep(400);
await shot(page, "06-tour-done");
await page.click(".coach-panel .chip >> nth=0").catch(() => page.locator("[data-tour='feedback'] .chip").first().click());
await page.waitForSelector("button:has-text('피드백 보기'):not([disabled])", { timeout: 240000 });

// ---------- 5. everyday mistakes, in Korean
await page.click(".rec-btn");
await sleep(1500);
await page.click(".rec-btn"); // stopped during the count-in
await page.waitForSelector(".toast:has-text('끝까지 불러 주세요')", { timeout: 15000 });
await shot(page, "07-error-stopped-early", { wait: 200 });
await page.goto(`${BASE}/#/`);
await page.click("[data-tour='add-song']");
const bogus = path.join(SHOTS, "not-audio.mp3");
fs.writeFileSync(bogus, "this is not audio");
await page.setInputFiles("input[type=file]", bogus);
await page.click("button:has-text('올리기')");
await page.waitForSelector(".toast.err", { timeout: 15000 });
await shot(page, "08-error-bad-file", { wait: 300 });
fs.unlinkSync(bogus);
await page.click(".modal button:has-text('취소')");

// ---------- 6. a phone on the same Wi-Fi
await page.goto(`${BASE}/#/connect`);
await page.waitForSelector("text=휴대폰 카메라로 QR 코드를 찍으세요");
await shot(page, "09-connect", { full: true });
const net = await api("/api/network");
const phoneCtx = await browser.newContext({ ...devices["iPhone 13"], locale: "ko-KR", ignoreHTTPSErrors: true });
// this sandbox resets the browser's own TLS connections to non-loopback addresses, so the phone's requests are
// re-sent by Playwright (same URL, headers and user-agent; the server sees a LAN client) — a test-harness detail only
if (process.env.PHONE_VIA_ROUTE !== "0") await phoneCtx.route(`${net.urls[0]}**`, async (r) => r.fulfill({ response: await r.fetch() }));
const phone = await phoneCtx.newPage();
await phone.goto(net.urls[0]);
await phone.waitForSelector("text=누가 부르나요?");
await shot(phone, "10-phone-welcome");
await phone.click(`.btn:has-text('${NAME}')`);
await phone.waitForSelector("text=곡 보관함");
await phone.goto(`${net.urls[0]}#/phrase/${phrase.id}`);
await phone.waitForSelector(".rec-btn");
await shot(phone, "11-phone-practice", { full: true });
await page.waitForSelector(".notice.ok:has-text('연결된 기기')", { timeout: 15000 });
await shot(page, "12-connect-device", { el: ".notice.ok" });
await browser.close();
log("ok");
