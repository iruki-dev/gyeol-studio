// Phase 4 end-to-end with real voices (VocalSet): six singers record technique pairs of the same arpeggio
// (plain ↔ breathy / belt / vocal fry) — the first one through the browser's technique mode, the rest through the same
// upload API — then a model is trained from the 학습 screen: start, stop, resume, compare, apply, a second run on
// commercially usable data only, provenance, roll back.
//   BASE=… AUDIO=… SHOTS=docs/screenshots/phase-4 node tests/e2e/phase4.mjs     (AUDIO from make_technique_material.py)
import { chromium } from "playwright";
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
async function call(method, p, { user, json, form } = {}) {
  const headers = user ? { "X-User": user } : {};
  let body;
  if (json) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  const r = await fetch(BASE + p, { method, headers, body });
  const out = await r.json();
  if (!r.ok) throw new Error(`${method} ${p}: ${JSON.stringify(out)}`);
  return out;
}
const get = (p, user) => call("GET", p, { user });
async function until(fn, timeoutS, what) {
  const t0 = Date.now();
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() - t0 > timeoutS * 1000) throw new Error(`timed out: ${what}`);
    await sleep(1000);
  }
}

const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
async function newPage(storage, viewport = { width: 1280, height: 900 }) {
  const ctx = await browser.newContext({ viewport, locale: "ko-KR" });
  await ctx.addInitScript({ path: path.join(here, "singer.js") });
  if (storage) await ctx.addInitScript((v) => { if (!localStorage.getItem("gyeol-studio")) localStorage.setItem("gyeol-studio", v); }, JSON.stringify(storage));
  await ctx.route("**/__test_audio/**", (r) => r.fulfill({ path: path.join(AUDIO, path.basename(new URL(r.request().url()).pathname)) }));
  const page = await ctx.newPage();
  page.on("pageerror", (e) => log("[pageerror]", e.message));
  return page;
}
const shot = async (page, name, opts = {}) => { await sleep(opts.wait ?? 600); if (opts.full) await page.addStyleTag({ content: ".topbar, .sidenav { position: static !important; }" }); await (opts.el ? page.locator(opts.el).first() : page).screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: !!opts.full }); log("shot", name); };

// ---------- 0. a re-run starts clean (the app's own deletes)
const NAMES = { female1: "수아", female2: "하린", female3: "도윤", female4: "서연", female5: "지호", female6: "예린" };
const COMMERCIAL = new Set(["female1", "female2", "female3"]);
let ov = await get("/api/training");
while (ov.active) ov = await call("POST", "/api/training/rollback");
for (const r of ov.runs) await call("DELETE", `/api/training/runs/${r.id}`).catch((e) => log(e.message));
for (const u of (await get("/api/users")).users.filter((x) => Object.values(NAMES).includes(x.name))) {
  await call("DELETE", `/api/users/${u.id}`, { json: { confirm_name: u.name } });
}
for (const s of (await get("/api/songs")).songs.filter((x) => x.title === "아르페지오 (VocalSet)")) await call("DELETE", `/api/songs/${s.id}`);

// ---------- 1. six testers who agreed to training (three also to commercial training)
const users = {};
for (const [singer, name] of Object.entries(NAMES)) {
  users[singer] = (await call("POST", "/api/users", { json: { name, consent: { analysis: true, training: true, commercial: COMMERCIAL.has(singer) } } })).id;
}
const owner = (await get("/api/users")).users.find((u) => u.name === "지은").id;

// ---------- 2. the song (a plain arpeggio, voice only) and its phrase
const fd = new FormData();
fd.append("title", "아르페지오 (VocalSet)");
fd.append("artist", "VocalSet female7");
fd.append("vocal_only", "true");
fd.append("file", new Blob([fs.readFileSync(path.join(AUDIO, plan.song.file))]), plan.song.file);
const song = await call("POST", "/api/songs", { user: owner, form: fd });
await until(async () => (await get(`/api/songs/${song.id}`)).status === "ready", 300, "song ready");
const LEAD_IN = 0.15, PHRASE = 6.2;
const start = plan.song.onset_s - LEAD_IN;
const phrase = await call("POST", `/api/songs/${song.id}/phrases`, { user: owner, json: { start_s: start, end_s: start + PHRASE, lyrics: "아 아 아 아 아 아 아 아 아" } });
await until(async () => (await get(`/api/phrases/${phrase.id}`)).status === "ready", 120, "phrase ready");
log("phrase ready", phrase.id);

// ---------- 3. 수아 records a breathy pair in the browser (technique mode)
const sua = users.female1;
let page = await newPage({ user: sua, headphone_seen: true, latency: { wired: { ms: 80, method: "default" } }, tour_done: true });
await page.goto(`${BASE}/#/phrase/${phrase.id}`);
await page.waitForSelector(".rec-btn");
await page.click(".seg button:has-text('기술 녹음')");
await page.click(".chip:has-text('맑은 소리 ↔ 숨섞인 소리')");
await shot(page, "01-technique-mode", { el: ".recorder" });
const first = plan.singers.female1[0];
for (const role of ["off", "on"]) {
  const take = first[role];
  // the singer starts so that the phrase lands where the app expects it (count-in + 80 ms latency)
  const lead = 3.0 + 0.08 - (take.onset_s - LEAD_IN);
  const n0 = (await get(`/api/phrases/${phrase.id}/takes`, sua)).takes.length;
  await page.evaluate(([f, l]) => { window.__singer.queue.push(`/__test_audio/${f}`); window.__singer.armed = true; window.__singer.lead = l; }, [take.file, lead]);
  await page.click(".rec-btn");
  await until(async () => (await get(`/api/phrases/${phrase.id}/takes`, sua)).takes.length > n0, 60, "take uploaded");
  await sleep(1500);
  if (role === "off") await shot(page, "02-technique-second-step", { el: ".recorder" });
}
await page.waitForSelector(".take-list .badge:has-text('기술')");
await shot(page, "03-technique-pair-saved", { el: ".two-col > div:first-child", wait: 1500 });
const browserTakes = (await get(`/api/phrases/${phrase.id}/takes`, sua)).takes;
log("browser takes", browserTakes.map((t) => [t.pair_role, JSON.stringify(t.labels)]).join(" | "));

