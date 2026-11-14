# Gemini в Bloom: интеграция блока текстового и голосового ввода в новый интерфейс

Документ для передачи разработчику интерфейса. Он описывает фактический контракт текущего backend и то, как UI должен применять результат. Актуальные реализации: `backend/ask.py`, endpoint в `backend/app.py`, существующий клиент в `web/ask.js`.

Production: `https://95-179-180-7.sslip.io`. В интерфейсе, который раздаётся с того же домена, нужно использовать относительные URL (`/api/health`, `/api/ask`), а не зашивать production-hostname.

## 1. Что делает и чего не делает Gemini

Gemini здесь не является чат-ботом и не строит маршрут. Он выполняет одну ограниченную задачу: превращает текст или голос человека в форму:

```json
{
  "intent": "route",
  "from": "Căminul C12",
  "from_here": false,
  "to": "Piața Victoriei",
  "mode": "bike",
  "time": "2026-11-14T23:30",
  "heard": ""
}
```

После ответа Gemini backend:

1. Проверяет допустимые значения и длину полей.
2. Ищет распознанные названия только в локальном `places.json.gz`.
3. Возвращает UI доверенные точки с координатами.
4. Сам маршрут по этим точкам по-прежнему считает обычный Bloom routing API.

Полный flow:

```text
текст или микрофон
        ↓
POST /api/ask
        ↓
Gemini: intent + названия + режим + время
        ↓
локальный поиск мест Bloom
        ↓
kind: route + доверенные координаты
        ↓
UI заполняет A/B, режим и время
        ↓
обычный пересчёт /api/route
```

ElevenLabs в этом flow не участвует. Голосовая запись отправляется напрямую в Gemini как аудиовход. ElevenLabs можно позднее применить отдельно для озвучивания результата.

## 2. Требования к размещению нового UI

Рекомендуемый вариант: новый интерфейс раздаётся тем же FastAPI/Caddy и работает на том же origin, что и API. Тогда запросы выглядят так:

```js
fetch('/api/health')
fetch('/api/ask', { method: 'POST', ... })
```

Если UI будет размещён на другом домене или dev-server, backend сейчас не настраивает CORS. В таком случае либо проксировать `/api` на Bloom из dev-server, либо отдельно согласовать CORS. Нельзя вызывать Google Gemini напрямую из браузера: это раскроет `GEMINI_API_KEY`.

Микрофон браузера работает только в secure context: HTTPS или localhost. Production уже доступен по HTTPS.

## 3. Проверка доступности функции

При инициализации блока:

```http
GET /api/health
```

Пример ответа:

```json
{
  "ok": true,
  "segments": 5405,
  "data_as_of": "2026-11-14",
  "ask": true
}
```

Правило UI:

- `ask: true` — показать Gemini-блок;
- `ask: false` — скрыть его, но оставить обычные поля From/To;
- ошибка healthcheck — основная форма маршрута продолжает работать без Gemini.

`ask` становится `true`, только если backend нашёл одновременно ключ Gemini и локальный индекс мест.

## 4. Endpoint и тело запроса

```http
POST /api/ask
Content-Type: application/json
```

Тело:

```ts
type AskRequest = {
  text?: string;   // текст запроса, максимум 300 символов
  audio?: string;  // чистый base64 без префикса data:...
  mime?: string;   // для текущего UI: audio/wav
  lang?: 'ro' | 'en' | 'ru';
  near?: string;   // текущая точка A в формате "lat,lon"
};
```

Нужно отправлять либо `text`, либо `audio`, но не оба сразу. Если присутствует `audio`, backend обрабатывает запрос как голосовой.

### Текстовый пример

```js
const response = await fetch('/api/ask', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    text: 'от Căminul C12 до Piața Victoriei на велосипеде',
    lang: 'ru',
    near: currentStart ? `${currentStart.lat},${currentStart.lon}` : '',
  }),
});
```

### Для чего нужен `near`

`near` — уже выбранная пользователем точка старта. Backend использует её локально, например чтобы найти ближайшую аптеку в запросе «отсюда до ближайшей аптеки».

Координата `near` не отправляется Gemini. В Gemini уходит только текст или аудиозапись, язык интерфейса и текущее локальное время Timișoara.

Формат:

```text
45.74720,21.23140
```

Не нужно отправлять объект, GeoJSON или порядок `lon,lat`.

## 5. Варианты успешного ответа HTTP 200

### 5.1 `kind: route`

```ts
type Place = {
  kind: string;
  name: string;
  lat: number;
  lon: number;
  nearest_of?: string;
};

type AskRoute = {
  kind: 'route';
  from: Place | null;
  from_here: boolean;
  to: Place;
  mode: 'walk' | 'bike' | 'transit' | null;
  at: string | null;       // YYYY-MM-DDTHH:MM, иногда legacy HH:MM
  heard: string;           // только для голоса, максимум 200 символов
};
```

