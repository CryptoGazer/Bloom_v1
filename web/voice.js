'use strict';
/* Shared speech for desktop, mobile web and Android's bundled web page.
   Only the backend has the ElevenLabs key. Language is captured for the entire playback attempt. */
const BzVoice = (() => {
  const STORAGE_KEY = 'bezna.voice', WAIT_MS = 2500;
  const locales = { ro: 'ro-RO', en: 'en-GB' };
  function create(language) {
    const lang = Object.hasOwn(locales, language) ? language : 'ro';
    const voice = { on: false, cloud: new Set(), audio: null, at: 0 };
    const clips = new Map();
    let seq = 0, deadline = null;
    const native = () => window.BeznaNative;
    try { voice.on = localStorage.getItem(STORAGE_KEY) === '1'; } catch (_) { /* optional storage */ }
    const ctl = new AbortController(), healthTimer = setTimeout(() => ctl.abort(), WAIT_MS);
    voice.ready = fetch('/api/health', { signal: ctl.signal }).then(r => {
      if (!r.ok) throw new Error('health');
      return r.json();
    }).then(h => { voice.cloud = new Set((h.speak || []).filter(l => Object.hasOwn(locales, l))); })
      .catch(() => {}).finally(() => clearTimeout(healthTimer));

    const canSpeak = () => !!(native() || window.speechSynthesis || voice.cloud.has(lang));
    function system(text) {
      if (native()) { native().speak(text, locales[lang]); return; }
      if (!window.speechSynthesis) return;
      const u = new SpeechSynthesisUtterance(text);
      u.lang = locales[lang];
      // Prefer a matching installed voice; never explicitly choose an English voice for Romanian.
      const available = speechSynthesis.getVoices();
      const matches = v => v.lang.toLowerCase().replace('_', '-').split('-')[0] === lang;
      u.voice = available.find(v => v.lang === locales[lang]) || available.find(matches) || null;
      speechSynthesis.speak(u);
    }
    function clip(text) {
      if (clips.has(text)) return clips.get(text);
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 9000);
      const ready = fetch('/api/speak?' + new URLSearchParams({ lang, text }), { signal: controller.signal })
        .then(r => {
          if (!r.ok || !(r.headers.get('content-type') || '').startsWith('audio/')) throw new Error('speech unavailable');
          return r.blob();
        }).then(blob => {
          if (!blob.size) throw new Error('empty speech');
          return URL.createObjectURL(blob);
        });
      clips.set(text, ready);
      ready.then(() => clearTimeout(timer), () => { clearTimeout(timer); if (clips.get(text) === ready) clips.delete(text); });
      if (clips.size > 40) {
        const [oldest, gone] = clips.entries().next().value;
        clips.delete(oldest);
        gone.then(url => URL.revokeObjectURL(url), () => {});
      }
      return ready;
    }
    function unlockAudio() {
      if (voice.audio) return;
      // Reuse this element: mobile browsers grant playback to the element touched by the user.
      voice.audio = new Audio('data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQIAAAAAAA==');
      voice.audio.play().catch(() => {});
    }
    function hush() {
      seq++;
      clearTimeout(deadline);
      if (voice.audio) { voice.audio.onerror = null; voice.audio.pause(); }
      if (native()) native().stopSpeaking();
      else if (window.speechSynthesis) speechSynthesis.cancel();
    }
    function speak(value) {
      hush();
      const text = String(value || '').trim().replace(/\s+/g, ' '), attempt = seq;
      if (!text) return;
      voice.at = Date.now();
      let usedSystem = false;
      const fallback = () => {
        if (attempt !== seq || usedSystem) return;
        usedSystem = true;
        clearTimeout(deadline);
        if (voice.audio) { voice.audio.onerror = null; voice.audio.pause(); }
        system(text);
      };
      // The very first tap can precede /api/health. Wait for its configuration before picking a provider.
      voice.ready.then(() => {
        if (attempt !== seq) return;
        if (!voice.cloud.has(lang) || Array.from(text).length > 200) { fallback(); return; }
        deadline = setTimeout(fallback, WAIT_MS);
        clip(text).then(url => {
          if (usedSystem || attempt !== seq) return;
          const a = voice.audio || (voice.audio = new Audio());
          a.onerror = fallback; // decode/network errors can occur after play() has already resolved
          a.src = url;
          a.play().then(() => {
            if (attempt === seq) clearTimeout(deadline);
          }, fallback);
        }, fallback);
      });
    }
    function warm(text) {
      if (!voice.on || Array.from(text).length > 200) return;
      voice.ready.then(() => { if (voice.on && voice.cloud.has(lang)) clip(text).catch(() => {}); });
    }
    function spokenDist(m) {
      m = Math.max(0, m);
      if (m >= 975) {
        const k = (m / 1000).toFixed(1).replace('.0', '');
        if (k === '1') return lang === 'en' ? 'one kilometre' : 'un kilometru';
        return lang === 'en' ? `${k} kilometres` : `${k.replace('.', ',')} kilometri`;
      }
      const n = m >= 40 && m < 60 ? 50 : m > 100 ? Math.round(m / 50) * 50 : Math.max(10, Math.round(m / 10) * 10);
      return lang === 'en' ? `${n} metres` : `${n} ${n % 100 === 0 || n % 100 >= 20 ? 'de ' : ''}metri`;
    }
    window.addEventListener('pagehide', () => {
      hush();
      for (const clip of clips.values()) clip.then(url => URL.revokeObjectURL(url), () => {});
      clips.clear();
    });
    return Object.assign(voice, { canSpeak, speak, warm, hush, unlockAudio, spokenDist });
  }
  return { create, STORAGE_KEY };
})();
