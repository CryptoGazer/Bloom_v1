'use strict';
/* How the line of a planned ride ran around the same hour on a recent day (backend/history.py, from Tiger Data),
   in words, for both the desktop page (app.js) and the phone page (m/m.js). Texts: block `hist` in i18n.js.

   historyParts(ride) -> null, or { sentence, advice, source }:
     sentence  "Yesterday around this time tram 8 ran ~3 min ahead of the timetable."
     advice    "Be at the stop 4 min early." / "It may be up to 9 min late." / '' — only ever these two kinds:
               never "you can leave later", missing the last trip costs more than waiting
     source    the day, the number of trips, where the delays come from: shown only after a tap */
function historyParts(ride) {
  const h = ride && ride.history;
  if (!h) return null;
  const date = h.day.slice(8, 10) + '.' + h.day.slice(5, 7);
  const when = h.when === 'date' ? t('hist.onDate', { date }) : t('hist.' + h.when);
  const mins = x => Math.max(1, Math.round(Math.abs(x)));
  // the same minutes in the sentence and in the advice next to it: the advice rounds up
  const how = t('hist.how.' + h.pattern, { n: mins(h.median_min), a: h.be_early_min || mins(h.early_min), b: h.wait_up_to_min || mins(h.late_min) });
  const line = (t('rt.' + ride.route_type) + ' ' + ride.line).toLowerCase();
  return {
    sentence: t('hist.line', { line, when, how }),
    advice: [h.be_early_min ? t('hist.beEarly', { n: h.be_early_min }) : '', h.wait_up_to_min ? t('hist.mayWait', { n: h.wait_up_to_min }) : '']
      .filter(Boolean).join(' '),
    source: t('hist.source', { trips: h.trips, from: h.from, to: h.to, date }) + (h.last_seen ? ' ' + t('hist.lastSeen', { time: h.last_seen }) : ''),
  };
}
