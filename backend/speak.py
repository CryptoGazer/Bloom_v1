"""Spoken directions: the navigator's short phrases read aloud by an ElevenLabs voice.

GET /api/speak?text=…&lang=ro answers with MP3. The key stays on the server (ELEVENLABS_API_KEY). Each interface
language has its own voice: ELEVENLABS_VOICE_ID_RO, ELEVENLABS_VOICE_ID_EN (Romanian also
takes the older ELEVENLABS_VOICE_ID). A language without a voice is simply not offered, and the page then speaks
with the phone's own voice, as it does when this service is slow, over its limits or down.

Every phrase is generated once and afterwards served from a cache on disk (data/cache/speak), so "right onto
Bulevardul Vasile Pârvan" costs credits once for everybody. What leaves the server is the phrase itself, a distance
and a street name: never coordinates, never who asked.
"""
import collections
import hashlib
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from backend.ask import _ssl_context

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format={format}"

# All numbers are settings.
SPEAK = {
    "languages": ("ro", "en"),
    "text_chars": 200,              # a navigator phrase is under 100 characters; longer requests are refused
    "model": "eleven_flash_v2_5",   # the low-delay model; it takes language_code, so "50" is read in the right language
    "format": "mp3_44100_64",       # ~8 KB per second of speech; plays in every browser and in the Android WebView
    "timeout_s": 8,
    "per_client_per_min": 30,       # newly generated phrases only: a cached phrase is free and never limited
    "total_per_min": 120,
    "chars_per_day": 30_000,        # newly generated characters a day for everybody: protects the ElevenLabs quota
    "memory_clips": 300,            # most recent phrases kept in memory
    "cache_files": 4000,            # phrases kept on disk, ~25 KB each; the oldest go first
}


class SpeakError(Exception):
    """code: empty | too_long | bad_lang | no_voice | too_many | voice_busy | voice_unavailable | voice_not_configured"""

    def __init__(self, code, status, message=""):
        super().__init__(message or code)
        self.code, self.status = code, status


def voices_from_env(environ=None):
    """{language: voice id} from ELEVENLABS_VOICE_ID_<LANG>; Romanian falls back to ELEVENLABS_VOICE_ID."""
    environ = os.environ if environ is None else environ
    voices = {}
    for lang in SPEAK["languages"]:
        voice = environ.get(f"ELEVENLABS_VOICE_ID_{lang.upper()}", "").strip() or (environ.get("ELEVENLABS_VOICE_ID", "").strip() if lang == "ro" else "")
        if voice:
            voices[lang] = voice
    return voices


