// Records the 올팍 나우 demo video from the live site: a browser-looking frame, a moving cursor, short captions.
// Usage (from tools/): npm install && node record_demo.js [out.mp4]
// Chrome path: CHROME env var, default is the macOS install. SHOW_DAY must fall inside the live 7-day forecast.
const puppeteer = require("puppeteer-core");
const ffmpeg = require("ffmpeg-static");
const fs = require("fs"), path = require("path"), { execFileSync } = require("child_process");

const SITE = "https://lhwlhw0829-cmd.github.io/olpark-now/";
const SHOW_DAY = process.env.SHOW_DAY || "2026-11-28";
const W = 1280, H = 720, BAR = 76;            // browser chrome height
const TMP = path.join(__dirname, "frames");
const OUT = path.resolve(process.argv[2] || path.join(__dirname, "olpark-demo.mp4"));
fs.rmSync(TMP, { recursive: true, force: true }); fs.mkdirSync(TMP);
const wait = ms => new Promise(r => setTimeout(r, ms));
const sleep = ms => new Promise(r => setTimeout(r, ms + Math.random() * 250));   // small jitter, like a person
let page, site, frames = [], recording = true;

const SHELL = (gh) => `<!doctype html><html><head><meta charset="utf-8"><style>
  body{margin:0;width:${W}px;height:${H}px;overflow:hidden;background:#dfe1e5;font-family:-apple-system,'Apple SD Gothic Neo',sans-serif}
  .tabs{height:38px;display:flex;align-items:flex-end;padding-left:78px;position:relative}
  .dots{position:absolute;left:14px;top:13px;display:flex;gap:8px}.dots i{width:12px;height:12px;border-radius:50%;display:block}
  .tab{height:30px;width:230px;background:#fff;border-radius:9px 9px 0 0;display:flex;align-items:center;gap:8px;padding:0 12px;font-size:12px;color:#202124;box-sizing:border-box}
  .tab b{width:14px;height:14px;border-radius:3px;background:#2f5d8a;display:inline-block}
  .bar{height:38px;background:#fff;display:flex;align-items:center;gap:14px;padding:0 14px;box-sizing:border-box;border-bottom:1px solid #dadce0}
  .nav{color:#5f6368;font-size:15px;letter-spacing:10px}
  .url{flex:1;height:28px;border-radius:14px;background:#f1f3f4;display:flex;align-items:center;padding:0 14px;font-size:13px;color:#202124}
  .url span{color:#5f6368}
  #view{position:absolute;left:0;top:${BAR}px;width:${W}px;height:${H - BAR}px;border:0;background:#f7f7f5}
  #img{position:absolute;left:0;top:${BAR}px;width:${W}px;height:${H - BAR}px;object-fit:cover;object-position:top;display:none}
  #cur{position:absolute;left:640px;top:400px;width:22px;height:22px;z-index:10;pointer-events:none;transition:none}
  #ring{position:absolute;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:2px solid rgba(47,93,138,.7);z-index:9;opacity:0;pointer-events:none}
  #cap{position:absolute;left:50%;bottom:26px;transform:translateX(-50%);max-width:80%;padding:7px 16px;border-radius:6px;
       background:rgba(255,255,255,.94);color:#1d1d1b;font-size:19px;font-weight:600;box-shadow:0 1px 6px rgba(0,0,0,.18);
       z-index:8;text-align:center;word-break:keep-all;display:none}
  #card{position:absolute;inset:0;background:#f7f7f5;z-index:20;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px}
  #card h1{margin:0;font-size:44px;color:#1d1d1b}#card p{margin:0;font-size:18px;color:#6b6b66}
</style></head><body>
  <div class="tabs"><div class="dots"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i></div>
    <div class="tab"><b></b><span id="title">올팍 나우 · OlPark Now</span></div></div>
  <div class="bar"><span class="nav">‹ › ↻</span><div class="url" id="url"><span>https://</span>lhwlhw0829-cmd.github.io/olpark-now/</div></div>
  <iframe id="view" allow="clipboard-write"></iframe><img id="img" src="${gh}">
  <div id="ring"></div>
  <svg id="cur" viewBox="0 0 24 24"><path d="M3 2l7.5 19 2.3-7.7L20.5 11z" fill="#111" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>
  <div id="cap"></div>
  <div id="card"><h1>올팍 나우</h1><p>올림픽공원 주차 혼잡 예보</p></div>
</body></html>`;

