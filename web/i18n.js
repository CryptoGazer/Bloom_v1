'use strict';
/* Interface texts: Romanian first (city requirement), English for students and visitors, Russian for the team.
   The word "safe" is never used: we only know about lighting. Romanian wording still needs a native speaker's check.
   Language: ?lang=ro|en|ru in the URL, else the last choice (localStorage), else Romanian. */
const I18N = {
  ro: {
    htmlLang: 'ro', decimal: ',', m: 'm', km: 'km', min: 'min', letters: { A: 'A', B: 'B' },
    title: 'Traseu de noapte', subtitle: 'Timișoara, pe jos', langLabel: 'Limba',
    mapLabel: 'Hartă: segmente de stradă colorate după starea iluminatului',
    modesLabel: 'Ce face un clic pe hartă', modeRoute: 'Traseu: clicul pune punctele', modeInspect: 'De ce această culoare: clic pe stradă',
    loading: 'Se încarcă datele…', reset: 'Resetează', showNet: 'Arată iluminatul străzilor', legendTitle: 'Legendă',
    status: { lit_confirmed: 'iluminat', lit_likely: 'probabil iluminat', unknown: 'fără date', dark_reported: 'semnalat ca neiluminat' },
    legend: {
      lit_confirmed: 'Iluminat — dovadă directă (etichetă OSM sau stâlpi pe imaginile Mapillary)',
      lit_likely: 'Probabil iluminat — doar indicii indirecte sau o sesizare',
      unknown: 'Fără date (nu înseamnă „întuneric”)',
      dark_reported: 'Semnalat ca neiluminat (sesizare recentă sau lit=no)',
      second: 'Al doilea traseu; apăsați pentru a-l alege',
    },
    areaNote: 'Harta acoperă campusul universitar, cartierele din jur și centrul (Cetate). În afara acestei zone nu calculăm trasee.',
    areaKnown: 'Stare cunoscută: {x}% din străzi și trotuare',
    kind: { street: 'stradă', sidewalk: 'trotuar', crossing: 'trecere de pietoni', path: 'alee', service: 'drum de acces' },
    noName: 'fără nume', noEvidence: 'Nicio dovadă', sourcesCount: 'surse independente: {n}', dataAsOf: 'Date la {date}.',
    ev: {
      osm_yes: 'OpenStreetMap: marcat ca iluminat (lit=yes)', osm_no: 'OpenStreetMap: marcat ca neiluminat (lit=no)',
      osm_mixed: 'OpenStreetMap: marcaje contradictorii (lit=yes și lit=no)', ways: ' (way {ways})',
      lamps: 'Mapillary: {n} stâlpi de iluminat la cel mult 20 m (cel mai apropiat la {near} m), acoperă {cov}% din lungime, văzuți în {years}',
      lampsBelow: ' — sub jumătate, sursa nu este luată în calcul',
      complaint: 'Sesizări {nr}: {sub} — {state}, depusă la {created}', closedAt: ', închisă la {date}', age: ', acum {age} zile',
      distance: ', la {d} m de segment',
      state: { fixed: 'rezolvată', open_area_outage: 'deschisă: iluminatul nu funcționează în zonă', open_lamp_out: 'deschisă: bec nefuncțional',
        open_other: 'deschisă: altă problemă', declined: 'declinată, nu este luată în calcul' },
      same_name: 'Indirect: strada „{ref}” este marcată ca iluminată în altă parte a zonei',
      near_lit_street: 'Indirect: alături este o stradă cu dovezi de iluminat',
      partial_lamps: 'Indirect: stâlpi de iluminat doar pe o parte din segment',
      inherited_dark: 'Strada alăturată este semnalată ca neiluminată',
    },
    segmentError: 'Segmentul nu a putut fi încărcat: {msg}',
    hintStart: 'Faceți clic pe hartă pentru punctul <b>{A}</b>, apoi pentru punctul <b>{B}</b>.',
    hintB: 'Acum faceți clic pentru punctul <b>{B}</b>. Marcajele pot fi mutate.',
    computing: 'Calculez traseul…',
    afterRoute: 'Apăsați pe un card pentru a afișa traseul; marcajele pot fi mutate. Linkul din bara de adrese deschide același traseu.',
    newRoute: 'Un clic pe hartă începe un traseu nou.',
    inspect: 'Faceți clic pe o stradă: vedeți din ce dovezi provine culoarea ei.',
    outside: 'Punctul {p} este în afara zonei hărții sau prea departe de alei{near}. Mutați marcajul.', nearest: ' (cea mai apropiată la {d})',
    routeFailed: 'Traseul nu a putut fi calculat: {msg}',
    serverDown: 'Serverul nu răspunde ({msg}). Porniți <code>./scripts/mac/lightmap.sh api</code> și deschideți pagina de la adresa serverului.',
    point: 'Punctul {p}',
    sameTitle: 'Cel mai rapid — și cel mai bine iluminat', nearSameTitle: 'Cel mai rapid — varianta mai bine iluminată aproape nu diferă',
    litTitle: 'Mai bine iluminat', fastTitle: 'Cel mai rapid',
    extra: '+{min} min ({share})',
    tooLong: 'În produs această variantă ar fi ascunsă: mai lungă cu {extra}; pragul este {limit} min sau {limitShare}.',
    extraOk: '{extra} față de cel mai rapid; iluminat confirmat pe {lit} din traseu, față de {fast}.',
    warn: 'Atenție: fără date sau semnalat ca neiluminat pe {bad} din {total} ({share})', warnRun: '; cea mai lungă porțiune semnalată ca neiluminată — {run}',
    via: 'Prin: ', snapNote: 'De la punct până la cea mai apropiată alee, în linie dreaptă (nu intră în calcul): {list}.',
    meta: 'Străzi și trotuare în zonă: {km} km; iluminat {lit}%, probabil {likely}%, semnalat ca neiluminat {dark}%, fără date {unknown}%. ' +
      'Date la {asof}: OpenStreetMap {osm}, stâlpi Mapillary (imagini {mly}), Sesizări ({ses}). Viteză de mers {speed} km/h.',
  },
  en: {
    htmlLang: 'en', decimal: '.', m: 'm', km: 'km', min: 'min', letters: { A: 'A', B: 'B' },
    title: 'Night route', subtitle: 'Timișoara, on foot', langLabel: 'Language',
    mapLabel: 'Map: street segments coloured by lighting status',
    modesLabel: 'What a click on the map does', modeRoute: 'Route: a click sets the points', modeInspect: 'Why this colour: click a street',
    loading: 'Loading data…', reset: 'Reset', showNet: 'Show street lighting', legendTitle: 'Legend',
    status: { lit_confirmed: 'lit', lit_likely: 'probably lit', unknown: 'no data', dark_reported: 'reported dark' },
    legend: {
      lit_confirmed: 'Lit — direct evidence (OSM tag or street lights on Mapillary imagery)',
      lit_likely: 'Probably lit — indirect signs or a complaint only',
      unknown: 'No data (does not mean dark)',
      dark_reported: 'Reported dark (recent complaint or lit=no)',
      second: 'Second route; click to switch',
    },
    areaNote: 'The map covers the university campus, the districts around it and the centre (Cetate). Routes are not computed outside this area.',
    areaKnown: 'Known status: {x}% of streets and sidewalks',
    kind: { street: 'street', sidewalk: 'sidewalk', crossing: 'crossing', path: 'path', service: 'service road' },
    noName: 'unnamed', noEvidence: 'No evidence', sourcesCount: 'independent sources: {n}', dataAsOf: 'Data as of {date}.',
    ev: {
      osm_yes: 'OpenStreetMap: tagged as lit (lit=yes)', osm_no: 'OpenStreetMap: tagged as not lit (lit=no)',
      osm_mixed: 'OpenStreetMap: conflicting tags (lit=yes and lit=no)', ways: ' (way {ways})',
      lamps: 'Mapillary: {n} street lights within 20 m (nearest {near} m), covering {cov}% of the length, seen in {years}',
      lampsBelow: ' — below half, the source is not counted',
      complaint: 'Sesizări {nr}: {sub} — {state}, filed on {created}', closedAt: ', closed on {date}', age: ', {age} days ago',
      distance: ', {d} m from the segment',
      state: { fixed: 'resolved', open_area_outage: 'open: lighting does not work in the area', open_lamp_out: 'open: a lamp is out',
        open_other: 'open: other issue', declined: 'declined, not counted' },
      same_name: 'Indirect: the street “{ref}” is tagged as lit elsewhere in the area',
      near_lit_street: 'Indirect: next to a street with lighting evidence',
      partial_lamps: 'Indirect: street lights along only part of the segment',
      inherited_dark: 'The adjacent street is reported dark',
    },
    segmentError: 'Could not load the segment: {msg}',
    hintStart: 'Click the map to set point <b>{A}</b>, then point <b>{B}</b>.',
    hintB: 'Now click point <b>{B}</b>. Markers can be dragged.',
    computing: 'Computing the route…',
    afterRoute: 'Click a card to show its route; markers can be dragged. The link in the address bar opens the same route.',
    newRoute: 'A click on the map starts a new route.',
    inspect: 'Click a street to see the evidence behind its colour.',
    outside: 'Point {p} is outside the map area or too far from any path{near}. Move the marker.', nearest: ' (nearest {d} away)',
    routeFailed: 'Could not compute the route: {msg}',
    serverDown: 'The server is not reachable ({msg}). Start <code>./scripts/mac/lightmap.sh api</code> and open this page from the server address.',
    point: 'Point {p}',
    sameTitle: 'Fastest — also the best lit', nearSameTitle: 'Fastest — the better-lit option is almost the same',
    litTitle: 'Better lit', fastTitle: 'Fastest',
    extra: '+{min} min ({share})',
    tooLong: 'The product would hide this option: longer by {extra}; the limit is {limit} min or {limitShare}.',
    extraOk: '{extra} compared with the fastest; confirmed lit on {lit} of the way, against {fast}.',
    warn: 'Warning: no data or reported dark on {bad} of {total} ({share})', warnRun: '; longest reported-dark stretch — {run}',
    via: 'Via: ', snapNote: 'Straight-line distance from the point to the nearest path (not included): {list}.',
    meta: 'Streets and sidewalks in the area: {km} km; lit {lit}%, probably lit {likely}%, reported dark {dark}%, no data {unknown}%. ' +
      'Data as of {asof}: OpenStreetMap {osm}, Mapillary street lights (imagery {mly}), Sesizări complaints ({ses}). Walking speed {speed} km/h.',
  },
  ru: {
    htmlLang: 'ru', decimal: ',', m: 'м', km: 'км', min: 'мин', letters: { A: 'А', B: 'Б' },
    title: 'Ночной маршрут', subtitle: 'Тимишоара, пешком', langLabel: 'Язык',
    mapLabel: 'Карта: отрезки улиц, окрашенные по освещённости',
    modesLabel: 'Что делает клик по карте', modeRoute: 'Маршрут: клик ставит точки', modeInspect: 'Почему такой цвет: клик по улице',
    loading: 'Загружаю данные…', reset: 'Сбросить', showNet: 'Показывать освещённость улиц', legendTitle: 'Обозначения',
    status: { lit_confirmed: 'освещено', lit_likely: 'вероятно освещено', unknown: 'нет данных', dark_reported: 'сообщали, что темно' },
    legend: {
      lit_confirmed: 'освещено — тег OSM или фонари на съёмке Mapillary',
      lit_likely: 'вероятно освещено — косвенные признаки или жалоба',
      unknown: 'нет данных (не значит «темно»)',
      dark_reported: 'сообщали, что темно (свежая жалоба или lit=no)',
      second: 'второй маршрут; нажмите, чтобы переключить',
    },
    areaNote: 'Карта покрывает университетский район, соседние кварталы и центр (Cetate). Вне этой области маршруты не строятся.',
    areaKnown: 'Известно: {x}% улиц и тротуаров',
    kind: { street: 'улица', sidewalk: 'тротуар', crossing: 'переход', path: 'дорожка', service: 'проезд' },
    noName: 'без названия', noEvidence: 'Свидетельств нет', sourcesCount: 'независимых источников: {n}', dataAsOf: 'Данные на {date}.',
    ev: {
      osm_yes: 'OpenStreetMap: отмечено «освещено» (lit=yes)', osm_no: 'OpenStreetMap: отмечено «не освещено» (lit=no)',
      osm_mixed: 'OpenStreetMap: противоречивые отметки (lit=yes и lit=no)', ways: ' (путь {ways})',
      lamps: 'Mapillary: фонарей в 20 м — {n}, ближайший в {near} м, покрыто {cov}% длины, сняты в {years}',
      lampsBelow: ' — меньше половины, источник не засчитан',
      complaint: 'Sesizări {nr}: {sub} — {state}, подана {created}', closedAt: ', закрыта {date}', age: ', {age} дн. назад',
      distance: ', {d} м от отрезка',
      state: { fixed: 'закрыта', open_area_outage: 'открыта: темно в районе', open_lamp_out: 'открыта: не горит лампа',
        open_other: 'открыта: прочее', declined: 'отклонена, не засчитана' },
      same_name: 'Косвенно: улица «{ref}» отмечена освещённой в другом месте',
      near_lit_street: 'Косвенно: рядом улица со свидетельствами освещения',
      partial_lamps: 'Косвенно: фонари есть только на части отрезка',
      inherited_dark: 'Соседняя улица отмечена тёмной по жалобам',
    },
    segmentError: 'Не удалось загрузить отрезок: {msg}',
    hintStart: 'Кликните на карте точку <b>{A}</b>, затем точку <b>{B}</b>.',
    hintB: 'Теперь кликните точку <b>{B}</b>. Маркеры можно перетаскивать.',
    computing: 'Считаю маршрут…',
    afterRoute: 'Нажмите на карточку, чтобы показать маршрут; маркеры можно перетаскивать. Ссылка из адресной строки откроет тот же маршрут.',
    newRoute: 'Клик по карте начнёт новый маршрут.',
    inspect: 'Кликните по улице: покажу, из чего сложен её цвет.',
    outside: 'Точка {p} вне области карты или слишком далеко от дорожек{near}. Передвиньте маркер.', nearest: ' (ближайшая в {d})',
    routeFailed: 'Маршрут не построен: {msg}',
    serverDown: 'Сервер недоступен ({msg}). Запустите <code>./scripts/mac/lightmap.sh api</code> и откройте эту страницу с адреса сервера.',
    point: 'Точка {p}',
    sameTitle: 'Быстрый — он же самый освещённый', nearSameTitle: 'Быстрый — более освещённый почти не отличается',
    litTitle: 'Более освещённый', fastTitle: 'Быстрый',
    extra: '+{min} мин ({share})',
    tooLong: 'В продукте этот вариант скрыли бы: дольше на {extra}; порог {limit} мин или {limitShare}.',
    extraOk: '{extra} к быстрому; подтверждённо освещено {lit} пути против {fast}.',
    warn: 'Внимание: нет данных или сообщали о темноте на {bad} из {total} ({share})', warnRun: '; самый длинный участок «сообщали, что темно» — {run}',
    via: 'Через: ', snapNote: 'От точки до ближайшей дорожки по прямой (не входит в расчёт): {list}.',
    meta: 'Улицы и тротуары области: {km} км; освещено {lit}%, вероятно {likely}%, сообщали о темноте {dark}%, нет данных {unknown}%. ' +
      'Данные на {asof}: OpenStreetMap {osm}, фонари Mapillary (снимки {mly}), жалобы Sesizări ({ses}). Скорость пешком {speed} км/ч.',
  },
};

const LANGS = ['ro', 'en', 'ru'];

function pickLang() {
  const fromUrl = new URLSearchParams(location.search).get('lang');
  if (LANGS.includes(fromUrl)) return fromUrl;
  try { const saved = localStorage.getItem('lightmap.lang'); if (LANGS.includes(saved)) return saved; } catch (e) { /* storage blocked */ }
  return 'ro';
}

const LANG = pickLang();

/* t('ev.state.fixed'), t('outside', { p: 'A' }): text in the current language; a missing key falls back to Romanian. */
function t(path, vars) {
  const get = dict => path.split('.').reduce((node, key) => (node == null ? undefined : node[key]), dict);
  let text = get(I18N[LANG]);
  if (text == null) text = get(I18N.ro);
  if (text == null) return path;
  if (typeof text !== 'string') return text;
  for (const [key, value] of Object.entries(vars || {})) text = text.split('{' + key + '}').join(String(value));
  return text;
}

function switchLang(lang) {
  try { localStorage.setItem('lightmap.lang', lang); } catch (e) { /* storage blocked */ }
  const params = new URLSearchParams(location.search);
  params.set('lang', lang);
  location.search = params.toString(); // keeps the #a=…&b=… route in the hash
}