Пример:

```json
{
  "kind": "route",
  "from": {
    "kind": "place",
    "name": "Căminul C12 UVT",
    "lat": 45.7498,
    "lon": 21.2403
  },
  "from_here": false,
  "to": {
    "kind": "street",
    "name": "Piața Victoriei",
    "lat": 45.7531,
    "lon": 21.2257
  },
  "mode": "bike",
  "at": "2026-11-14T23:30",
  "heard": ""
}
```

Действия UI в указанном порядке:

1. Если `mode !== null`, выбрать соответствующий режим.
2. Если `at !== null`, заполнить время отправления.
3. Всегда установить точку B из `to.lat`, `to.lon`, `to.name`.
4. Если `from !== null`, установить точку A из `from`.
5. Если `from === null`, применить правила старта ниже.
6. Запустить обычный пересчёт маршрута.

Правила, когда `from === null`:

| Ситуация | Действие |
|---|---|
| Уже есть выбранная A, `from_here === false` | Оставить существующую A |
| `from_here === true` | Запросить/использовать текущую геолокацию |
| A ещё нет и старт не назван | Запросить текущую геолокацию |

`mode: null` означает «режим не был назван»: UI не должен самовольно менять уже выбранный режим.

`at: null` означает «время не было названо»: сохранить текущее состояние формы. Для маршрута «сейчас» route API сам использует текущее время.

### 5.2 `kind: off_topic`

```json
{
  "kind": "off_topic",
  "heard": ""
}
```

Используется для рецептов, программирования, общих вопросов, других городов, prompt injection и просьб раскрыть инструкции.

UI не должен показывать сгенерированный Gemini-текст. Рекомендуемый локальный текст:

```text
Я строю только маршруты по Тимишоаре. Напишите или скажите, откуда и куда вам нужно.
```

### 5.3 `kind: unclear`

```json
{
  "kind": "unclear",
  "heard": ""
}
```

Маршрутная тема понятна, но destination распознать нельзя, либо запись непонятна.

Рекомендуемый текст:

```text
Не понял, куда вам нужно. Например: «от Căminul C12 до Piața Victoriei».
```

### 5.4 `kind: not_found`

Не найден старт:

```json
{
  "kind": "not_found",
  "which": "from",
  "name": "Несуществующее место",
  "heard": ""
}
```

Не найден destination, но старт уже найден:

```json
{
  "kind": "not_found",
  "which": "to",
  "name": "Несуществующее место",
  "from": {
    "kind": "place",
    "name": "Căminul C12 UVT",
    "lat": 45.7498,
    "lon": 21.2403
  },
  "heard": ""
}
```

Действия UI:

1. Если в ответе есть `from`, применить его как точку A.
2. Записать `name` в проблемное поле `from` или `to`.
3. Сфокусировать это поле и открыть обычные локальные подсказки.
4. Показать сообщение, что место не найдено внутри области карты.

## 6. Голосовой ввод

Текущая реализация использует браузерные `getUserMedia` и `MediaRecorder`.

Кнопку микрофона показывать только если одновременно доступны:

```js
navigator.mediaDevices?.getUserMedia &&
window.MediaRecorder &&
window.isSecureContext
```

Рекомендуемые параметры записи:

```js
await navigator.mediaDevices.getUserMedia({
  audio: {
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
  },
});
```

Текущий клиент:

1. Записывает не более 10 секунд.
2. Декодирует браузерный WebM/Opus или MP4/AAC через `AudioContext`.
3. Ресемплирует через `OfflineAudioContext`.
4. Создаёт mono PCM WAV, 16 bit, 16 kHz.
5. Проверяет peak: запись с peak ниже `0.02` считается тишиной и не отправляется.
6. Кодирует все байты WAV в base64.

Запрос:

```js
await fetch('/api/ask', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    audio: wavBase64,
    mime: 'audio/wav',
    lang: currentLanguage,
    near: currentStart ? `${currentStart.lat},${currentStart.lon}` : '',
  }),
});
```

В `audio` нельзя передавать строку вида:

```text
data:audio/wav;base64,UklGR...
```

Нужна только часть после запятой:

```text
UklGR...
```

Backend также принимает MIME:

```text
audio/wav
audio/x-wav
audio/webm
audio/ogg
audio/mp4
audio/mpeg
audio/aac
audio/flac
```

Но готовый существующий converter отправляет `audio/wav`, поэтому для нового UI лучше сохранить этот формат.

## 7. `heard` и UX голосового запроса

Для голоса Gemini возвращает расшифровку в `heard`, например:

```json
{
  "heard": "от общежития C12 до площади Победы на велосипеде"
}
```

Её можно показать перед результатом:

