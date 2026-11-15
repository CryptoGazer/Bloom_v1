'use strict';
/* "Ask in plain words": a text box and a microphone above the address boxes.
   The request goes to our own /api/ask. There Gemini only fills in a form (from, to, mode, time) and the places
   are found in our own index; anything that is not a route request gets a short refusal (backend/ask.py).
   BzAsk below records the voice, converts it and sends the request, without touching any page: the phone page
   (web/m/m.js) draws its own block with it. The rest of this file is the block of the desktop page: it needs
   i18n.js (I18N, t, LANG) and app.js (A, labels, setPoint, clearPoint, clearAskRoute, setTravel, setDeparture, pointsChanged, locate, $) and runs only
   where a <form id="ask"> exists. The texts of this feature are here, not in i18n.js, so that removing the
   feature means removing this file and the <form id="ask"> block in index.html. */

Object.assign(I18N.ro, { ask: {
  label: 'Întrebați cu propriile cuvinte', placeholder: 'De ex.: de la Căminul C12 la Piața Victoriei cu bicicleta',
  go: 'Caută', mic: 'Spuneți cu vocea', stop: 'Opriți înregistrarea',
  listening: 'Ascult… apăsați din nou pe microfon când ați terminat (cel mult 10 secunde).', thinking: 'Citesc cererea…',
  understood: 'Am înțeles: {from} → {to}{extra}.', heard: 'Am auzit: „{text}”.',
  offTopic: 'Planific doar trasee în Timișoara. Scrieți sau spuneți de unde plecați și unde vreți să ajungeți.',
  unclear: 'Nu am înțeles unde vreți să ajungeți. De exemplu: „de la Căminul C12 la Piața Victoriei”.',
  choose: 'Confirmați punctul „{box}”: alegeți locul potrivit.',
  missing: 'Precizați punctul „{box}” în câmpul de mai jos sau reformulați cererea.',
  choices: 'Locuri posibile',
  loopCenter: 'Centrul plimbării', loopStart: 'Începutul și sfârșitul plimbării', loopPoint: 'Punctul {n} al plimbării',
  loopUnderstood: 'Circuit în jurul „{center}”', loopApprox: 'Dimensiunea este aproximativă; traseul urmează străzile accesibile.',
  loopTransit: 'Circuitele sunt disponibile pe jos sau cu bicicleta. Alegeți unul dintre aceste moduri.',
  loopUnavailable: 'Nu am putut găsi un circuit rezonabil în jurul acestui loc în zona hărții. Alegeți alt loc sau un circuit mai mic.',
  notFound: 'Nu am găsit „{name}” în zona hărții. Alegeți locul în câmpul „{box}”.',
  tooMany: 'Prea multe cereri. Încercați peste un minut sau folosiți câmpurile de mai jos.',
  down: 'Asistentul nu este disponibil acum. Câmpurile „De unde” și „Unde” de mai jos funcționează fără el.',
  micDenied: 'Microfonul nu este disponibil ({msg}). Scrieți cererea.', silent: 'Nu se aude nimic. Încercați din nou, mai aproape de microfon.',
  privacy: 'Textul sau înregistrarea vocii este trimisă la Google Gemini pentru a înțelege cererea; noi nu o păstrăm.',
} });
Object.assign(I18N.en, { ask: {
  label: 'Ask in your own words', placeholder: 'E.g. from Căminul C12 to Piața Victoriei by bike',
  go: 'Go', mic: 'Say it', stop: 'Stop recording',
  listening: 'Listening… press the microphone again when you are done (10 seconds at most).', thinking: 'Reading your request…',
  understood: 'Understood: {from} → {to}{extra}.', heard: 'Heard: “{text}”.',
  offTopic: 'I only plan routes in Timișoara. Type or say where you start and where you want to go.',
  unclear: 'I did not catch where you want to go. For example: “from Căminul C12 to Piața Victoriei”.',
  choose: 'Confirm the “{box}” point: choose the intended place.',
  missing: 'Specify the “{box}” point in the box below or rephrase your request.',
  choices: 'Possible places',
  loopCenter: 'Walk centre', loopStart: 'Walk start and finish', loopPoint: 'Walk point {n}',
  loopUnderstood: 'Circuit around “{center}”', loopApprox: 'The size is approximate; the route follows accessible streets.',
  loopTransit: 'Circuits support walking and cycling. Choose one of these modes.',
  loopUnavailable: 'No reasonable circuit around this place fits the mapped area. Choose another place or a smaller circuit.',
  notFound: 'I could not find “{name}” inside the map area. Pick the place in the “{box}” box.',
  tooMany: 'Too many requests. Try again in a minute or use the boxes below.',
  down: 'The assistant is not available right now. The From and To boxes below work without it.',
  micDenied: 'The microphone is not available ({msg}). Type your request.', silent: 'Nothing was heard. Try again, closer to the microphone.',
  privacy: 'Your text or voice recording is sent to Google Gemini to understand the request; we do not store it.',
} });
Object.assign(I18N.ru, { ask: {
  label: 'Спросите своими словами', placeholder: 'Например: от Căminul C12 до Piața Victoriei на велосипеде',
  go: 'Найти', mic: 'Сказать голосом', stop: 'Остановить запись',
  listening: 'Слушаю… нажмите на микрофон ещё раз, когда закончите (не дольше 10 секунд).', thinking: 'Разбираю запрос…',
  understood: 'Понял: {from} → {to}{extra}.', heard: 'Услышал: «{text}».',
  offTopic: 'Я строю только маршруты по Тимишоаре. Напишите или скажите, откуда и куда вам нужно.',
  unclear: 'Не понял, куда вам нужно. Например: «от Căminul C12 до Piața Victoriei».',
  choose: 'Уточните точку «{box}»: выберите подходящее место.',
  missing: 'Уточните точку «{box}» в поле ниже или переформулируйте запрос.',
  choices: 'Возможные места',
  loopCenter: 'Центр прогулки', loopStart: 'Начало и конец прогулки', loopPoint: 'Точка прогулки {n}',
  loopUnderstood: 'Круговая прогулка вокруг «{center}»', loopApprox: 'Размер приблизительный; путь проходит по доступным улицам.',
  loopTransit: 'Круговые прогулки доступны пешком и на велосипеде. Выберите один из этих способов.',
  loopUnavailable: 'Вокруг этого места не удалось подобрать разумный круг в области карты. Выберите другое место или меньший размер прогулки.',
  notFound: 'Не нашёл «{name}» в области карты. Выберите место в поле «{box}».',
  tooMany: 'Слишком много запросов. Попробуйте через минуту или используйте поля ниже.',
  down: 'Помощник сейчас недоступен. Поля «Откуда» и «Куда» ниже работают без него.',
  micDenied: 'Микрофон недоступен ({msg}). Напишите запрос текстом.', silent: 'Ничего не слышно. Попробуйте ещё раз, ближе к микрофону.',
  privacy: 'Текст или запись голоса отправляется в Google Gemini, чтобы понять запрос; мы её не храним.',
} });

