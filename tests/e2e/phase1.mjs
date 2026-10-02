// Phase 1 end-to-end in Chromium: first run (model download) → register with consent → add a song → choose a phrase
// → sing along twice (virtual singer, see singer.js) → self-assessment → feedback → own-voice demo.
// Screenshots go to $SHOTS.  Usage:
//   BASE=http://127.0.0.1:8765 AUDIO=<dir with gom3_*.wav> SHOTS=docs/screenshots/phase-1 node tests/e2e/phase1.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE || "http://127.0.0.1:8765";
const AUDIO = process.env.AUDIO;
const SHOTS = process.env.SHOTS || "shots";
const [P0, P1] = fs.readFileSync(path.join(AUDIO, "gom3_phrase.txt"), "utf8").trim().split(/\s+/).map(Number);
const LYRICS = "곰 세마리가 한 집에 있어 아빠곰 엄마곰 애기곰";
fs.mkdirSync(SHOTS, { recursive: true });

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(p) {
  const r = await fetch(BASE + p);
  return r.json();
}
async function until(fn, { timeout = 600000, every = 2000, what = "" } = {}) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    const v = await fn();
    if (v) return v;
    await sleep(every);
  }
  throw new Error(`timed out: ${what}`);
}

const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });

async function newPage(viewport, { mobile = false, storage = null } = {}) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: mobile ? 2 : 1, locale: "ko-KR", isMobile: mobile, hasTouch: mobile });
  await ctx.addInitScript({ path: path.join(here, "singer.js") });
  if (storage) await ctx.addInitScript((v) => { if (!localStorage.getItem("gyeol-studio")) localStorage.setItem("gyeol-studio", v); }, JSON.stringify(storage));
  await ctx.route("**/__test_audio/**", (r) => r.fulfill({ path: path.join(AUDIO, path.basename(new URL(r.request().url()).pathname)) }));
  const page = await ctx.newPage();
  page.on("pageerror", (e) => log("[pageerror]", e.message));
  page.on("console", (m) => { if (m.type() === "error") log("[console]", m.text()); });
  return { ctx, page };
}

const shot = async (page, name, opts = {}) => {
  await sleep(opts.wait ?? 400);
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: opts.full ?? false });
  log("shot", name);
};

const { page } = await newPage({ width: 1280, height: 860 });

// 1. first visit: welcome + consent
await page.goto(BASE + "/");
await page.waitForSelector("text=처음 오셨군요");
await shot(page, "01-welcome", { full: true });
await page.fill("input[maxlength='40']", "지은");
await page.check("input[name=training]");
await page.click("text=동의하고 시작하기");
await page.waitForSelector("text=곡 보관함");
const userId = await page.evaluate(() => JSON.parse(localStorage.getItem("gyeol-studio")).user);
log("user", userId);

// 2. model download (first run)
await page.goto(BASE + "/#/setup");
await page.waitForSelector(".progress, :text('준비가 끝났어요')", { timeout: 60000 });
await shot(page, "02-setup-downloading");
await page.waitForSelector("text=준비가 끝났어요", { timeout: 600000 });
await shot(page, "03-setup-done");
await page.click("text=곡 보관함으로");

// 3. empty library → upload
await page.waitForSelector("text=아직 곡이 없어요");
await shot(page, "04-library-empty");
await page.click("text=첫 곡 추가하기");
await page.setInputFiles("input[type=file]", path.join(AUDIO, "gom3_song.wav"));
await page.fill("input[placeholder='예: 너의 의미']", "곰 세마리");
await page.fill("input[placeholder='예: 아이유']", "동요 (CSD)");
await page.fill("input[placeholder='예: C, A♭m']", "E");
await shot(page, "05-upload-dialog");
await page.click("button:has-text('올리기')");
await page.waitForSelector("text=소절 만들기");
const songId = page.url().split("/").pop();
log("song", songId);

// 4. choose the phrase by dragging on the waveform, then fine-tune the numbers
const canvas = await page.$(".wave-wrap canvas");
const box = await canvas.boundingBox();
const dur = (await api(`/api/songs/${songId}`)).duration_s;
const x = (t) => box.x + (t / dur) * box.width;
await page.mouse.move(x(P0 + 0.3), box.y + box.height / 2);
await page.mouse.down();
await page.mouse.move(x(P1 - 0.4), box.y + box.height / 2, { steps: 12 });
await page.mouse.up();
await page.fill("input[aria-label='시작(초)']", P0.toFixed(2));
await page.dispatchEvent("input[aria-label='시작(초)']", "change");
await page.fill("input[aria-label='끝(초)']", P1.toFixed(2));
await page.dispatchEvent("input[aria-label='끝(초)']", "change");
await page.fill("input[placeholder='예: 사랑해요 그대']", LYRICS);
await shot(page, "06-phrase-select");
await page.click("button:has-text('소절 저장')");
await page.waitForSelector(".phrase-item");
await shot(page, "07-song-separating", { wait: 2500 });

