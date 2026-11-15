/* Verify release consistency and a manual 6-point loop in both modes. No Gemini calls. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const base = process.env.GEMINI_TEST_URL || 'https://bezna.xyz';
const origin = new URL(base).origin;
const points = [[45.7526,21.2250],[45.7599,21.2240],[45.7600,21.2300],[45.7563,21.2312],[45.7503,21.2310],[45.7486,21.2280]];
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 430, height: 932 }, reducedMotion: 'reduce' });
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', r => new URL(r.request().url()).origin === origin ? r.continue() : r.abort());
    const response = await page.goto(base + '/m/?lang=ru');
    const healthResponse = await page.request.get(base + '/api/health');
    const health = await healthResponse.json();
    assert.equal(health.ask_version, 4);
    assert.equal(healthResponse.headers()['cache-control'], 'no-store');
    assert.equal(response.headers()['cache-control'], 'no-cache');
    assert.equal(response.headers()['x-bezna-ui-version'], health.ui_version);
    const scripts = await page.locator('script[src]').evaluateAll(nodes => nodes.map(n => n.src));
    assert.ok(scripts.length >= 6);
    for (const script of scripts) assert.equal(new URL(script).searchParams.get('v'), health.ui_version);
    await page.locator('[data-act="loop"]').click();
    await page.evaluate(points => { for (const p of points) map.fire('click', { latlng: L.latLng(p) }); }, points);
    for (const mode of ['walk', 'bike']) {
      if (mode === 'bike') { await page.evaluate(() => go('home', false)); await page.locator('[data-act="mode"][data-mode="bike"]').click(); }
      const done = page.waitForResponse(r => new URL(r.url()).pathname === '/api/loop');
      await page.locator('[data-act="loopGo"]').click();
      const answer = await done;
      assert.equal(answer.status(), 200, JSON.stringify(await answer.json()));
      await page.waitForFunction(mode => plan && plan.loop && plan.mode === mode && document.querySelector('#screen .rcard'), mode);
      const result = await page.evaluate(() => plan);
      assert.equal(result.points.length, 6);
      for (const route of Object.values(result.routes)) {
        const coords = route.geometry.features.flatMap(f => f.geometry.coordinates);
        assert.ok(route.length_m > 0);
        assert.deepEqual(coords[0], coords.at(-1));
      }
      console.log(JSON.stringify({ mode, points: 6, status: answer.status(), meters: result.routes.fastest.length_m, closed: true }));
    }
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'PASS', ui_version: health.ui_version, ask_version: health.ask_version }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
