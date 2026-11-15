'use strict';
/* Navigator logic of the phone page (web/m/m.js) without a browser: the route as a path with distances along it,
   the manoeuvres, where the phone is along the route, and arrival. Points are {lat, lng}.
   Tests: node --test web/m/nav.test.cjs */
const BzNav = (() => {
  const RAD = Math.PI / 180;
  const NAV = {
    look_m: 15,           // the turn at a vertex: direction from this far before it to this far after it
    straight_deg: 30,     // a smaller change of direction where the street name changes reads "straight on"
    sharp_deg: 55,        // a turn this sharp is announced even where the street keeps its name
    merge_m: 20,          // manoeuvres closer than this are one manoeuvre
    on_route_m: 40,       // a fix this close to the route counts as on it...
    on_route_max_m: 80,   // ...or within its own accuracy, up to this
    back_m: 30,           // a fix less than this behind the progress point is GPS noise, not a step back
    window_back_m: 60,    // where the phone is looked for first, around the progress point
    window_ahead_m: 400,
    jump_max_m: 1500,     // a position further ahead than this along the route is not taken from one fix
    arrive_left_m: 25,    // arrival: less than this left along the route...
    arrive_near_m: 25,    // ...and the phone this close to the destination, or within its accuracy up to 50 m
    trivial_m: 15,        // a route shorter than this: "you are already there"
  };

  function meters(a, b) {
    const R = 6371000, dLat = (b.lat - a.lat) * RAD, dLon = (b.lng - a.lng) * RAD;
    const x = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * RAD) * Math.cos(b.lat * RAD) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  }
  const bearing = (a, b) => (Math.atan2((b.lng - a.lng) * Math.cos(a.lat * RAD), b.lat - a.lat) / RAD + 360) % 360;
  const turnOf = (inDeg, outDeg) => ((outDeg - inDeg + 540) % 360) - 180;   // -180..180, positive = right

  // P: points with their distance along the route; seg[k]: the feature of the segment from P[k-1] to P[k]
  function buildPath(route) {
    const feats = route.geometry.features, P = [], seg = [];
    let acc = 0;
    feats.forEach((f, fi) => {
      for (const c of f.geometry.coordinates) {
        const p = { lat: c[1], lng: c[0] }, last = P[P.length - 1];
        if (last && last.p.lat === p.lat && last.p.lng === p.lng) continue;
        if (last) { acc += meters(last.p, p); seg[P.length] = fi; }
        P.push({ p, d: acc });
      }
    });
    const path = { P, seg, total: acc, man: [] };
    path.man = manoeuvres(path, feats);
    return path;
  }

  function pointAt(path, d) {
    const P = path.P;
    if (!P.length) return null;
    if (P.length === 1 || d <= 0) return P[0].p;
    if (d >= path.total) return P[P.length - 1].p;
    let lo = 0, hi = P.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (P[m].d <= d) lo = m; else hi = m; }
    const a = P[lo], b = P[hi], k = (d - a.d) / ((b.d - a.d) || 1);
    return { lat: a.p.lat + (b.p.lat - a.p.lat) * k, lng: a.p.lng + (b.p.lng - a.p.lng) * k };
  }

  // A manoeuvre at every vertex where the street name changes (at the shared point of the two streets, with the
  // direction coming in and going out) and at every sharp turn, named or not; then the arrival.
  function manoeuvres(path, feats) {
    const { P, seg } = path, found = [];
    let lastName = '';   // the last named street: an unnamed crossing between two pieces of one street is no change
    for (let k = 1; k < P.length - 1; k++) {
      const before = pointAt(path, Math.max(0, P[k].d - NAV.look_m)), after = pointAt(path, Math.min(path.total, P[k].d + NAV.look_m));
      const turn = turnOf(bearing(before, P[k].p), bearing(P[k].p, after));
      const inName = feats[seg[k]].properties.name || '', outName = feats[seg[k + 1]].properties.name || '';
      if (inName) lastName = inName;
      const renamed = seg[k] !== seg[k + 1] && outName && outName !== lastName;
      if (!renamed && Math.abs(turn) < NAV.sharp_deg) continue;
      found.push({ d: P[k].d, type: Math.abs(turn) < NAV.straight_deg ? 'straight' : turn > 0 ? 'right' : 'left', street: outName, turn });
    }
    const man = [];
    for (const m of found) {
      if (path.total - m.d < 10) continue;                              // the arrival says it
      const last = man[man.length - 1];
      if (last && m.d - last.d < NAV.merge_m) {                         // one manoeuvre: keep the sharper turn
        if (Math.abs(m.turn) > Math.abs(last.turn)) man[man.length - 1] = { ...m, street: m.street || last.street };
        continue;
      }
      man.push(m);
    }
    man.push({ d: path.total, type: 'arrive', street: '', turn: 0 });
    return man;
  }

  // the nearest point of each segment to pos, within [from, to] along the route
  function candidates(path, pos, from = -Infinity, to = Infinity) {
    const P = path.P, out = [];
    const kx = Math.cos(pos.lat * RAD) * 111320, ky = 110540;
    for (let i = 1; i < P.length; i++) {
      const a = P[i - 1], b = P[i];
      if (b.d < from || a.d > to) continue;
      const len = b.d - a.d;
      const uMin = len ? Math.max(0, (from - a.d) / len) : 0, uMax = len ? Math.min(1, (to - a.d) / len) : 1;
      const ax = (a.p.lng - pos.lng) * kx, ay = (a.p.lat - pos.lat) * ky, bx = (b.p.lng - pos.lng) * kx, by = (b.p.lat - pos.lat) * ky;
      const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
      const u = Math.min(uMax, Math.max(uMin, L2 ? -(ax * dx + ay * dy) / L2 : 0));
      out.push({ i, d: a.d + u * len, off: Math.hypot(ax + u * dx, ay + u * dy) });
    }
    return out;
  }
  function project(path, pos, from, to) {
    if (path.P.length < 2) return null;
    let best = null;
    for (const c of candidates(path, pos, from, to)) if (!best || c.off < best.off) best = c;
    return best;
  }
  // the first stretch of the route (in route order) that the fix lies on: on a loop the start is not taken for the
  // end, on an out-and-back route the way there is not taken for the way back
  function firstOn(list, allow) {
    let best = null, lastI = -2;
    for (const c of list) {
      if (c.off > allow) continue;
      if (best && c.i !== lastI + 1) break;
      if (!best || c.off < best.off) best = c;
      lastI = c.i;
    }
    return best;
  }

  const trivial = path => path.P.length < 2 || path.total < NAV.trivial_m;

  // Where a new fix puts the phone: progress along the route (m), how far off the route it is, arrival.
  // first: the first fix of a navigation may put the phone anywhere along the route (started half-way).
  function track(path, progress, fix, first = false) {
    const allow = Math.min(NAV.on_route_max_m, Math.max(NAV.on_route_m, fix.accuracy || 0));
    const P = path.P, end = P.length ? P[P.length - 1].p : fix;
    const nearEnd = meters(fix, end) <= Math.max(NAV.arrive_near_m, Math.min(fix.accuracy || 0, 50));
    if (P.length < 2) return { progress, off: meters(fix, end), onRoute: nearEnd, arrived: nearEnd, allow };
    let on = firstOn(candidates(path, fix, progress - NAV.window_back_m, progress + NAV.window_ahead_m), allow);
    if (!on) {
      const ahead = candidates(path, fix).filter(c => first || c.d - progress <= NAV.jump_max_m);
      on = firstOn(ahead.filter(c => c.d >= progress - NAV.back_m), allow) || firstOn(ahead, allow);
    }
    const off = on ? on.off : project(path, fix).off;
    let next = progress;
    if (on) next = on.d >= progress - NAV.back_m ? Math.max(progress, on.d) : on.d;
    return { progress: next, off, onRoute: !!on, arrived: !!on && path.total - next < NAV.arrive_left_m && nearEnd, allow };
  }

  return { NAV, meters, buildPath, pointAt, project, track, trivial };
})();
if (typeof module === 'object' && module.exports) module.exports = BzNav;