class ElevenLabs:
    def __init__(self, key, model=None, transport=None):
        self.key, self.model = key, (model or SPEAK["model"]).strip()
        self.transport = transport or self._post
        self._ssl = None

    def _post(self, voice, text, lang):
        """The phrase as MP3 bytes."""
        if self._ssl is None:
            self._ssl = _ssl_context()
        body = {"text": text, "model_id": self.model, "language_code": lang}
        req = urllib.request.Request(API_URL.format(voice=voice, format=SPEAK["format"]), data=json.dumps(body).encode("utf-8"),
                                     headers={"xi-api-key": self.key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
        try:
            with urllib.request.urlopen(req, timeout=SPEAK["timeout_s"], context=self._ssl) as r:
                audio = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 429 or "quota" in detail:
                raise SpeakError("voice_busy", 503, f"over quota or too many requests: {detail}")
            if e.code in (401, 403):
                raise SpeakError("voice_not_configured", 503, f"key or voice rejected: {detail}")
            raise SpeakError("voice_unavailable", 502, f"HTTP {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SpeakError("voice_unavailable", 502, f"{type(e).__name__}: {e}")
        if len(audio) < 200:
            raise SpeakError("voice_unavailable", 502, f"an answer of {len(audio)} bytes is not a recording")
        return audio


class Speaker:
    def __init__(self, provider, voices, cache_dir=None, clock=time.monotonic, today=None):
        self.provider, self.voices, self.clock = provider, dict(voices), clock
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.today = today or (lambda: time.strftime("%Y-%m-%d"))
        self.memory = collections.OrderedDict()
        self.calls = collections.defaultdict(collections.deque)
        self.spent = (self.today(), 0)        # (day, characters generated that day)
        self.making = {}                      # phrase key -> lock: the same new phrase is generated once, not per listener
        self.lock = threading.Lock()
        self.written = 0

    @classmethod
    def from_env(cls, cache_dir=None):
        """None without ELEVENLABS_API_KEY or without a voice for any language."""
        key, voices = os.environ.get("ELEVENLABS_API_KEY", "").strip(), voices_from_env()
        return cls(ElevenLabs(key, os.environ.get("ELEVENLABS_MODEL")), voices, cache_dir) if key and voices else None

    def languages(self):
        """Interface languages that have a voice, in the order of SPEAK["languages"]."""
        return [lang for lang in SPEAK["languages"] if lang in self.voices]

    def clip(self, text, lang, client="-"):
        """The phrase in the language's voice as MP3 bytes: from memory, from disk, or newly generated."""
        text = " ".join(str(text or "").split())
        if not text:
            raise SpeakError("empty", 422, "nothing to say")
        if len(text) > SPEAK["text_chars"]:
            raise SpeakError("too_long", 422, f"at most {SPEAK['text_chars']} characters")
        if lang not in SPEAK["languages"]:
            raise SpeakError("bad_lang", 422, f"lang must be one of {', '.join(SPEAK['languages'])}")
        voice = self.voices.get(lang)
        if not voice:
            raise SpeakError("no_voice", 404, f"no voice is set for '{lang}'")
        key = hashlib.sha256(f"{getattr(self.provider, 'model', '')}|{voice}|{lang}|{text}".encode("utf-8")).hexdigest()
        audio = self._cached(key)
        if audio is not None:
            return audio
        with self.lock:
            making = self.making.setdefault(key, threading.Lock())
        with making:
            try:
                audio = self._cached(key)       # somebody asked for the same phrase a moment earlier
                if audio is None:
                    self._allow(client, len(text))
                    audio = self.provider.transport(voice, text, lang)
                    self._keep(key, audio)
            finally:
                with self.lock:
                    self.making.pop(key, None)
        return audio

    def _path(self, key):
        return self.cache_dir / key[:2] / f"{key}.mp3" if self.cache_dir else None

    def _cached(self, key):
        with self.lock:
            if key in self.memory:
                self.memory.move_to_end(key)
                return self.memory[key]
        path = self._path(key)
        if path is not None:
            try:
                audio = path.read_bytes()
            except OSError:
                return None
            self._remember(key, audio)
            return audio
        return None

    def _remember(self, key, audio):
        with self.lock:
            self.memory[key] = audio
            self.memory.move_to_end(key)
            while len(self.memory) > SPEAK["memory_clips"]:
                self.memory.popitem(last=False)

    def _keep(self, key, audio):
        self._remember(key, audio)
        path = self._path(key)
        if path is None:
            return
        try:  # written beside its place and moved in one step: a reader never meets half a file (also on Windows)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
            with os.fdopen(fd, "wb") as f:
                f.write(audio)
            os.replace(tmp, path)
        except OSError as e:  # a full or read-only disk must not silence the navigator
            print(f"speak: the phrase was not cached: {type(e).__name__}: {e}", flush=True)
            return
        self.written += 1
        if self.written % 200 == 0:
            self._prune()

    def _prune(self):
        files = sorted(self.cache_dir.glob("*/*.mp3"), key=lambda p: p.stat().st_mtime)
        for path in files[:max(0, len(files) - SPEAK["cache_files"])]:
            try:
                path.unlink()
            except OSError:
                pass

    def _allow(self, client, chars):
        """Limits on newly generated phrases: per visitor and for everybody a minute, and characters a day."""
        with self.lock:
            now, day = self.clock(), self.today()
            if self.spent[0] != day:
                self.spent = (day, 0)
            if self.spent[1] + chars > SPEAK["chars_per_day"]:
                raise SpeakError("voice_busy", 503, "the day's budget of generated speech is used up")
            for who, limit in ((client, SPEAK["per_client_per_min"]), ("*", SPEAK["total_per_min"])):
                q = self.calls[who]
                while q and now - q[0] >= 60:
                    q.popleft()
                if len(q) >= limit:
                    raise SpeakError("too_many", 429, "too many new phrases, try again in a minute")
            self.calls[client].append(now)
            self.calls["*"].append(now)
            self.spent = (day, self.spent[1] + chars)
            for who in [k for k, q in self.calls.items() if not q]:
                del self.calls[who]