// ---- helpers -------------------------------------------------------------
const cap = t => page.evaluate(t => { const c = document.getElementById("cap"); c.textContent = t; c.style.display = t ? "block" : "none"; }, t);
const card = (on, h, p) => page.evaluate((on, h, p) => { const c = document.getElementById("card"); c.style.display = on ? "flex" : "none";
  if (h) c.querySelector("h1").textContent = h; if (p) c.querySelector("p").textContent = p; }, on, h, p);
async function moveTo(x, y, ms = 700) {               // eased cursor glide
  await page.evaluate((x, y, ms) => new Promise(res => {
    const c = document.getElementById("cur"), x0 = parseFloat(c.style.left) || 640, y0 = parseFloat(c.style.top) || 400, t0 = performance.now();
    const step = now => { const k = Math.min(1, (now - t0) / ms), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      c.style.left = (x0 + (x - x0) * e) + "px"; c.style.top = (y0 + (y - y0) * e) + "px"; k < 1 ? requestAnimationFrame(step) : res(); };
    requestAnimationFrame(step); }), x, y, ms);
}
async function pulse() {
  await page.evaluate(() => { const c = document.getElementById("cur"), r = document.getElementById("ring");
    r.style.left = (parseFloat(c.style.left) + 4) + "px"; r.style.top = (parseFloat(c.style.top) + 4) + "px";
    r.animate([{ opacity: .9, transform: "scale(.5)" }, { opacity: 0, transform: "scale(1.3)" }], { duration: 450 }); });
}
async function rectOf(sel, i = 0) {                    // element centre in shell coordinates
  const r = await site.evaluate((s, i) => { const b = document.querySelectorAll(s)[i].getBoundingClientRect(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; }, sel, i);
  return { x: r.x, y: r.y + BAR };
}
async function point(sel, i = 0) { const p = await rectOf(sel, i); await moveTo(p.x - 2, p.y - 2); await sleep(200); await pulse(); }
async function click(sel, i = 0) {
  await point(sel, i); await site.evaluate((s, i) => document.querySelectorAll(s)[i].click(), sel, i); await sleep(350);
}
const scroll = (y) => site.evaluate(y => window.scrollTo({ top: y, behavior: "smooth" }), y).then(() => sleep(1100));
const scrollToEl = (sel, off = 90) => site.evaluate((s, o) => window.scrollTo({ top: document.querySelector(s).getBoundingClientRect().top + scrollY - o, behavior: "smooth" }), sel, off).then(() => sleep(1100));

async function grabLoop() {
  const t0 = Date.now();
  while (recording) {
    const t = Date.now() - t0, f = path.join(TMP, `${String(frames.length).padStart(5, "0")}.jpg`);
    try { await page.screenshot({ path: f, type: "jpeg", quality: 88, captureBeyondViewport: false, optimizeForSpeed: true }); frames.push({ f, t }); } catch (e) {}
    await wait(Math.max(0, 70 - (Date.now() - t0 - t)));
  }
}

(async () => {
  const browser = await puppeteer.launch({ executablePath: process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    headless: "new", args: [`--window-size=${W},${H}`, "--hide-scrollbars", "--lang=ko-KR"] });
  await browser.defaultBrowserContext().overridePermissions(new URL(SITE).origin, ["clipboard-read", "clipboard-write"]);

  // GitHub can't be framed: take a real screenshot of the Actions page first and show it inside the frame later
  const gp = await browser.newPage(); await gp.setViewport({ width: W, height: H - BAR });
  await gp.goto("https://github.com/lhwlhw0829-cmd/olpark-now/actions", { waitUntil: "networkidle2" });
  const gh = "data:image/png;base64," + (await gp.screenshot({ encoding: "base64" })); await gp.close();

  page = await browser.newPage(); await page.setViewport({ width: W, height: H });
  const cdp = await page.createCDPSession(); await cdp.send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: TMP });
  await page.evaluateOnNewDocument(() => { try { delete Navigator.prototype.share; } catch (e) {} });
  await page.setContent(SHELL(gh), { waitUntil: "load" });
  await page.evaluate(u => { document.getElementById("view").src = u; }, SITE);
  await sleep(2500);
  site = page.frames().find(f => f.url().startsWith(SITE));
  await site.waitForFunction(() => typeof F !== "undefined" && document.querySelector(".grid .c"));
  const loop = grabLoop();

  // title card
  await sleep(1800); await card(false); await sleep(900);
  // 1. overview
  await moveTo(520, 380, 900);
  await cap("일주일 동안의 주차 혼잡을 시간대별로 보여 줍니다"); await sleep(1200);
  await scrollToEl("h2", 40); await moveTo(700, 330, 900); await sleep(2600);
  // 2. pick the show day
  const row = await site.evaluate(d => [...document.querySelectorAll(".grid .d")].findIndex(e => F.days[+e.dataset.i]?.date === d), SHOW_DAY);
  await cap("공연이 있는 날(●)을 눌러 봅니다"); await sleep(900);
  await click(".grid .d", row);
  await sleep(600); await scrollToEl("#dayTitle", 20);
  await cap("11월 28일 조용필 콘서트 날, 오후 2~4시는 만차 예상"); await moveTo(430, 420, 900); await sleep(2600);
  await moveTo(860, 300, 800); await cap("오후 5시 도착을 추천하고, 붐비면 지하철을 안내합니다"); await sleep(3200);
  // 3. shows
  await scrollToEl("#showsWrap", 30); await moveTo(640, 330, 800);
  await cap("공연 일정은 올림픽공원 홈페이지에서 매일 자동으로 가져옵니다"); await sleep(3400);
  // 4. calendar + share
  await scrollToEl("#dayTitle", 20);
  await cap("추천 시간을 캘린더에 넣거나"); await click("#ics"); await sleep(1300);
  await cap("링크로 같이 가는 사람에게 보낼 수 있습니다"); await click("#share"); await sleep(2200);
  // 5. languages
  await scroll(0); await cap("영어·일본어·중국어도 지원합니다");
  for (const l of ["en", "ja", "zh"]) {
    await point("#lang");
    await site.evaluate(l => { const s = document.getElementById("lang"); s.value = l; s.dispatchEvent(new Event("change")); }, l);
    await sleep(1500);
  }
  await site.evaluate(() => { const s = document.getElementById("lang"); s.value = "ko"; s.dispatchEvent(new Event("change")); });
  await cap(""); await sleep(500);
  // 6. operators
  await click('[data-tab="ops"]'); await cap("운영자 화면에서는 임시주차장이 필요한 날을 미리 볼 수 있습니다");
  await sleep(800); await scrollToEl("#opsTable", 120); await moveTo(1000, 400, 900); await sleep(3200);
  // 7. evidence
  await scroll(0); await click('[data-tab="data"]');
  await cap("공연 있는 평일 밤에는 주차가 91% 늘어납니다"); await sleep(700);
  await scrollToEl("#profileChart", 110); await moveTo(1000, 330, 1000); await sleep(3000);
  await scrollToEl("#acc", 160); await moveTo(900, 300, 800);
  await cap("예측 오차는 평균 306대로, 지난주 같은 시간 기준(350대)보다 정확합니다"); await sleep(3400);
  // 8. automation (real GitHub Actions screenshot inside the frame)
  await cap(""); await page.evaluate(() => {
    document.getElementById("view").style.display = "none"; document.getElementById("img").style.display = "block";
    document.getElementById("url").innerHTML = "<span>https://</span>github.com/lhwlhw0829-cmd/olpark-now/actions";
    document.getElementById("title").textContent = "Actions · olpark-now"; });
  await moveTo(560, 330, 900); await cap("매일 아침 6시에 공연 일정과 예보가 자동으로 갱신됩니다"); await sleep(3600);
  // end card
  await cap(""); await card(true, "올팍 나우", "lhwlhw0829-cmd.github.io/olpark-now"); await sleep(2800);

  recording = false; await loop; await browser.close();
  const list = frames.map((fr, i) => `file '${fr.f}'\nduration ${(((frames[i + 1]?.t ?? fr.t + 70) - fr.t) / 1000).toFixed(3)}`).join("\n") + `\nfile '${frames.at(-1).f}'\n`;
  fs.writeFileSync(path.join(TMP, "list.txt"), list);
  execFileSync(ffmpeg, ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", path.join(TMP, "list.txt"),
    "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-movflags", "+faststart", OUT]);
  console.log(`${frames.length} frames, ${(frames.at(-1).t / 1000).toFixed(1)}s → ${OUT}`);
})().catch(e => { console.error(e); process.exit(1); });
