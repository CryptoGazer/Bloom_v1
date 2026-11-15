/* Manual live check: uses the backend's real Gemini key and actual routing, consumes API quota.
   Run a fresh backend on 8019, then: node scripts/testing/check_gemini_routes_live.cjs
   Requires Playwright and installed Chrome; no production changes. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const ui = require('./gemini_ui_driver.cjs');
const base = process.env.GEMINI_TEST_URL || 'http://127.0.0.1:8019';
const origin = new URL(base).origin;
const cases = [
  { name: 'direct', text: 'От C12 до Piața Victoriei пешком',
    from: { name: 'Căminul C12 UVT', lat: 45.749852, lon: 21.240281 },
    to: { name: 'Piața Victoriei', lat: 45.753113, lon: 21.2257 } },
  { name: 'clarification', text: 'Сделай мне маршрут от больницы клиник Пьячерата до Ботанического парка',
    from: { name: 'Spitalul Clinic Căi Ferate', lat: 45.749327, lon: 21.218488 },
    to: { name: 'Parcul Botanic', lat: 45.760166, lon: 21.224805 } },
];
const point = p => `${p.lat.toFixed(5)},${p.lon.toFixed(5)}`;

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    for (const mobile of [false, true]) {
      const page = await browser.newPage({ viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
      const errors = [];
      let askRequests = 0;
      page.on('pageerror', e => errors.push(e.message));
      page.on('request', r => { if (new URL(r.url()).pathname === '/api/ask') askRequests++; });
      // Gemini and routing requests pass unchanged to the backend. Only external tile/font resources are blocked.
      await page.route('**/*', intercepted => new URL(intercepted.request().url()).origin === origin ? intercepted.continue() : intercepted.abort());
      await page.goto(base + (mobile ? '/m/' : '/') + '?lang=ru');
      for (const c of cases) {
        await ui.open(page, mobile);
        await page.locator(ui.input(mobile)).fill(c.text);
        const ask = page.waitForResponse(r => new URL(r.url()).pathname === '/api/ask', { timeout: 120000 });
        const routed = page.waitForResponse(r => {
          const url = new URL(r.url());
          return url.pathname === '/api/route' && url.searchParams.get('from') === point(c.from) && url.searchParams.get('to') === point(c.to);
        }, { timeout: 120000 });
        const before = askRequests;
        await page.locator('#ask-go').click();
        const answer = await ask;
        assert.equal(answer.status(), 200);
        const body = await answer.json();
        await ui.settled(page, mobile);
        assert.ok(['route', 'clarify'].includes(body.kind), JSON.stringify(body));
        console.log(JSON.stringify({ stage: 'Gemini', view: mobile ? 'mobile' : 'desktop', case: c.name, kind: body.kind }));
        if (body.kind === 'clarify') {
          for (const side of ['from', 'to']) {
            if (body.missing.includes(side) || body.ambiguity.includes(side)) {
              assert.ok(body.candidates[side].some(p => p.name === c[side].name), JSON.stringify(body));
              await page.locator('#ask-choices button').filter({ hasText: c[side].name }).click();
            }
          }
        }
        const response = await routed;
        assert.equal(response.status(), 200);
        const result = await response.json();
        for (const route of Object.values(result.routes)) {
          assert.ok(route.geometry.features.length && route.length_m > 0 && route.minutes > 0);
          assert.ok(route.geometry.features.every(f => f.geometry.coordinates.length >= 2));
        }
        await page.waitForFunction(isMobile => {
          if (!plan) return false;
          const visible = e => e && getComputedStyle(e).display !== 'none' && getComputedStyle(e).visibility !== 'hidden' &&
            +getComputedStyle(e).opacity > 0 && e.getBoundingClientRect().width + e.getBoundingClientRect().height > 0;
          const cards = [...document.querySelectorAll(isMobile ? '#screen .rcard' : '#cards .card')].some(visible);
          const painted = routeLayer.getLayers().some(l => l.getLatLngs && l.getLatLngs().length >= 2 && l._map && l.options.weight >= 5 &&
            visible(l._path || (l._renderer && l._renderer._container)));
          return cards && painted;
        }, mobile);
        const names = await page.evaluate(() => ({ from: labels.A, to: labels.B }));
        assert.deepEqual(names, { from: c.from.name, to: c.to.name });
        assert.equal(askRequests - before, 1, 'Choosing a candidate must not call Gemini again');
        assert.equal(errors.length, 0, errors.join('\n'));
        console.log(JSON.stringify({ view: mobile ? 'mobile' : 'desktop', case: c.name, status: 'PASS', routeStatus: response.status(),
          meters: result.routes.fastest.length_m, minutes: result.routes.fastest.minutes, visibleRoute: true, visibleCards: true, names }));
      }
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
