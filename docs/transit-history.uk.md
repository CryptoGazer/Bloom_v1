# Історія транспорту: що з'явилося в API і що додати в мобільну версію

Додано 15.11.2026. Сервер тепер знає, як лінія реально ходила в недавній день (дані з Tiger Data). У десктопі це вже показано одним рядком на картці «пішки + транспорт». У мобільній (`web/m/`) цього рядка ще немає.

## Що змінилося в API

Нічого зі старого не змінилося. Додалося три речі.

**1. Поле `history` у кроці поїздки.** У відповіді `/api/route?mode=transit`, у `transit.legs[1]` (там, де `type: "ride"`):

```json
"history": {
  "day": "2026-11-14",
  "when": "yesterday",
  "from": "22:30", "to": "01:00",
  "trips": 4, "fixes": 202,
  "median_min": -2.6, "early_min": -3.5, "late_min": -1.1,
  "early_share": 0.93, "late_share": 0.0,
  "pattern": "early",
  "be_early_min": 4,
  "wait_up_to_min": null,
  "last_seen": "23:59"
}
```

Якщо даних немає, поле дорівнює `null`: тоді нічого не показуємо.

| Поле | Що це |
|---|---|
| `when` | `"today"`, `"yesterday"` або `"date"` (тоді показуємо `day` як `14.11`) |
| `from`, `to` | за який проміжок часу того дня зібрано спостереження |
| `trips` | скільки рейсів бачили (завжди 3 або більше) |
| `median_min` | звичайне відхилення від розкладу в хвилинах; мінус означає «раніше» |
| `early_min`, `late_min` | кожна десята позначка GPS була ще раніше / ще пізніше за це значення |
| `pattern` | яким реченням це сказати, див. нижче |
| `be_early_min` | порада «будьте на зупинці за N хв»; `null` — поради немає |
| `wait_up_to_min` | «може запізнитися до N хв»; `null` — не показувати |
| `last_seen` | коли лінію востаннє бачили того дня; `null`, якщо поїздка не під кінець руху |

**2. Прапорець у `/api/health`:** `"history": true`, коли історія прочитана з бази.

**3. Звіт за вечір:** `GET /api/transit/night` і готова сторінка `/night.html` (усі лінії за один вечір). У мобільній достатньо посилання на неї.

## Значення `pattern`

| `pattern` | Речення (ключ у `web/i18n.js`) | Які числа підставити |
|---|---|---|
| `on_time` | `hist.how.on_time` | — |
| `early` | `hist.how.early` | `{n}` = `median_min` |
| `late` | `hist.how.late` | `{n}` = `median_min` |
| `uneven` | `hist.how.uneven` | `{a}` = `be_early_min`, `{b}` = `wait_up_to_min` |
| `on_time_but_early` | `hist.how.on_time_but_early` | `{a}` = `be_early_min` |
| `on_time_but_late` | `hist.how.on_time_but_late` | `{b}` = `wait_up_to_min` |

`{n}` округлюємо так: `Math.max(1, Math.round(Math.abs(x)))`.

## Тексти

Усі тексти вже є в `web/i18n.js`, блок `hist`, трьома мовами (RO / EN / RU). Мобільна версія читає `web/i18n.js`, тому їх можна брати через `t('hist.…')` без копіювання в `web/m/texts.js`.

| Ключ | Приклад (RU) |
|---|---|
| `hist.line` | `{line}: {when} в это время шёл {how}.` |
| `hist.today`, `hist.yesterday`, `hist.onDate` | `сегодня`, `вчера`, `{date}` |
| `hist.how.*` | `на ~{n} мин раньше расписания` |
| `hist.beEarly` | `Будьте на остановке за {n} мин до отправления.` |
| `hist.mayWait` | `Может опоздать до {n} мин.` |
| `hist.source` | `Наблюдение по {trips} рейсам с {from} до {to}; …` |
| `hist.lastSeen` | `В тот день линию последний раз видели в {time}.` |
| `hist.report` | `Как ходил транспорт вечером: все линии →` |

## Готовий код

Так це зроблено в десктопі (`web/app.js`, функція `historyNote`). Для `web/m/m.js` достатньо перенести й замінити розмітку на свою:

```js
function historyNote(ride) {
  const h = ride.history;
  if (!h) return '';
  const when = h.when === 'date' ? t('hist.onDate', { date: h.day.slice(8, 10) + '.' + h.day.slice(5, 7) }) : t('hist.' + h.when);
  const mins = x => Math.max(1, Math.round(Math.abs(x)));
  const how = t('hist.how.' + h.pattern, { n: mins(h.median_min), a: h.be_early_min || mins(h.early_min), b: h.wait_up_to_min || mins(h.late_min) });
  const advice = [h.be_early_min ? t('hist.beEarly', { n: h.be_early_min }) : '', h.wait_up_to_min ? t('hist.mayWait', { n: h.wait_up_to_min }) : '']
    .filter(Boolean).join(' ');
  const source = t('hist.source', { trips: h.trips, from: h.from, to: h.to }) + (h.last_seen ? ' ' + t('hist.lastSeen', { time: h.last_seen }) : '');
  // три частини: спостереження, порада (виділити), дрібний рядок із джерелом
  return { line: t('hist.line', { line: t('rt.' + ride.route_type) + ' ' + ride.line, when, how }), advice, source };
}
```

## Правила, які треба зберегти

- **Жива картка рейсу головніша.** Якщо є живий прогноз, історія йде нижче й дрібніше.
- **Порада лише в один бік.** Є «прийдіть раніше» і «може запізнитися». «Можна вийти пізніше» не пишемо ніколи.
- **Завжди показуємо джерело:** день, число рейсів, «це не обіцянка». Це спостереження за один день, а не статистика.
- **Розрахунок маршруту не змінюється.** Час «вийти о…» лишається таким самим, історія тільки додає пораду.

## Як перевірити

Локально: `./scripts/mac/lightmap.sh api`, далі запит на вечір, наприклад на 23:20 сьогодні. Зараз у базі є лише вечір 14.11 (з 21:09 до 00:08), тому для денних поїздок `history` буде `null`.

```
http://localhost:8001/?lang=ru#a=45.74717,21.24669&b=45.74441,21.22243&m=transit&at=2026-11-15T23:20
```

Тут має вийти трамвай 8 у бік Gara de Nord з порадою «за 4 хв».
