/* Run against a fresh local backend: GEMINI_TEST_URL=http://127.0.0.1:8019 node scripts/testing/check_gemini_ui.cjs
   Requires Playwright and installed Chrome. Gemini responses are fixtures; routing is the real local API.
   No provider calls or real microphone input: Chrome supplies synthetic audio. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const base = process.env.GEMINI_TEST_URL || 'http://127.0.0.1:8019';
const origin = new URL(base).origin;
const c12 = { id: 'c12', kind: 'place', name: 'Căminul C12 UVT', lat: 45.749852, lon: 21.240281 };
const hospital = { id: 'hospital', kind: 'place', name: 'Spitalul Clinic Căi Ferate', lat: 45.749327, lon: 21.218488 };
const botanic = { id: 'botanic', kind: 'place', name: 'Parcul Botanic', lat: 45.760166, lon: 21.224805 };
const square = { id: 'square', kind: 'street', name: 'Piața Victoriei', lat: 45.753113, lon: 21.2257 };
const route = { kind: 'route', from: c12, to: botanic, from_here: false, mode: 'walk', at: null, heard: '' };

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true,
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  try {
    for (const mobile of [false, true]) {
      const context = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
        permissions: ['geolocation', 'microphone'], geolocation: { latitude: 45.7509, longitude: 21.2321 } });
      const page = await context.newPage();
      const errors = [], requests = [], routeResponses = [];
      let response = route, askCalls = 0, audioCalls = 0, renderedRoutes = 0;
      page.on('pageerror', e => errors.push(e.message));
      page.on('response', r => {
        if (new URL(r.url()).pathname === '/api/route') routeResponses.push({ url: r.url(), status: r.status() });
      });
      await page.route('**/*', async intercepted => {
        const request = intercepted.request(), url = new URL(request.url());
        if (url.origin !== origin) return intercepted.abort();
        if (url.pathname === '/api/health') return intercepted.fulfill({ json: { ok: true, ask: true, ask_version: 2 } });
        if (url.pathname === '/api/ask') {
          askCalls++;
          const body = request.postDataJSON();
          if (body.audio) {
            const wav = Buffer.from(body.audio, 'base64');
            assert.equal(body.mime, 'audio/wav');
            assert.equal(wav.toString('ascii', 0, 4), 'RIFF');
            assert.equal(wav.readUInt16LE(22), 1);
            assert.equal(wav.readUInt32LE(24), 16000);
            audioCalls++;
          }
          return intercepted.fulfill({ json: response });
        }
        if (url.pathname === '/api/route') requests.push(url);
        return intercepted.continue();
      });
      await page.goto(base + (mobile ? '/m/' : '/') + '?lang=ru');
      const open = async () => {
        if (mobile) await page.evaluate(() => openSearch('B'));
        await page.locator('#ask-text').waitFor({ state: 'visible' });
      };
      const submit = async value => {
        await open();
        response = value;
        await page.locator('#ask-text').fill('Тестовый маршрут');
        const done = page.waitForResponse(r => new URL(r.url()).pathname === '/api/ask');
        await page.locator('#ask-go').click();
        await done;
        await page.waitForFunction(() => !document.getElementById('ask-go').disabled);
      };
      const state = () => page.evaluate(() => ({ a: A && [A.lat, A.lng], b: B && [B.lat, B.lng], labels, planned: !!plan }));
      const planned = async () => {
        await page.waitForFunction(isMobile => {
          if (!plan || !A || !B) return false;
          const visible = element => {
            if (!element) return false;
            const style = getComputedStyle(element), rect = element.getBoundingClientRect();
            return rect.width + rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && +style.opacity > 0;
          };
          const card = [...document.querySelectorAll(isMobile ? '#screen .rcard' : '#cards .card')].some(visible);
          const geometry = ['fastest', 'better_lit'].every(kind => {
            const r = plan.routes[kind];
            return r.length_m > 0 && r.minutes > 0 && r.geometry.features.some(f => f.geometry.coordinates.length >= 2);
          });
          const painted = routeLayer.getLayers().some(layer => layer.getLatLngs && layer.getLatLngs().length >= 2 && layer._map && layer.options.weight >= 5 &&
            visible(layer._path || (layer._renderer && layer._renderer._container)));
          return card && geometry && painted;
        }, mobile);
        const current = await state(), request = requests.at(-1);
        const point = coordinates => coordinates.map(n => n.toFixed(5)).join(',');
        assert.equal(request.searchParams.get('from'), point(current.a));
        assert.equal(request.searchParams.get('to'), point(current.b));
        assert.equal(routeResponses.findLast(r => r.url === request.href)?.status, 200);
        renderedRoutes++;
      };

      await submit({ ...route, mode: 'bike', at: '2026-11-15T23:30' });
      await planned();
      assert.equal(requests.at(-1).searchParams.get('mode'), 'bike');
      assert.equal(requests.at(-1).searchParams.get('at'), '2026-11-15T23:30');

      // A failed new start must clear the old A while applying its independently resolved B.
      await submit({ ...route, kind: 'not_found', from: null, to: square, which: 'from', name: 'wrong normalized name',
        missing: ['from'], ambiguity: [], candidates: { from: [], to: [] }, queries: { from: 'исходное название клиники' } });
      assert.equal((await state()).a, null);
      assert.equal((await state()).planned, false);
      assert.equal((await state()).labels.B, square.name);
      assert.equal(await page.locator('#from').inputValue(), 'исходное название клиники');

      // Both ambiguous points can be selected consecutively with no further Gemini calls.
      await submit({ ...route, kind: 'clarify', from: null, to: null, which: 'from', name: null,
        missing: [], ambiguity: ['from', 'to'], candidates: { from: [hospital, c12], to: [botanic, square] } });
      const beforeChoice = askCalls;
      await page.locator('#ask-choices button', { hasText: hospital.name }).click();
      assert.equal((await state()).labels.A, hospital.name);
      assert.equal((await state()).b, null);
      await page.locator('#ask-choices button', { hasText: botanic.name }).click();
      await planned();
      assert.equal(askCalls, beforeChoice);
      assert.equal((await state()).labels.B, botanic.name);

      // Explicit "from here" requests must refresh location even if A was already selected.
      await submit({ ...route, from: null, from_here: true });
      await planned();
      assert.deepEqual((await state()).a, [45.7509, 21.2321]);

      const beforeOffTopic = await state();
      await submit({ kind: 'off_topic', heard: '' });
      assert.deepEqual(await state(), beforeOffTopic);

      // Exercise actual getUserMedia -> MediaRecorder -> 16 kHz WAV, with synthetic Chrome audio.
      await open(); response = { ...route, heard: 'от C12 до Ботанического парка' };
      await page.locator('#ask-mic').click();
      await page.waitForFunction(() => document.getElementById('ask-mic').getAttribute('aria-pressed') === 'true');
      await page.waitForTimeout(1200);
      const recorded = page.waitForResponse(r => new URL(r.url()).pathname === '/api/ask');
      await page.locator('#ask-mic').click();
      await recorded;
      await page.waitForFunction(() => !document.getElementById('ask-go').disabled && document.getElementById('ask-note').textContent.includes('Услышал:'));
      await planned();
      assert.equal(audioCalls, 1);
      assert.equal(errors.length, 0, errors.join('\n'));
      console.log(JSON.stringify({ view: mobile ? 'mobile' : 'desktop', status: 'PASS', scenarios: 6, audioCalls, renderedRoutes, checked: 'A/B → HTTP 200 + geometry → visible route and cards' }));
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