```text
Услышал: «…». Понял: Căminul C12 UVT → Piața Victoriei · велосипед.
```

Для текста backend принудительно возвращает `heard: ""`, даже если модель попыталась его заполнить. Нельзя использовать `heard` как главный источник названий или координат — применять нужно только доверенные `from` и `to`.

## 8. Ошибки HTTP

Ошибки приложения обычно имеют форму:

```json
{
  "detail": {
    "code": "too_many",
    "message": "too many requests, try again in a minute"
  }
}
```

Для ошибок провайдера backend специально скрывает внутреннюю причину и API key из публичного ответа. Причина остаётся только в server log.

| HTTP | `detail.code` | Значение | Действие UI |
|---:|---|---|---|
| 422 | `empty` | Нет текста и аудио | Не отправлять пустую форму |
| 422 | `too_long` | Текст длиннее 300 символов | Ограничить input через `maxlength=300` |
| 422 | `bad_audio` | MIME, base64 или размер аудио не прошли проверку | Предложить записать ещё раз или ввести текст |
| 422 | `bad_point` | Некорректный `near` | Исправить сериализацию текущей точки |
| 429 | `too_many` | Превышен rate limit | Попросить повторить через минуту |
| 503 | `ai_busy` | Квота/перегрузка всех моделей | Оставить обычные From/To доступными |
| 503 | `ai_not_configured` | Нет/не принят key или нет индекса мест | Скрыть/отключить Gemini-блок |
| 502 | `ai_unavailable` | Сетевая или provider-ошибка | Показать fallback, не ломать форму маршрута |

FastAPI/Pydantic также может вернуть стандартный массив `detail` для нарушения максимальной длины JSON-полей. Обработчик ошибок должен выдерживать как объект с `detail.code`, так и неизвестную структуру.

## 9. Лимиты и поведение backend

| Ограничение | Значение |
|---|---:|
| Текст | 300 символов |
| Голос в текущем UI | 10 секунд |
| Поле base64-аудио | максимум 700 000 символов |
| Timeout Gemini | 20 секунд на модель |
| Запросы одного клиента | 6 в минуту |
| Все клиенты одного backend process | 30 в минуту |
| In-memory cache текста | до 1 часа, максимум 300 записей |

Одинаковые текстовые запросы без относительного времени кешируются. Голос не кешируется. Запросы со временем вроде «через 20 минут» не кешируются.

Уточнение по privacy: текст и аудио не пишутся в файл, базу или application log. Нормализованный текст текстового запроса временно используется как ключ in-memory cache процесса до одного часа. Аудио в cache не сохраняется.

Backend последовательно пробует модели из `GEMINI_MODEL`. По умолчанию:

```text
gemini-flash-lite-latest
gemini-flash-latest
```

Если первая недоступна или исчерпала квоту, используется следующая.

## 10. Состояния интерфейса

Минимальная state machine блока:

```text
idle
 ├─ submit text ───────────────→ sending
 └─ start mic → recording → encoding → sending

sending
 ├─ route ──────→ apply route → idle
 ├─ off_topic ──→ warning ─────→ idle
 ├─ unclear ────→ hint ────────→ idle
 ├─ not_found ──→ focus field ─→ idle
 └─ HTTP error ─→ fallback ────→ idle
```

Во время `sending`:

- отключить submit и микрофон;
- не разрешать второй параллельный запрос;
- показать нейтральный статус «Разбираю запрос…»;
- в `finally` всегда вернуть кнопки в рабочее состояние.

Во время записи:

- заменить иконку микрофона на Stop;
- поставить `aria-pressed="true"`;
- разрешить остановку повторным нажатием;
- автоматически остановиться через 10 секунд;
- после остановки обязательно остановить все tracks микрофона.

## 11. Локализация

Backend понимает запросы не только на RO/EN/RU, но `lang` официально должен соответствовать языку интерфейса:

```text
ro
en
ru
```

Все пользовательские сообщения формируются интерфейсом, не Gemini. Готовые переводы сейчас находятся в начале `web/ask.js` в `I18N.ro.ask`, `I18N.en.ask`, `I18N.ru.ask`.

Обязательные группы текстов:

- placeholder и label;
- начать/остановить запись;
- listening / thinking;
- understood / heard;
- off-topic;
- unclear;
- not-found;
- rate limit;
- provider unavailable;
- microphone denied;
- silence;
- privacy disclosure.

## 12. Privacy-текст

Возле формы должен быть явно видимый текст. Текущая русская версия:

```text
Текст или запись голоса отправляется в Google Gemini, чтобы понять запрос; мы не сохраняем их постоянно.
```

Более полная версия для tooltip/details:

```text
Gemini используется только для выделения места отправления, назначения, режима и времени. Маршрут рассчитывает Bloom. Координаты пользователя не отправляются Gemini. Текст и аудио не записываются в базу или файлы; текстовый запрос может до одного часа находиться в оперативной памяти backend как ключ кеша.
```

