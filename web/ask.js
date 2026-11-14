'use strict';
/* "Ask in plain words": a text box and a microphone above the address boxes.
   The request goes to our own /api/ask. There Gemini only fills in a form (from, to, mode, time) and the places
   are found in our own index; anything that is not a route request gets a short refusal (backend/ask.py).
   This file records the voice, sends the request and applies the answer to the page.
   Needs i18n.js (I18N, t, LANG) and app.js (A, labels, setPoint, setTravel, pointsChanged, locate, $).
   The texts of this feature are here, not in i18n.js, so that removing the feature means removing this file
   and the <form id="ask"> block in index.html. */

Object.assign(I18N.ro, { ask: {
  label: 'Întrebați cu propriile cuvinte', placeholder: 'De ex.: de la Căminul C12 la Piața Victoriei cu bicicleta',
  go: 'Caută', mic: 'Spuneți cu vocea', stop: 'Opriți înregistrarea',
  listening: 'Ascult… apăsați din nou pe microfon când ați terminat (cel mult 10 secunde).', thinking: 'Citesc cererea…',
  understood: 'Am înțeles: {from} → {to}{extra}.', heard: 'Am auzit: „{text}”.',
  offTopic: 'Planific doar trasee în Timișoara. Scrieți sau spuneți de unde plecați și unde vreți să ajungeți.',
  unclear: 'Nu am înțeles unde vreți să ajungeți. De exemplu: „de la Căminul C12 la Piața Victoriei”.',
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
  notFound: 'Не нашёл «{name}» в области карты. Выберите место в поле «{box}».',
  tooMany: 'Слишком много запросов. Попробуйте через минуту или используйте поля ниже.',
  down: 'Помощник сейчас недоступен. Поля «Откуда» и «Куда» ниже работают без него.',
  micDenied: 'Микрофон недоступен ({msg}). Напишите запрос текстом.', silent: 'Ничего не слышно. Попробуйте ещё раз, ближе к микрофону.',
  privacy: 'Текст или запись голоса отправляется в Google Gemini, чтобы понять запрос; мы её не храним.',
} });

(function () {
  const form = $('ask');
  if (!form) return;
  const input = $('ask-text'), mic = $('ask-mic'), go = $('ask-go'), note = $('ask-note');
  const MAX_MS = 10000, RATE = 16000, SILENCE_PEAK = 0.02;
  let busy = false, rec = null;

  input.placeholder = t('ask.placeholder');
  input.setAttribute('aria-label', t('ask.label'));
  go.textContent = t('ask.go');
  $('ask-privacy').textContent = t('ask.privacy');
  setMic(false);

  // the box appears only if the server has a Gemini key; the microphone only where the browser allows recording
  fetch('/api/health').then(r => r.json()).then(d => { form.hidden = !d.ask; }).catch(() => {});
  mic.hidden = !(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder && window.isSecureContext);

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
    go.disabled = mic.disabled = true;
    show(t('ask.thinking'));
    // the current start point stays on our server ("the nearest pharmacy"); it is not sent to Gemini
    const near = A ? `${A.lat.toFixed(5)},${A.lng.toFixed(5)}` : '';
    fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...payload, lang: LANG, near }) })
      .then(async r => ({ ok: r.ok, body: await r.json().catch(() => ({})) }))
      .then(({ ok, body }) => (ok ? apply(body) : fail(body.detail || {})))
      .catch(() => fail({}))
      .finally(() => { busy = false; go.disabled = mic.disabled = false; });
  }

  function fail(detail) {
    show(t(detail.code === 'too_many' ? 'ask.tooMany' : 'ask.down'), 'warn');
  }

  function apply(r) {
    const heard = r.heard ? t('ask.heard', { text: r.heard }) + ' ' : '';
    if (r.kind === 'off_topic') { show(heard + t('ask.offTopic'), 'warn'); return; }
    if (r.kind === 'not_found') {
      if (r.from) setPoint('A', [r.from.lat, r.from.lon], r.from.name);
      const which = r.which === 'from' ? 'from' : 'to';
      show(heard + t('ask.notFound', { name: r.name, box: t(which + 'Label') }), 'warn');
      $(which).value = r.name;
      $(which).focus(); // opens the suggestions for what was understood
      return;
    }
    if (r.kind !== 'route') { show(heard + t('ask.unclear'), 'warn'); return; }

    if (r.mode) setTravel(r.mode);
    if (r.at) setDeparture(r.at);
    setPoint('B', [r.to.lat, r.to.lon], r.to.name);
    const keepStart = !r.from && A && !r.from_here;
    if (r.from) setPoint('A', [r.from.lat, r.from.lon], r.from.name);
    const extra = [r.mode ? t({ walk: 'travelWalk', bike: 'travelBike', transit: 'travelTransit' }[r.mode]).toLowerCase() : '',
      r.at ? `${t('atLabel').toLowerCase()} ${r.at.includes('T') ? r.at.slice(11) : r.at}` : ''].filter(Boolean).map(x => ' · ' + x).join('');
    show(heard + t('ask.understood', { from: r.from ? r.from.name : keepStart ? labels.A : t('myLocation'), to: r.to.name, extra }));
    if (r.from || keepStart) pointsChanged(); else locate(); // no start named: where the person is now
  }

  // ---------- voice: record, convert to 16 kHz mono WAV in the browser, send ----------
  async function start() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch (err) {
      show(t('ask.micDenied', { msg: err.message || err.name }), 'warn');
      return;
    }
    const chunks = [], recorder = new MediaRecorder(stream);
    recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = async () => {
      stream.getTracks().forEach(track => track.stop());
      clearTimeout(rec.timer);
      rec = null;
      setMic(false);
      try {
        const wav = await toWav(new Blob(chunks, { type: recorder.mimeType }));
        if (wav) send({ audio: wav, mime: 'audio/wav' }); else show(t('ask.silent'), 'warn');
      } catch (err) {
        show(t('ask.micDenied', { msg: err.message || err.name }), 'warn');
      }
    };
    rec = { recorder, timer: setTimeout(stop, MAX_MS) };
    recorder.start();
    setMic(true);
    show(t('ask.listening'));
  }

  function stop() {
    if (rec && rec.recorder.state !== 'inactive') rec.recorder.stop();
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

  form.addEventListener('submit', e => {
    e.preventDefault();
    const text = input.value.trim();
    if (text) send({ text });
  });
  mic.addEventListener('click', () => { if (rec) stop(); else if (!busy) start(); });
})();