const BzAsk = (() => {
  const MAX_MS = 10000, RATE = 16000, SILENCE_PEAK = 0.02;
  // recording needs a secure page (https or localhost) and MediaRecorder
  const canRecord = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder && window.isSecureContext);
  // the block appears only if the server has a Gemini key
  const enabled = () => fetch('/api/health').then(r => r.json()).then(d => !!d.ask).catch(() => false);

  // -> {ok: true, body: the answer} or {ok: false, code: 'too_many' | 'ai_busy' | ... | ''}
  // near: the current start point; it stays on our server ("the nearest pharmacy") and is not sent to Gemini
  async function send(payload, near) {
    // A request may include two extraction attempts and three place-search rounds (20 s each).
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 110000);
    try {
      const response = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload, lang: LANG, near: near || '' }), signal: controller.signal });
      const body = await response.json().catch(() => ({}));
      return response.ok ? { ok: true, body } : { ok: false, code: (body.detail && body.detail.code) || '' };
    } catch (err) {
      return { ok: false, code: err.name === 'AbortError' ? 'timeout' : '' };
    } finally { clearTimeout(timer); }
  }

  // Starts recording for at most MAX_MS. Resolves to {stop()} once recording runs, or null if the microphone is refused.
  // done() is called once: {wav: base64} | {silent: true} | {error: text, denied: true if the microphone was refused}
  async function record(done) {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch (err) {
      done({ error: err.message || err.name, denied: true });
      return null;
    }
    const chunks = [], recorder = new MediaRecorder(stream);
    let timer = null;
    recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = async () => {
      stream.getTracks().forEach(track => track.stop());
      clearTimeout(timer);
      try {
        const wav = await toWav(new Blob(chunks, { type: recorder.mimeType }));
        done(wav ? { wav } : { silent: true });
      } catch (err) {
        done({ error: err.message || err.name });
      }
    };
    const stop = () => { if (recorder.state !== 'inactive') recorder.stop(); };
    timer = setTimeout(stop, MAX_MS);
    recorder.start();
    return { stop };
  }

  // Any format the browser records (webm/opus, mp4/aac) -> base64 WAV, PCM 16 bit, 16 kHz, mono; null if silent.
  async function toWav(blob) {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    let decoded;
    try { decoded = await ctx.decodeAudioData(await blob.arrayBuffer()); } finally { ctx.close(); }
    const frames = Math.min(Math.ceil(decoded.duration * RATE), RATE * (MAX_MS / 1000 + 1));
    const offline = new OfflineAudioContext(1, Math.max(frames, 1), RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const pcm = (await offline.startRendering()).getChannelData(0);
    let peak = 0;
    for (let i = 0; i < pcm.length; i++) peak = Math.max(peak, Math.abs(pcm[i]));
    if (peak < SILENCE_PEAK) return null;

    const view = new DataView(new ArrayBuffer(44 + pcm.length * 2));
    const ascii = (offset, s) => { for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i)); };
    ascii(0, 'RIFF'); view.setUint32(4, 36 + pcm.length * 2, true); ascii(8, 'WAVE'); ascii(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, RATE, true); view.setUint32(28, RATE * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    ascii(36, 'data'); view.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) {
      const v = Math.max(-1, Math.min(1, pcm[i]));
      view.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7FFF, true);
    }
    const bytes = new Uint8Array(view.buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(binary);
  }

  // Visitor coordinates are used only by our loop endpoint, never sent to Gemini.
  async function loopParams(r) {
    let start = r.from;
    if (r.from_here && !start) {
      const pos = await new Promise((resolve, reject) => {
        if (!navigator.geolocation) { reject(new Error(t('geoError', { msg: 'navigator.geolocation' }))); return; }
        navigator.geolocation.getCurrentPosition(resolve, reject, { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 });
      });
      start = { lat: pos.coords.latitude, lon: pos.coords.longitude };
    }
    const center = r.to || start;
    if (!center) throw new Error(t('ask.unclear'));
    const point = p => `${p.lat.toFixed(6)},${p.lon.toFixed(6)}`;
    const params = new URLSearchParams({ center: point(center), radius_m: r.radius_m || 400 });
    if (start) params.set('start', point(start));
    return params;
  }

  return { MAX_MS, canRecord, enabled, send, record, loopParams };
})();