// 5. wait for separation + target analysis (progress visible in the library meanwhile)
await page.goto(BASE + "/#/");
await sleep(8000);
await shot(page, "08-library-progress");
const phrase = await until(async () => {
  const s = await api(`/api/songs/${songId}`);
  return s.phrases.find((p) => p.status === "ready");
}, { what: "phrase ready", every: 5000, timeout: 1800000 });
log("phrase ready", phrase.id);
await page.goto(BASE + `/#/song/${songId}`);
await shot(page, "09-song-ready", { wait: 1500 });

// 6. practice: headphone guide → latency calibration → count-in → recording
await page.goto(BASE + `/#/phrase/${phrase.id}`);
await page.waitForSelector(".rec-btn");
await shot(page, "10-practice", { wait: 1200 });
await page.evaluate(() => { window.__singer.queue.push("/__test_audio/gom3_take_v2.wav"); window.__singer.armed = true; window.__singer.lead = 3.0 + 0.13; });
await page.click(".rec-btn");
await page.waitForSelector("text=이어폰을 연결해 주세요");
await shot(page, "11-headphones");
await page.click("text=연결했어요");
await page.waitForSelector("text=소리 지연 맞추기");
await shot(page, "12-latency");
await page.click("text=건너뛰기 (기본값 사용)");
await sleep(2600);
await shot(page, "13-countin", { wait: 0 });
await sleep(3200);
await shot(page, "14-recording", { wait: 0 });

// 7. self-assessment while the analysis runs, then feedback
await page.waitForSelector("text=무엇이 달랐다고 느끼셨나요?", { timeout: 60000 });
await shot(page, "15-self-assessment");
await page.click(".chip:has-text('음정')");
await page.waitForSelector("button:has-text('피드백 보기'):not([disabled])", { timeout: 180000 });
await page.click("button:has-text('피드백 보기')");
await page.waitForSelector(".coach-main", { timeout: 30000 });
await shot(page, "16-feedback", { full: true, wait: 1500 });
await page.waitForSelector("button:has-text('듣기')", { timeout: 60000 }).catch(() => log("no demo button"));
await page.click(".coach-main button:has-text('듣기')").catch(() => {});
await sleep(1500);
await page.click(".coach-main .seg button:has-text('시범음')").catch(() => {});
await sleep(1200);
await shot(page, "17-demo-ab");
await page.click(".coach-main .respond .chip:has-text('맞아요')");
await page.click(".coach-main button:has-text('멈추기')").catch(() => {});

// 8. a second take (the same line, sung ~35 cents flat)
await page.evaluate(() => { window.__singer.queue.push("/__test_audio/gom3_take_flat.wav"); window.__singer.armed = true; window.__singer.lead = 3.0 + 0.10; });
await page.click(".rec-btn");
await page.waitForSelector("text=무엇이 달랐다고 느끼셨나요?", { timeout: 60000 });
await sleep(1000);
await page.click(".chip:has-text('음정')");
await page.click(".chip:has-text('박자')");
await page.waitForSelector("button:has-text('피드백 보기'):not([disabled])", { timeout: 180000 });
await page.click("button:has-text('피드백 보기')");
await page.waitForSelector(".coach-main");
await sleep(1500);
const sec = await page.$("details.coach-item");
if (sec) { await sec.click(); await sleep(800); }
await shot(page, "18-feedback-take2", { full: true });

// 9. phone-sized screens for the same user
const m = await newPage({ width: 390, height: 844 }, { mobile: true,
  storage: { user: userId, headphone_seen: true, latency: { wired: { ms: 80, method: "default" } } } });
await m.page.goto(BASE + "/#/");
await shot(m.page, "19-mobile-library", { wait: 1500 });
await m.page.goto(BASE + `/#/phrase/${phrase.id}`);
await m.page.waitForSelector(".rec-btn");
await shot(m.page, "20-mobile-practice", { wait: 2000 });
await m.page.evaluate(() => document.querySelector(".coach-main")?.scrollIntoView());
await shot(m.page, "21-mobile-feedback", { wait: 1500 });

const takes = await api(`/api/phrases/${phrase.id}/takes?user=${userId}`);
log("takes", JSON.stringify(takes.takes.map((t) => [t.status, t.latency_ms, t.feedback && t.feedback.primary])));
await browser.close();
