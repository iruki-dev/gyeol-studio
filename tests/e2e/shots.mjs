// Screenshots of app screens for a given user (no recording).  Usage:
//   BASE=… USER=<user id> SHOTS=dir node tests/e2e/shots.mjs name=#/route[@mobile][@full][@scroll=<css>] …
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE || "http://127.0.0.1:8765";
const SHOTS = process.env.SHOTS || "shots";
fs.mkdirSync(SHOTS, { recursive: true });
const browser = await chromium.launch();
for (const arg of process.argv.slice(2)) {
  const [name, spec] = arg.split("=", 2).length === 2 ? [arg.slice(0, arg.indexOf("=")), arg.slice(arg.indexOf("=") + 1)] : [arg, "#/"];
  const [route, ...flags] = spec.split("@");
  const mobile = flags.includes("mobile");
  const ctx = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1280, height: 860 }, deviceScaleFactor: mobile ? 2 : 1,
    locale: "ko-KR", isMobile: mobile, hasTouch: mobile, colorScheme: flags.includes("dark") ? "dark" : "light" });
  const store = { user: process.env.USER_ID, headphone_seen: true, latency: { wired: { ms: 80, method: "default" } }, tour_done: true };
  await ctx.addInitScript((v) => localStorage.setItem("gyeol-studio", v), JSON.stringify(store));
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.log("[pageerror]", e.message));
  await page.goto(BASE + "/" + route);
  await page.waitForTimeout(Number(process.env.WAIT || 2500));
  const scroll = flags.find((f) => f.startsWith("scroll="));
  if (scroll) await page.evaluate((sel) => document.querySelector(sel)?.scrollIntoView({ block: "start" }), scroll.slice(7));
  for (const f of flags.filter((x) => x.startsWith("click="))) { await page.click(f.slice(6)).catch((e) => console.log("click failed", e.message)); await page.waitForTimeout(1200); }
  await page.waitForTimeout(400);
  // a sticky top bar is painted mid-image in full-page captures; make it static for the capture
  if (flags.includes("full")) await page.addStyleTag({ content: ".topbar, .sidenav { position: static !important; }" });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: flags.includes("full") });
  console.log("shot", name);
  await ctx.close();
}
await browser.close();