## 13. Зависимости существующего `web/ask.js`

Если Тимур захочет временно подключить файл без переписывания, он ожидает глобальные сущности:

```text
I18N, t, LANG
$
A
labels
setPoint(which, latlng, label)
setTravel(mode)
setDeparture(value)
pointsChanged()
locate()
```

И HTML с ID:

```html
<form id="ask" hidden>
  <input id="ask-text" maxlength="300">
  <button type="button" id="ask-mic"></button>
  <button type="submit" id="ask-go"></button>
  <p id="ask-note" aria-live="polite" hidden></p>
  <p id="ask-privacy"></p>
</form>
```

Для нового компонентного UI лучше перенести request/recording/apply-логику в его state management, а не сохранять глобальные переменные только ради совместимости.

## 14. Рекомендуемый универсальный обработчик ответа

Псевдокод, который нужно адаптировать к состоянию новой карты:

```js
async function interpretRoute(payload) {
  setAskState({ status: 'sending' });

  try {
    const response = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...payload,
        lang: currentLanguage,
        near: startPoint ? `${startPoint.lat},${startPoint.lon}` : '',
      }),
    });

    const body = await response.json().catch(() => ({}));

    if (!response.ok) {
      const code = body?.detail?.code;
      showAskError(code === 'too_many' ? 'tooMany' : 'unavailable');
      return;
    }

    if (body.kind === 'off_topic') {
      showOffTopic(body.heard);
      return;
    }

    if (body.kind === 'unclear') {
      showUnclear(body.heard);
      return;
    }

    if (body.kind === 'not_found') {
      if (body.from) setStart(body.from);
      setUnresolvedField(body.which, body.name);
      focusAndOpenSuggestions(body.which);
      return;
    }

    if (body.kind !== 'route') {
      showAskError('unavailable');
      return;
    }

    if (body.mode) setMode(body.mode);
    if (body.at) setDeparture(body.at);
    setDestination(body.to);

    if (body.from) {
      setStart(body.from);
      recalculateRoute();
    } else if (startPoint && !body.from_here) {
      recalculateRoute();
    } else {
      locateUserAndRecalculate();
    }

    showUnderstood(body);
  } catch {
    showAskError('unavailable');
  } finally {
    setAskState({ status: 'idle' });
  }
}
```

## 15. Минимальный acceptance checklist нового UI

- [ ] Блок показывается только при `/api/health.ask === true`.
- [ ] Текстовый запрос заполняет A/B и запускает существующую маршрутизацию.
- [ ] Неназванный mode не сбрасывает выбранный режим.
- [ ] Запрос «отсюда» использует геолокацию.
- [ ] Запрос «до ближайшей аптеки» передаёт текущую A через `near`.
- [ ] `off_topic` не показывает свободный ответ модели.
- [ ] `not_found` переводит пользователя в обычный поиск места.
- [ ] Во время запроса нельзя отправить второй.
- [ ] Микрофон скрыт без HTTPS/MediaRecorder.
- [ ] Запись автоматически заканчивается через 10 секунд.
- [ ] Тихая запись не отправляется.
- [ ] После записи tracks микрофона остановлены.
- [ ] Ошибка Gemini не ломает ручные From/To и построение маршрута.
- [ ] Privacy-текст виден до отправки.
- [ ] API key отсутствует в frontend-коде и network response.
- [ ] Проверены RO, EN и RU.

## 16. Файлы для сверки

| Файл | Роль |
|---|---|
| `backend/ask.py` | Gemini REST, prompt, schema, validation, off-topic, local place resolution, cache и rate limits |
| `backend/app.py` | `/api/health`, модель входа и `POST /api/ask` |
| `backend/geocode.py` | локальный поиск доверенных мест |
| `web/ask.js` | текущий UI, запись/конвертация WAV и применение ответа |
| `web/app.js` | состояние точек, режима, времени и пересчёт маршрута |
| `web/i18n.js` | базовая локализация приложения |
| `backend/tests/test_ask.py` | проверяемый контракт без реальных сетевых вызовов |

## 17. Быстрые production-проверки

Health:

```bash
curl -fsS https://95-179-180-7.sslip.io/api/health
```

Маршрутный запрос:

```bash
curl -fsS \
  -X POST \
  https://95-179-180-7.sslip.io/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"text":"от Căminul C12 до Piața Victoriei на велосипеде","lang":"ru"}'
```

Off-topic:

```bash
curl -fsS \
  -X POST \
  https://95-179-180-7.sslip.io/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"text":"напиши сортировку пузырьком","lang":"ru"}'
```

После интеграции обязательно проверить не только `kind`, но и фактическое заполнение точек, переключение mode/time и запуск обычного маршрута.
