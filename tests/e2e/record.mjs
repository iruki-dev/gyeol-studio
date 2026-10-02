// Record one take with the virtual singer and open its feedback.  Usage:
//   BASE=… USER_ID=… AUDIO=… SHOTS=… PHRASE=<id> TAKE=gom3_take_flat.wav NOTICED=pitch,rhythm NAME=shot-name [LEAD=3.12] [MOBILE=1] node tests/e2e/record.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE || "http://127.0.0.1:8765";
const { AUDIO, SHOTS = "shots", PHRASE, TAKE, NAME = "take", USER_ID } = process.env;
const NOTICED = (process.env.NOTICED || "nothing").split(",");
const LABEL = { pitch: "음정", rhythm: "박자", dynamics: "강약", ornament: "꾸밈음", phonation: "발성", diction: "발음", nothing: "잘 모르겠어요" };
fs.mkdirSync(SHOTS, { recursive: true });
const mobile = !!process.env.MOBILE;
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const ctx = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1280, height: 900 }, deviceScaleFactor: mobile ? 2 : 1,
  locale: "ko-KR", isMobile: mobile, hasTouch: mobile });
await ctx.addInitScript({ path: path.join(here, "singer.js") });
await ctx.addInitScript((v) => localStorage.setItem("gyeol-studio", v),
  JSON.stringify({ user: USER_ID, headphone_seen: true, tour_done: true, latency: { wired: { ms: 80, method: "default" } }, ...(JSON.parse(process.env.STORE || "{}")) }));
await ctx.route("**/__test_audio/**", (r) => r.fulfill({ path: path.join(AUDIO, path.basename(new URL(r.request().url()).pathname)) }));
const page = await ctx.newPage();
page.on("pageerror", (e) => console.log("[pageerror]", e.message));
await page.goto(`${BASE}/#/phrase/${PHRASE}`);
await page.waitForSelector(".rec-btn");
await page.waitForTimeout(1500);
const lead = Number(process.env.LEAD || 3.12);
await page.evaluate(([f, l]) => { window.__singer.queue.push(`/__test_audio/${f}`); window.__singer.armed = true; window.__singer.lead = l; }, [TAKE, lead]);
await page.click(".rec-btn");
await page.waitForSelector("text=무엇이 달랐다고 느끼셨나요?", { timeout: 90000 });
await page.waitForTimeout(800);
for (const n of NOTICED) await page.click(`.chip:has-text('${LABEL[n]}')`);
await page.waitForSelector("button:has-text('피드백 보기'):not([disabled])", { timeout: 240000 });
await page.click("button:has-text('피드백 보기')");
await page.waitForSelector(".coach-main, :text('확실히 짚을 만한 차이를 찾지 못했어요')", { timeout: 30000 });
await page.waitForTimeout(2500);
const panel = await page.$(".two-col > div:last-child");
await (panel || page).screenshot({ path: path.join(SHOTS, `${NAME}.png`) });
const takeId = page.url().split("/").pop();
console.log("take", takeId);
await browser.close();
