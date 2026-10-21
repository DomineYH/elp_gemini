// PROTOTYPE (#140): screenshots + layout measurements of scratch/out/*.html.
// Run: NODE_PATH=<dir containing node_modules/playwright> node scratch/shoot_proto.js
const { chromium } = require("playwright");
const path = require("path");
const out = path.resolve(__dirname, "out");
const f = (n, qs = "") => "file://" + path.join(out, n) + qs;

const measure = () => {
  const r = s => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect(); return { top: +b.top.toFixed(0), bottom: +b.bottom.toFixed(0), left: +b.left.toFixed(0), right: +b.right.toFixed(0), w: +b.width.toFixed(0), h: +b.height.toFixed(0) }; };
  const seats = [...document.querySelectorAll('.seat')].map(e => e.getBoundingClientRect());
  return {
    vw: innerWidth, vh: innerHeight, scrollX: scrollX, scrollW: document.documentElement.scrollWidth,
    nav: r('nav'), main: r('main'), footer: r('footer'), tDock: r('#tDock'), tForm: r('#tDock form'),
    seatsGrid: r('#seats'), seatCount: seats.length, seatCols: new Set(seats.map(s => Math.round(s.left))).size,
    lastSeatBottom: seats.length ? Math.round(Math.max(...seats.map(s => s.bottom))) : null,
    advance: r('#advance'), stepper: r('#stepper'), stepperScrollW: document.querySelector('#stepper')?.scrollWidth,
    fab: r('#fabRow'), dm: r('#dmModal [role=dialog]'), custom: r('#customModal [role=dialog]'),
  };
};

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
  const shots = [
    ["simulation.html", "", "sim4"],
    ["simulation.html", "?n=6", "sim6"],
    ["simulation.html", "?dm=1", "sim_dm"],
    ["simulation_setup.html", "", "setup"],
    ["simulation_setup.html", "?custom=1", "setup_custom"],
  ];
  const report = {};
  for (const [w, h, tag] of [[1280, 900, "desk"], [375, 812, "mob"]]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    for (const [file, qs, name] of shots) {
      await page.goto(f(file, qs));
      await page.waitForTimeout(1200); // tailwind CDN JIT + fonts
      const top = await page.evaluate(measure);
      await page.screenshot({ path: path.join(out, `${name}_${tag}.png`) });
      await page.evaluate(() => scrollTo(0, document.body.scrollHeight));
      await page.waitForTimeout(200);
      const bottom = await page.evaluate(measure);
      if (name === "sim4" || name === "sim6") await page.screenshot({ path: path.join(out, `${name}_${tag}_bottom.png`) });
      report[`${name}_${tag}`] = { top, bottom };
    }
    await page.close();
  }
  await browser.close();
  require("fs").writeFileSync(path.join(out, "measure.json"), JSON.stringify(report, null, 1));
  console.log("done");
})();
