// Phase 2 end-to-end: a second tester (training + commercial consent) records with conditions; labelling with a few taps
// (data screen and from the coaching panel); feedback responses; evaluation and training exports.
//   BASE=… AUDIO=… SHOTS=docs/screenshots/phase-2 node tests/e2e/phase2.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE || "http://127.0.0.1:8765";
const { AUDIO, SHOTS = "shots" } = process.env;
fs.mkdirSync(SHOTS, { recursive: true });
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = async (p, user) => (await fetch(BASE + p, { headers: user ? { "X-User": user } : {} })).json();

const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
async function newPage(storage) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "ko-KR" });
  await ctx.addInitScript({ path: path.join(here, "singer.js") });
  if (storage) await ctx.addInitScript((v) => { if (!localStorage.getItem("gyeol-studio")) localStorage.setItem("gyeol-studio", v); }, JSON.stringify(storage));
  await ctx.route("**/__test_audio/**", (r) => r.fulfill({ path: path.join(AUDIO, path.basename(new URL(r.request().url()).pathname)) }));
  const page = await ctx.newPage();
  page.on("pageerror", (e) => log("[pageerror]", e.message));
  return page;
}
const shot = async (page, name, opts = {}) => { await sleep(opts.wait ?? 600); await (opts.el ? page.locator(opts.el).first() : page).screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: !!opts.full }); log("shot", name); };

// a re-run starts clean: remove the second tester if an earlier run created them (the app's own delete)
for (const u of (await api("/api/users")).users.filter((x) => x.name === "민준")) {
  await fetch(`${BASE}/api/users/${u.id}`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm_name: "민준" }) });
}

// 1. a second tester registers
let page = await newPage({ headphone_seen: true, latency: { wired: { ms: 80, method: "default" } }, tour_done: true });
await page.goto(BASE + "/#/welcome");
await page.waitForSelector("text=새 사용자 등록");
await shot(page, "01-pick-or-register");
await page.fill("input[maxlength='40']", "민준");
await page.check("input[name=training]");
await page.check("input[name=commercial]");
await page.selectOption("select[name=retention]", "1095");
await page.click("text=동의하고 시작하기");
await page.waitForSelector("text=곡 보관함");
const minjun = await page.evaluate(() => JSON.parse(localStorage.getItem("gyeol-studio")).user);
const firstSong = (await api("/api/songs")).songs[0];
const song = await api(`/api/songs/${firstSong.id}`);
const pid = song.phrases[0].id;

// 2. recording conditions (kept for the next takes), then two takes
await page.goto(`${BASE}/#/phrase/${pid}`);
await page.waitForSelector(".rec-btn");
await page.click("button:has-text('녹음 조건')");
await page.fill("input[placeholder^='예: 갤럭시']", "아이폰 15");
await page.fill("input[placeholder^='예: 집 방']", "연습실");
await shot(page, "02-conditions");
await page.click(".modal button:has-text('저장')");
await page.click(".seg button:has-text('블루투스')");
await page.evaluate(() => { const s = JSON.parse(localStorage.getItem("gyeol-studio")); s.latency.bluetooth = { ms: 220, method: "loopback" }; localStorage.setItem("gyeol-studio", JSON.stringify(s)); });
await page.reload();
await page.waitForSelector(".rec-btn");
await shot(page, "03-conditions-kept", { el: ".recorder" });
for (const [file, lead] of [["gom3_take_v2.wav", 3.24], ["gom3_take_flat.wav", 3.26]]) {
  await page.evaluate(([f, l]) => { window.__singer.queue.push(`/__test_audio/${f}`); window.__singer.armed = true; window.__singer.lead = l; }, [file, lead]);
  await page.click(".rec-btn");
  await page.waitForSelector("text=무엇이 달랐다고 느끼셨나요?", { timeout: 90000 });
  await sleep(500);
  await page.click(".chip:has-text('음정')");
  await page.waitForSelector("button:has-text('피드백 보기'):not([disabled])", { timeout: 240000 });
  await page.click("button:has-text('피드백 보기')");
  await page.waitForSelector(".coach-main");
  await sleep(800);
  await page.click(".coach-main .respond .chip:has-text('맞아요')");
  const det = await page.$("details.coach-item");
  if (det) { await det.click(); await sleep(600); await page.locator("details.coach-item[open] .respond .chip:has-text('아닌 것 같아요')").first().click().catch(() => {}); }
}
await shot(page, "04-responses", { el: ".two-col > div:last-child", wait: 1200 });

// 3. label from the coaching panel
await page.click("button:has-text('이 녹음에 라벨 붙이기')");
await page.waitForSelector(".modal h2:has-text('라벨 붙이기')");
await page.click(".modal .chip:has-text('흉성')");
await sleep(300);
await page.click(".modal .chip:has-text('숨섞임')");
await sleep(300);
await page.click(".modal .chip:has-text('맞음')");
await sleep(500);
await shot(page, "05-label-dialog", { el: ".modal" });
await page.click(".modal button:has-text('다 됐어요')");

// 4. data screen as 지은 (all people's recordings, unlabeled first)
const users = (await api("/api/users")).users;
const jieun = users.find((u) => u.name === "지은").id;
page = await newPage({ user: jieun, headphone_seen: true, tour_done: true });
await page.goto(`${BASE}/#/data`);
await page.waitForSelector("text=라벨 붙이기");
await page.click(".seg button:has-text('모든 사람')");
await sleep(1200);
await shot(page, "06-label-queue");
const cards = page.locator(".stack > .card");
const n = Math.min(await cards.count(), 4);
const plan = [["가성", "숨섞임", "맞음"], ["믹스", "트왱", "틀림"], ["흉성", "해당 없음", "맞음"], ["흉성", "압착·벨팅", "맞음"]];
for (let i = 0; i < n; i++) {
  const c = cards.nth(i);
  for (const label of plan[i]) { await c.locator(`.chip:has-text('${label}')`).first().click(); await sleep(250); }
  await sleep(300);
}
await page.click("label:has-text('라벨 없는 것만') input");
await sleep(1200);
await shot(page, "07-labeled", { full: true });

// 5. exports
await page.goto(`${BASE}/#/data/export`);
await page.waitForSelector("text=평가용");
await shot(page, "08-export-before");
await page.locator(".card:has(h2:text-is('평가용')) button:has-text('내보내기')").click();
await sleep(500);
await page.locator(".card:has(h2:text-is('학습용')) button:has-text('내보내기')").click();
await page.waitForFunction(() => document.querySelectorAll("table.simple tr").length >= 3, null, { timeout: 120000 });
await sleep(1500);
await shot(page, "09-export-done", { full: true });
await page.goto(`${BASE}/#/data/responses`);
await shot(page, "10-responses-summary", { wait: 1500 });
const ex = await api("/api/exports");
log("exports", JSON.stringify(ex.exports.map((e) => [e.kind, e.scope, e.takes, e.n_users, e.dir])));
log("minjun", minjun);
await browser.close();
