'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname, 'voice.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
function setup(lang = 'en') {
  const health = deferred(), requests = [], spoken = [], played = [], timers = new Map();
  let timerId = 0;
  const context = vm.createContext({
    console, URL: { createObjectURL: blob => blob.url, revokeObjectURL() {} }, URLSearchParams, AbortController,
    localStorage: { getItem() { return null; } },
    window: { addEventListener() {}, BeznaNative: { speak: (text, lang) => spoken.push({ text, lang }), stopSpeaking() {} } },
    setTimeout: (fn, delay) => { timers.set(++timerId, { fn, delay }); return timerId; },
    clearTimeout: id => timers.delete(id),
    fetch: url => {
      if (url === '/api/health') return health.promise;
      const done = deferred(); requests.push({ url, done }); return done.promise;
    },
    Audio: class {
      play() { played.push(this.src); return Promise.resolve(); }
      pause() {}
    },
  });
  vm.runInContext(source, context);
  const voice = vm.runInContext(`BzVoice.create('${lang}')`, context);
  const configure = async () => { health.resolve({ ok: true, json: async () => ({ speak: ['ro', 'en'] }) }); await settle(); };
  const finish = async (i, url) => {
    requests[i].done.resolve({ ok: true, headers: { get: () => 'audio/mpeg' }, blob: async () => ({ url, size: 500 }) });
    await settle();
  };
  const timeout = async () => {
    for (const [id, timer] of [...timers]) if (timer.delay === 2500) { timers.delete(id); timer.fn(); }
    await settle();
  };
  return { voice, requests, spoken, played, configure, finish, timeout };
}
test('first phrase waits for provider configuration and uses the selected EN/RO voice', async () => {
  for (const lang of ['en', 'ro']) {
    const h = setup(lang);
    h.voice.speak('First direction');
    await settle();
    assert.equal(h.spoken.length, 0);
    assert.equal(h.requests.length, 0);
    await h.configure();
    assert.equal(new URL(h.requests[0].url, 'https://bezna.xyz').searchParams.get('lang'), lang);
    await h.finish(0, 'blob:first');
    assert.deepEqual(h.played, ['blob:first']);
    assert.equal(h.spoken.length, 0);
  }
});
test('a late previous direction never interrupts the newer direction', async () => {
  const h = setup(); await h.configure();
  h.voice.speak('Old'); await settle();
  h.voice.speak('New'); await settle();
  await h.finish(1, 'blob:new'); await h.finish(0, 'blob:old');
  assert.deepEqual(h.played, ['blob:new']);
  assert.equal(h.spoken.length, 0);
});
test('timeout uses the same language once and discards the late cloud recording', async () => {
  const h = setup('ro'); await h.configure();
  h.voice.speak('La dreapta'); await settle();
  await h.timeout(); await h.finish(0, 'blob:late');
  assert.deepEqual(h.spoken, [{ text: 'La dreapta', lang: 'ro-RO' }]);
  assert.deepEqual(h.played, []);
});
test('muting cancels a phrase waiting for health or audio', async () => {
  const h = setup();
  h.voice.speak('Before health'); h.voice.hush(); await h.configure();
  assert.equal(h.requests.length, 0);
  h.voice.speak('Before audio'); await settle(); h.voice.hush();
  await h.timeout(); await h.finish(0, 'blob:muted');
  assert.deepEqual(h.played, []); assert.deepEqual(h.spoken, []);
});
test('old Russian locale never produces a Russian cloud request', async () => {
  const h = setup('ru'); await h.configure();
  h.voice.speak('Înainte'); await settle();
  assert.equal(new URL(h.requests[0].url, 'https://bezna.xyz').searchParams.get('lang'), 'ro');
  await h.finish(0, 'blob:ro');
});