// ---------- the block of the desktop page ----------
(function () {
  const form = document.getElementById('ask');
  if (!form) return;
  const input = $('ask-text'), mic = $('ask-mic'), go = $('ask-go'), note = $('ask-note');
  const choices = $('ask-choices') || document.createElement('div');
  if (!choices.id) { choices.id = 'ask-choices'; note.after(choices); }
  choices.className = 'ask-choices';
  choices.hidden = true;
  choices.setAttribute('role', 'group');
  choices.setAttribute('aria-label', t('ask.choices'));
  let busy = false, rec = null, starting = false;

  input.placeholder = t('ask.placeholder');
  input.setAttribute('aria-label', t('ask.label'));
  go.textContent = t('ask.go');
  $('ask-privacy').textContent = t('ask.privacy');
  setMic(false);

  BzAsk.enabled().then(on => { form.hidden = !on; });
  mic.hidden = !BzAsk.canRecord();

  function show(text, cls) {
    note.className = cls || 'small';
    note.textContent = text;
    note.hidden = !text;
  }

  function setMic(on) {
    mic.setAttribute('aria-pressed', String(on));
    mic.textContent = on ? '⏹' : '🎤';
    mic.title = t(on ? 'ask.stop' : 'ask.mic');
    mic.setAttribute('aria-label', mic.title);
  }

  function send(payload) {
    if (busy) return;
    busy = true;
    choices.replaceChildren();
    choices.hidden = true;
    go.disabled = mic.disabled = true;
    show(t('ask.thinking'));
    const near = A ? `${A.lat.toFixed(5)},${A.lng.toFixed(5)}` : '';
    BzAsk.send(payload, near)
      .then(res => (res.ok ? apply(res.body) : show(t(res.code === 'too_many' ? 'ask.tooMany' : 'ask.down'), 'warn')))
      .finally(() => { busy = false; go.disabled = mic.disabled = false; });
  }

  function apply(r) {
    askPointChoice = null;
    choices.replaceChildren();
    choices.hidden = true;
    const heard = r.heard ? t('ask.heard', { text: r.heard }) + ' ' : '';
    if (r.kind === 'off_topic') { show(heard + t('ask.offTopic'), 'warn'); return; }
    if (r.kind === 'unsupported') { show(heard + t('ask.loopTransit'), 'warn'); return; }
    clearAskRoute(); // an incomplete new request must not keep displaying the previous route
    if (r.kind === 'loop') {
      setTravel(r.mode || 'walk');
      if (r.at) setDeparture(r.at);
      show(heard + t('ask.loopUnderstood', { center: r.to ? r.to.name : t('myLocation') }) + '. ' + t('ask.loopApprox'));
      startAskLoop(r);
      return;
    }
    if (r.kind !== 'route') {
      for (const side of ['from', 'to']) {
        if ((r.missing || []).includes(side) || (r.ambiguity || []).includes(side)) clearPoint(side === 'from' ? 'A' : 'B');
      }
      if (r.from_here && !r.from) clearPoint('A');
      if (r.from) setPoint('A', [r.from.lat, r.from.lon], r.from.name);
      if (r.to) setPoint('B', [r.to.lat, r.to.lon], r.to.name);
      if (r.mode) setTravel(r.mode);
      if (r.at) setDeparture(r.at);
      const ambiguity = r.ambiguity || [], missing = r.missing || [];
      const which = r.which === 'from' ? 'from' : 'to', box = t(r.loop && which === 'to' ? 'ask.loopCenter' : which + 'Label');
      const message = ambiguity.includes(which) ? t('ask.choose', { box })
        : r.kind === 'not_found' && r.name ? t('ask.notFound', { name: r.name, box })
          : missing.length ? t('ask.missing', { box }) : t('ask.unclear');
      show(heard + message, 'warn');
      const pick = (side, place) => {
        const next = { ...r, [side]: place,
          missing: missing.filter(s => s !== side), ambiguity: ambiguity.filter(s => s !== side),
          candidates: { ...r.candidates, [side]: [] } };
        const remaining = ['from', 'to'].filter(s => next.missing.includes(s) || next.ambiguity.includes(s));
        next.kind = remaining.length ? 'clarify' : next.to ? (next.loop ? 'loop' : 'route') : 'unclear';
        next.which = remaining[0] || 'to';
        next.name = null;
        apply(next);
      };
      if (r.loop) askPointChoice = (which, place) => { pick(which === 'A' ? 'from' : 'to', place); return true; };
      for (const side of ['from', 'to']) {
        const candidates = (r.candidates && r.candidates[side]) || [];
        if (!candidates.length) continue;
        const label = document.createElement('p');
        label.textContent = t(r.loop && side === 'to' ? 'ask.loopCenter' : side + 'Label');
        choices.append(label);
        for (const place of candidates) {
          const button = document.createElement('button');
          button.type = 'button';
          button.textContent = place.name;
          button.addEventListener('click', () => {
            pick(side, place); // a verified candidate is applied locally; no extra Gemini request
          });
          choices.append(button);
        }
      }
      choices.hidden = !choices.childElementCount;
      if (!choices.hidden) choices.querySelector('button').focus();
      else {
        $(which).value = (r.queries && r.queries[which]) || r.name || '';
        $(which).focus(); // opens manual suggestions on desktop and mobile
      }
      return;
    }

    if (r.mode) setTravel(r.mode);
    if (r.at) setDeparture(r.at);
    if (r.from_here && !r.from) clearPoint('A');
    setPoint('B', [r.to.lat, r.to.lon], r.to.name);
    const keepStart = !r.from && A && !r.from_here;
    if (r.from) setPoint('A', [r.from.lat, r.from.lon], r.from.name);
    const extra = [r.mode ? t({ walk: 'travelWalk', bike: 'travelBike', transit: 'travelTransit' }[r.mode]).toLowerCase() : '',
      r.at ? `${t('atLabel').toLowerCase()} ${r.at.includes('T') ? r.at.slice(11) : r.at}` : ''].filter(Boolean).map(x => ' · ' + x).join('');
    show(heard + t('ask.understood', { from: r.from ? r.from.name : keepStart ? labels.A : t('myLocation'), to: r.to.name, extra }));
    if (r.from || keepStart) pointsChanged(); else locate(); // no start named: where the person is now
  }

  async function start() {
    starting = true;
    rec = await BzAsk.record(res => {
      rec = null;
      setMic(false);
      if (res.wav) send({ audio: res.wav, mime: 'audio/wav' });
      else if (res.silent) show(t('ask.silent'), 'warn');
      else show(t('ask.micDenied', { msg: res.error }), 'warn');
    });
    starting = false;
    if (rec) { setMic(true); show(t('ask.listening')); }
  }

  form.addEventListener('submit', e => {
    e.preventDefault();
    const text = input.value.trim();
    if (text) send({ text });
  });
  mic.addEventListener('click', () => { if (rec) rec.stop(); else if (!busy && !starting) start(); });
})();
