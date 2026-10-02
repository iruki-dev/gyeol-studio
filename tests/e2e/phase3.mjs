// Phase 3 end-to-end: start check (virtual singer sings back what it hears, a little sharp), result and key advice,
// practice history, profile switching, deleting a person's data.
//   BASE=… AUDIO=<CSD material + check clips> SHOTS=docs/screenshots/phase-3 node tests/e2e/phase3.mjs
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
const api = async (p, opts = {}) => (await fetch(BASE + p, opts)).json();

const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
async function newPage(storage, { mobile = false } = {}) {
  const ctx = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1280, height: 900 }, deviceScaleFactor: mobile ? 2 : 1,
    isMobile: mobile, hasTouch: mobile, locale: "ko-KR" });
  await ctx.addInitScript({ path: path.join(here, "singer.js") });
  if (storage) await ctx.addInitScript((v) => { if (!localStorage.getItem("gyeol-studio")) localStorage.setItem("gyeol-studio", v); }, JSON.stringify(storage));
  await ctx.route("**/__test_audio/**", (r) => r.fulfill({ path: path.join(AUDIO, path.basename(new URL(r.request().url()).pathname)) }));
  const page = await ctx.newPage();
  page.on("pageerror", (e) => log("[pageerror]", e.message));
  return page;
}
const shot = async (page, name, opts = {}) => {
  await sleep(opts.wait ?? 600);
  if (opts.full) await page.addStyleTag({ content: ".topbar { position: static !important; }" });
  await (opts.el ? page.locator(opts.el).first() : page).screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: !!opts.full });
  log("shot", name);
};

for (const u of (await api("/api/users")).users.filter((x) => x.name === "임시")) {  // a re-run starts clean
  await fetch(`${BASE}/api/users/${u.id}`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm_name: "임시" }) });
}
const users = (await api("/api/users")).users;
const jieun = users.find((u) => u.name === "지은").id;
let page = await newPage({ user: jieun, headphone_seen: true, tour_done: true });

// 1. start check
await page.goto(`${BASE}/#/check`);
await page.waitForSelector(":text('이렇게 진행해요'), :text('검사 결과')");
await page.evaluate(() => { const S = window.__singer; S.echo = true; S.echoError = 18; S.queue.push("/__test_audio/glide_up.wav", "/__test_audio/glide_down.wav", "/__test_audio/comfortable.wav"); });
if (await page.$("text=이렇게 진행해요")) { await shot(page, "01-check-intro"); await page.click("button:has-text('시작하기')"); }
else await page.click("button:has-text('다시 검사하기')"); // a re-run: the earlier result is shown first
const stageBtn = "button.btn.primary.big";
const prompts = ["낮은 음 → 높은 음", "높은 음 → 낮은 음", "편한 높이로", "따라 부르기", "두 음 따라 부르기", "짧은 가락", "구별 듣기"];
for (const [i, p] of prompts.entries()) {
  await page.waitForSelector(stageBtn, { timeout: 120000 });
  if (i === 0) await shot(page, "02-check-range");
  if (i === 3) await shot(page, "03-check-match-intro");
  await page.click(stageBtn);
  if (i === 3) { await sleep(800); await shot(page, "04-check-match", { wait: 0 }); }
  log("prompt", p);
}
// 16 listening trials: a decent listener — right for differences of 25 cents and up, a coin flip below
for (let i = 0; i < 16; i++) {
  await page.waitForSelector(`text=구별 듣기 ${i + 1}/16`, { timeout: 30000 });
  await sleep(1500);
  const t = await page.evaluate(() => window.__singer.tones.splice(0).slice(-2));
  const up = t.length === 2 && t[1].hz > t[0].hz;
  const cents = t.length === 2 ? Math.abs(1200 * Math.log2(t[1].hz / t[0].hz)) : 0;
  const answerUp = cents >= 20 ? up : Math.random() < 0.5;
  if (i === 5) await shot(page, "05-check-listen");
  await page.click(answerUp ? "button:has-text('높았어요')" : "button:has-text('낮았어요')");
}
await page.waitForSelector("text=검사 결과", { timeout: 300000 });
await shot(page, "06-check-result", { full: true });
const me = await api(`/api/users/${jieun}`);
log("profile", JSON.stringify(me.onboarding), JSON.stringify(me.voice_range));

// 2. the phrase against the measured range (key advice)
const song = (await api("/api/songs")).songs[0];
const pid = (await api(`/api/songs/${song.id}`)).phrases[0].id;
await page.goto(`${BASE}/#/phrase/${pid}`);
await page.waitForSelector(".rec-btn");
await shot(page, "07-range-advice", { wait: 1500 });

// 3. history
await page.goto(`${BASE}/#/history`);
await page.waitForSelector("text=소절별 변화");
await shot(page, "08-history", { full: true, wait: 1500 });
const m = await newPage({ user: jieun, headphone_seen: true, tour_done: true }, { mobile: true });
await m.goto(`${BASE}/#/history`);
await m.waitForSelector("text=소절별 변화");
await shot(m, "09-history-mobile", { wait: 1500 });

// 4. profiles: switch by name, my info & consent, delete a person's data
await page.click("#user-btn");
await page.waitForSelector("text=사용자 바꾸기");
await shot(page, "10-switch-user", { el: ".modal" });
await page.keyboard.press("Escape");
const temp = await api("/api/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "임시", consent: { analysis: true } }) });
page = await newPage({ user: temp.id, headphone_seen: true, tour_done: true });
await page.goto(`${BASE}/#/settings/profile`);
await page.waitForSelector("#profile");
await shot(page, "11-profile", { el: "#profile" });
await page.click("button:has-text('내 데이터 모두 지우기')");
await page.fill(".modal input", "임시");
await shot(page, "12-delete-confirm", { el: ".modal" });
await page.click(".modal button:has-text('모두 지우기')");
await page.waitForSelector("text=누가 부르나요?", { timeout: 15000 });
await shot(page, "13-after-delete");
log("users after delete", (await api("/api/users")).users.map((u) => u.name).join(","));
await browser.close();
