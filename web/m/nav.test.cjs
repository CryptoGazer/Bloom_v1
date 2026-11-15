'use strict';
// Navigator logic (web/m/nav.js) without a browser. Run: node --test web/m/nav.test.cjs
// The cases come from the audit of 15.11.2026 (docs/qa/2026-11-15-bezna-app-audit.md).
const test = require('node:test');
const assert = require('node:assert/strict');
const N = require('./nav.js');

const M_LAT = 1 / 111195;                     // degrees per metre north
const M_LON = 1 / (111195 * Math.cos(45.75 * Math.PI / 180));
const at = (east, north) => [21.22 + east * M_LON, 45.75 + north * M_LAT];   // [lon, lat] from metres
const feature = (name, coords, status = 'lit_confirmed') => ({ properties: { name, status }, geometry: { coordinates: coords } });
const route = (...features) => ({ geometry: { features } });
const fix = (east, north, accuracy = 5) => { const [lng, lat] = at(east, north); return { lat, lng, accuracy }; };

test('a turn at the junction of two streets is announced at the junction', () => {
  // 100 m east on Street East, then left (north) 100 m on Street North; each street has only its two ends
  const p = N.buildPath(route(feature('Street East', [at(0, 0), at(100, 0)]), feature('Street North', [at(100, 0), at(100, 100)])));
  const turn = p.man.find(m => m.type !== 'arrive');
  assert.ok(turn, 'the left turn is missing');
  assert.equal(turn.type, 'left');
  assert.equal(turn.street, 'Street North');
  assert.ok(Math.abs(turn.d - 100) < 1, `announced at ${turn.d} m, not at the junction`);
});

test('a sharp turn on a street that keeps its name is announced too', () => {
  const p = N.buildPath(route(feature('Strada Lungă', [at(0, 0), at(100, 0), at(100, -80)])));
  const turn = p.man.find(m => m.type !== 'arrive');
  assert.ok(turn && turn.type === 'right' && Math.abs(turn.d - 100) < 1);
});

test('going straight where the name changes says "straight on", a gentle bend says nothing', () => {
  const p = N.buildPath(route(feature('A', [at(0, 0), at(100, 0)]), feature('B', [at(100, 0), at(200, 5)]), feature('B', [at(200, 5), at(300, 12)], 'lit_likely')));
  assert.deepEqual(p.man.map(m => m.type), ['straight', 'arrive']);
});

test('a fix a kilometre past the end is not an arrival', () => {
  const p = N.buildPath(route(feature('Street East', [at(0, 0), at(200, 0)])));
  const s = N.track(p, 150, fix(1305, 0));     // exact position, 1105 m beyond the end
  assert.equal(s.arrived, false);
  assert.equal(s.onRoute, false);
  assert.equal(s.progress, 150);
});

test('arrival needs the phone near the destination', () => {
  const p = N.buildPath(route(feature('Street East', [at(0, 0), at(200, 0)])));
  assert.equal(N.track(p, 150, fix(195, 2)).arrived, true);
});

test('a stray fix cannot push progress far ahead, and a real step back is followed', () => {
  const p = N.buildPath(route(feature('S', [at(0, 0), at(1000, 0)]), feature('T', [at(1000, 0), at(1000, 1000)])));
  assert.equal(N.track(p, 100, fix(1000, 900, 60)).progress, 100);   // 1700 m ahead in one fix: not taken
  assert.ok(Math.abs(N.track(p, 400, fix(250, 3)).progress - 250) < 1);
});

test('on a loop the start is not mistaken for the end', () => {
  // a 400 m square that comes back to its start
  const p = N.buildPath(route(feature('N', [at(0, 0), at(100, 0), at(100, 100), at(0, 100), at(0, 0)])));
  const s = N.track(p, 0, fix(2, 1));
  assert.ok(s.progress < 10, `progress jumped to ${s.progress}`);
  assert.equal(s.arrived, false);
  assert.equal(N.track(p, 390, fix(0, 3)).arrived, true);
});

test('a route with no length is recognised before navigating, and nothing throws', () => {
  const p = N.buildPath(route(feature('S', [at(10, 10), at(10, 10)])));
  assert.equal(N.trivial(p), true);
  assert.equal(N.project(p, fix(10, 10)), null);
  assert.doesNotThrow(() => N.track(p, 0, fix(10, 10)));
  assert.doesNotThrow(() => N.pointAt(p, 5));
});

test('an unnamed crossing between two pieces of one street is not a change of street', () => {
  const p = N.buildPath(route(feature('Bulevardul X', [at(0, 0), at(100, 0)]), feature(null, [at(100, 0), at(110, 0)]), feature('Bulevardul X', [at(110, 0), at(250, 0)])));
  assert.deepEqual(p.man.map(m => m.type), ['arrive']);
});

test('the first fix may put the phone far along the route; later fixes may not jump that far', () => {
  const p = N.buildPath(route(feature('S', [at(0, 0), at(2000, 0)])));
  assert.ok(Math.abs(N.track(p, 0, fix(1800, 2), true).progress - 1800) < 1);
  assert.equal(N.track(p, 0, fix(1800, 2)).progress, 0);
});
