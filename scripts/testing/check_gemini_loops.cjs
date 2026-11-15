/* Local backend on 8019. Default: mocked Gemini, real street routing and both UIs.
   --live: six real Gemini requests (one recorded voice input), replay their answers to mobile.
   Requires Playwright/Chrome; --live audio also needs macOS say and ffmpeg. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const ui = require('./gemini_ui_driver.cjs');
const live = process.argv.includes('--live');
const base = process.env.GEMINI_TEST_URL || 'http://127.0.0.1:8019';
const origin = new URL(base).origin;
const artifacts = fs.mkdtempSync(path.join(os.tmpdir(), 'bezna-gemini-loops-'));
const places = JSON.parse(execFileSync('.venv/bin/python', ['-c', "import gzip,json; print(json.dumps(json.load(gzip.open('data/out/city/places.json.gz','rt'))['entries']))"], { encoding: 'utf8' }));
const place = name => {
  const p = places.find(p => p.n === name);
  assert.ok(p, name);
  return { name: p.n, kind: p.k, lat: p.lat, lon: p.lon };
};
const liberty = place('Piața Libertății'), botanic = place('Parcul Botanic'), c12 = place('Căminul C12 UVT'), victory = place('Piața Victoriei');
const form = { kind: 'loop', loop: true, from: null, to: liberty, from_here: false, mode: 'walk', at: null, radius_m: 400, heard: '' };
const cases = [
  { id: 'centre-ru', lang: 'ru', text: 'Обойди центр Тимишоары по кругу, прогулка пешком с возвратом в начало', body: form },
  { id: 'botanic-voice-ru', lang: 'ru', audio: true,
    text: 'Построй небольшую круговую прогулку вокруг Ботанического парка с возвратом к началу',
    body: { ...form, to: botanic, radius_m: 200, heard: 'Построй небольшую круговую прогулку вокруг Ботанического парка' } },
  { id: 'bike-c12-ro', lang: 'ro', text: 'Vreau un circuit cu bicicleta în jurul căminului C12, cu întoarcere la început.', body: { ...form, to: c12, mode: 'bike' } },
  { id: 'around-me-en', lang: 'en', text: 'A short circular walk around me, starting here and returning here.', body: { ...form, to: null, from_here: true, radius_m: 200 } },
  { id: 'ordinary-journey', lang: 'ru', text: 'От C12 до Piața Victoriei пешком', expect: 'route', body: { ...form, kind: 'route', loop: false, from: c12, to: victory } },
  { id: 'off-topic', lang: 'en', text: 'Write bubble sort for a circular array', expect: 'off_topic', body: { kind: 'off_topic', heard: '' } },
];
if (!live) cases.push(
  { id: 'named-start-and-time', lang: 'ru', text: 'От C12 по кругу вокруг центра в 23:30', body: { ...form, from: c12, at: '2026-11-16T23:30', radius_m: 200 } },
  { id: 'confirm-centre', lang: 'ru', text: 'Прогулка вокруг площади', choose: botanic.name,
    body: { ...form, kind: 'clarify', to: null, which: 'to', missing: [], ambiguity: ['to'], candidates: { from: [], to: [liberty, botanic] } } },
  { id: 'manual-centre', lang: 'ru', text: 'Прогулка вокруг непонятного места', manual: botanic.name,
    body: { ...form, kind: 'not_found', to: null, which: 'to', name: 'Неизвестное место', missing: ['to'], ambiguity: [],
      candidates: { from: [], to: [] }, queries: { to: 'Ботанический парк' } } },
  { id: 'confirm-start-with-gps', lang: 'ru', text: 'Круг вокруг центра от дома', gps: true,
    body: { ...form, kind: 'unclear', which: 'from', missing: ['from'], ambiguity: [], candidates: { from: [], to: [] }, queries: { from: 'дом' } } },
  { id: 'transit-loop', lang: 'ru', text: 'Прогулка по кругу на трамвае', expect: 'unsupported', body: { kind: 'unsupported', reason: 'loop_transit', heard: '' } },
  { id: 'no-space-for-loop', lang: 'ru', text: 'Круг на границе карты', expect: 'no_loop_area', body: form },
);

async function checkPaint(page, mobile, isLoop) {
  await page.waitForFunction(({ mobile, isLoop }) => {
    if (!plan || !!plan.loop !== isLoop) return false;
    const visible = el => el && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden' &&
      +getComputedStyle(el).opacity > 0 && el.getBoundingClientRect().width + el.getBoundingClientRect().height > 0;
    const cards = [...document.querySelectorAll(mobile ? '#screen .rcard' : '#cards .card')].some(visible);
    const painted = routeLayer.getLayers().some(l => l.getLatLngs && l.getLatLngs().length >= 2 && l._map && l.options.weight >= 5 &&
      visible(l._path || l._renderer?._container));
    return cards && painted;
  }, { mobile, isLoop }, { timeout: 20000 });
}

async function run(browser, c, mobile, replay, audio) {
  const context = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
    permissions: ['geolocation', 'microphone'], geolocation: { latitude: 45.7531, longitude: 21.2257 } });
  const page = await context.newPage(), errors = [], routeRequests = [];
  let askCalls = 0;
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', async request => {
    const url = new URL(request.request().url());
    if (url.origin !== origin) return request.abort();
    if (url.pathname === '/api/health') return request.fulfill({ json: { ok: true, ask: true, ask_version: 3 } });
    if (url.pathname === '/api/ask') {
      askCalls++;
      if (replay) return request.fulfill({ status: replay.status, json: replay.body });
      if (!live) return request.fulfill({ json: c.body });
      if (audio) {
        const body = request.request().postDataJSON();
        delete body.text; body.audio = audio; body.mime = 'audio/wav';
        return request.continue({ postData: JSON.stringify(body) });
      }
    }
    if (['/api/loop', '/api/route'].includes(url.pathname)) {
      routeRequests.push(url);
      if (c.expect === 'no_loop_area') return request.fulfill({ status: 422, json: { detail: { code: 'no_loop_area' } } });
    }
    return request.continue();
  });
  let captured;
  try {
    await page.goto(base + (mobile ? '/m/' : '/') + '?lang=' + c.lang);
    await ui.open(page, mobile);
    const answer = page.waitForResponse(r => new URL(r.url()).pathname === '/api/ask', { timeout: 120000 });
    if (c.audio) {
      await page.locator(ui.mic(mobile)).click();
      await page.locator(ui.mic(mobile) + '[aria-pressed="true"]').waitFor();
      await page.waitForTimeout(1100);
      await page.locator(ui.mic(mobile)).click();
    } else {
      await page.locator(ui.input(mobile)).fill(c.text);
      await page.locator('#ask-go').click();
    }
    const response = await answer, body = await response.json();
    captured = { status: response.status(), body };
    assert.equal(response.status(), 200, JSON.stringify(body));
    await ui.settled(page, mobile);
    if (['off_topic', 'unsupported'].includes(c.expect)) {
      assert.equal(body.kind, c.expect, JSON.stringify(body));
      assert.equal(routeRequests.length, 0);
    } else {
      assert.ok(['route', 'loop', 'clarify', 'not_found', 'unclear'].includes(body.kind), JSON.stringify(body));
      if (c.choose) await page.locator('#ask-choices button').filter({ hasText: c.choose }).click();
      else if (c.manual) {
        if (mobile) await page.locator('[data-act="askFind"][data-which="B"]').click();
        await page.locator('#to').fill(c.manual);
        await page.locator(mobile ? '#s-list li' : '#to-list [role="option"]').filter({ hasText: c.manual }).first().click();
      } else if (c.gps) {
        if (mobile) {
          await page.locator('[data-act="askFind"][data-which="A"]').click();
          await page.locator('#s-list li[role="option"]').first().click();
        } else await page.locator('#locate').click();
      }
      if (c.expect === 'no_loop_area') {
        await page.waitForFunction(isMobile => (document.querySelector(isMobile ? '#toast' : '#hint')?.textContent || '').includes('разумный круг'), mobile);
        assert.equal(await page.evaluate(() => plan), null);
      } else {
        const isLoop = c.expect !== 'route';
        await checkPaint(page, mobile, isLoop);
        const planBody = await page.evaluate(() => plan);
        assert.equal(routeRequests.at(-1).pathname, isLoop ? '/api/loop' : '/api/route');
        if (isLoop) {
          assert.ok(planBody.generated);
          assert.ok(planBody.points.length >= 4 && planBody.points.length <= 10);
          for (const r of Object.values(planBody.routes)) {
            assert.ok(r.length_m > 0 && r.minutes > 0);
            const coords = r.geometry.features.flatMap(f => f.geometry.coordinates);
            for (let i = 0; i < 2; i++) assert.ok(Math.abs(coords[0][i] - coords.at(-1)[i]) < 1e-5, 'Loop does not close');
          }
          if (c.id === 'around-me-en' || c.gps) {
            assert.equal(planBody.from.lat, 45.7531);
            assert.equal(planBody.from.lon, 21.2257);
          }
          if (c.id === 'named-start-and-time') {
            assert.equal(planBody.from.lat, c12.lat);
            assert.equal(planBody.from.lon, c12.lon);
            assert.equal(planBody.at, '2026-11-16 23:30');
          }
          if (c.id === 'centre-ru') {
            if (mobile) await page.waitForFunction(() => !anim, null, { timeout: 20000 });
            await page.screenshot({ path: path.join(artifacts, mobile ? 'mobile.png' : 'desktop.png') });
            // Shared links restore a closed walk instead of collapsing it to A -> A.
            await page.reload();
            await checkPaint(page, mobile, true);
            const restored = await page.evaluate(() => plan);
            assert.equal(restored.points.length, planBody.points.length);
          }
        }
        captured.route = { meters: planBody.routes.fastest.length_m, minutes: planBody.routes.fastest.minutes,
          mode: planBody.mode, points: planBody.points?.length, center: planBody.center };
      }
    }
    assert.equal(askCalls, 1, 'Choosing a place or reopening a link must not call Gemini again');
    assert.deepEqual(errors, []);
    return { ...captured, view: mobile ? 'mobile' : 'desktop', pass: true };
  } catch (e) {
    await page.screenshot({ path: path.join(artifacts, c.id + '-' + (mobile ? 'mobile' : 'desktop') + '-failed.png') });
    return { ...captured, view: mobile ? 'mobile' : 'desktop', pass: false, error: e.message, errors };
  } finally { await context.close(); }
}

(async () => {
  console.log(JSON.stringify({ stage: 'start', live, artifacts, cases: cases.length }));
  const browser = await chromium.launch({ channel: 'chrome', headless: true,
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const results = [];
  try {
    for (const c of cases) {
      let audio;
      if (live && c.audio) {
        const file = path.join(artifacts, c.id);
        execFileSync('say', ['-v', 'Milena', '-r', '205', '-o', file + '.aiff', c.text]);
        execFileSync('ffmpeg', ['-nostdin', '-loglevel', 'error', '-i', file + '.aiff', '-ar', '16000', '-ac', '1', file + '.wav']);
        audio = fs.readFileSync(file + '.wav').toString('base64');
      }
      const desktop = await run(browser, c, false, undefined, audio);
      const mobile = desktop.body ? await run(browser, c, true, desktop, audio) : { pass: false, error: 'No captured response' };
      const result = { id: c.id, text: c.text, desktop, mobile };
      results.push(result);
      fs.writeFileSync(path.join(artifacts, 'results.json'), JSON.stringify(results, null, 2));
      console.log(JSON.stringify({ id: c.id, kind: desktop.body?.kind, heard: desktop.body?.heard,
        desktop: desktop.pass, mobile: mobile.pass, route: desktop.route, errors: [desktop.error, mobile.error].filter(Boolean) }));
    }
  } finally { await browser.close(); }
  const failed = results.filter(r => !r.desktop.pass || !r.mobile.pass).length;
  console.log(JSON.stringify({ stage: 'complete', passed: results.length - failed, failed, results: path.join(artifacts, 'results.json') }));
  if (failed) process.exitCode = 1;
})().catch(e => { console.error(e); process.exitCode = 1; });