// ---------- 4. the other pairs through the same upload the browser uses
async function upload(singer, take, pairId, role, contrast) {
  const raw = fs.readFileSync(path.join(AUDIO, take.file));
  const f = new FormData();
  f.append("file", new Blob([raw]), take.file);
  f.append("meta", JSON.stringify({ phrase_offset_s: Math.max(0, take.onset_s - LEAD_IN), kind: "technique", pair_id: pairId, pair_role: role,
    technique: { contrast }, conditions: { device: "VocalSet 녹음", earphone: "wired", place: "녹음실" } }));
  return call("POST", `/api/phrases/${phrase.id}/takes`, { user: users[singer], form: f });
}
let uploaded = browserTakes.length;
for (const [singer, pairs] of Object.entries(plan.singers)) {
  for (const [i, p] of pairs.entries()) {
    if (singer === "female1" && i === 0) continue;
    const pairId = `${singer}-${i}`;
    for (const role of ["off", "on"]) { await upload(singer, p[role], pairId, role, p.contrast); uploaded++; }
  }
}
log("uploaded takes", uploaded);

// ---------- 5. training screen
page = await newPage({ user: owner, headphone_seen: true, tour_done: true });
await page.goto(`${BASE}/#/training`);
await page.waitForSelector("text=새로 학습하기");
await shot(page, "04-training-start", { full: true });
await page.click(".seg button:has-text('상업 이용 가능만')");
await sleep(500);
await shot(page, "05-scope-commercial", { el: ".card:has(h2:text-is('새로 학습하기'))" });
await page.click(".seg button:has-text('전체')");
await page.click("button:has-text('학습 시작')");
const run1 = await until(async () => (await get("/api/training")).runs[0], 10, "run created");
await page.waitForSelector("text=진행 중인 학습");
await sleep(4000);
await shot(page, "06-preparing", { el: ".card:has(h2:has-text('진행 중인 학습'))" });
// stop once a couple of validation points are in, then resume
await until(async () => ((await get("/api/training")).runs[0].progress?.history || []).length >= 2, 1200, "validation points");
await sleep(2500);
await shot(page, "07-training-progress", { el: ".card:has(h2:has-text('진행 중인 학습'))" });
await page.click("button:has-text('멈추기')");
await until(async () => (await get("/api/training")).runs[0].status === "paused", 300, "paused");
await page.waitForSelector("button:has-text('이어서 학습')");
await shot(page, "08-paused", { el: ".card:has(h2:has-text('진행 중인 학습'))" });
const stepAtPause = (await get("/api/training")).runs[0].progress.step;
log("paused at", stepAtPause);
await page.click("button:has-text('이어서 학습')");
const done1 = await until(async () => { const r = (await get("/api/training")).runs[0]; return ["done", "failed"].includes(r.status) && r; }, 3600, "run 1 done");
if (done1.status !== "done") throw new Error(`run failed: ${JSON.stringify(done1.job)}`);
log("run 1", JSON.stringify(done1.metrics), "steps", done1.report.steps);
await page.waitForSelector("button:has-text('새 모델 적용')");
await shot(page, "09-compare-first", { el: ".card:has(h2:has-text('비교'))" });
await page.click("button:has-text('새 모델 적용')");
await page.waitForSelector("button:has-text('적용됨')");

// a second run on commercially usable data only, compared with the applied one
await page.click(".seg button:has-text('상업 이용 가능만')");
await page.click("button:has-text('학습 시작')");
const done2 = await until(async () => { const r = (await get("/api/training")).runs[0]; return r.id !== run1.id && ["done", "failed"].includes(r.status) && r; }, 3600, "run 2 done");
if (done2.status !== "done") throw new Error(`run 2 failed: ${JSON.stringify(done2.job)}`);
log("run 2", JSON.stringify(done2.metrics));
await page.reload();
await page.waitForSelector("button:has-text('새 모델 적용')");
await page.locator("details.coach-item").nth(0).locator("summary").click();
await page.locator("details.coach-item").nth(1).locator("summary").click();
await shot(page, "10-compare-and-provenance", { full: true, wait: 1000 });
await page.click("button:has-text('되돌리기')");
await sleep(800);
await shot(page, "11-rolled-back", { el: ".card:has(h2:has-text('비교'))" });

// ---------- 6. a mobile look at the training screen
page = await newPage({ user: owner, headphone_seen: true, tour_done: true }, { width: 390, height: 844 });
await page.goto(`${BASE}/#/training`);
await page.waitForSelector("text=새로 학습하기");
await shot(page, "12-mobile", { full: true });
await browser.close();
log("ok");
