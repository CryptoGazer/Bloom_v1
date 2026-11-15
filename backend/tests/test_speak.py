"""Spoken directions: one voice per language, a phrase generated once, limits, and the API. No network: a fake provider.
Run: .venv/bin/python -m pytest backend/tests -q"""
import gzip
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.speak import SPEAK, ElevenLabs, SpeakError, Speaker, voices_from_env
from backend.tests.test_routing import FEATURES

MP3 = b"ID3" + b"\x00" * 400


class Voice:
    """Fake ElevenLabs: remembers what it was asked to say; can be made to fail."""

    model = "fake-model"

    def __init__(self, error=None):
        self.said, self.error = [], error

    def transport(self, voice, text, lang):
        if self.error:
            raise self.error
        self.said.append((voice, text, lang))
        return MP3 + f"{voice}|{lang}|{text}".encode("utf-8")


def speaker(tmp_path=None, voices=None, **kw):
    provider = Voice(kw.pop("error", None))
    return Speaker(provider, voices or {"ro": "voice-ro", "en": "voice-en"}, tmp_path, **kw), provider


def test_each_language_speaks_with_its_own_voice():
    s, provider = speaker()
    assert s.clip("50 de metri. La dreapta pe Strada Cluj.", "ro").endswith("voice-ro|ro|50 de metri. La dreapta pe Strada Cluj.".encode())
    assert s.clip("50 metres. Right onto Strada Cluj.", "en").startswith(MP3)
    assert [(v, l) for v, _, l in provider.said] == [("voice-ro", "ro"), ("voice-en", "en")]
    assert s.languages() == ["ro", "en"]


def test_a_language_without_a_voice_and_bad_requests_are_refused_before_any_call():
    s, provider = speaker()
    for text, lang, code, status in [("Прямо", "ru", "bad_lang", 422), ("Hello", "de", "bad_lang", 422), ("   ", "ro", "empty", 422),
                                     ("x" * (SPEAK["text_chars"] + 1), "ro", "too_long", 422)]:
        with pytest.raises(SpeakError) as e:
            s.clip(text, lang)
        assert (e.value.code, e.value.status) == (code, status)
    assert provider.said == []
    with pytest.raises(SpeakError, match="no voice"):
        Speaker(provider, {"ro": "voice-ro"}).clip("Hello", "en")


def test_a_phrase_is_generated_once_then_comes_from_memory_and_from_disk(tmp_path):
    s, provider = speaker(tmp_path)
    first = s.clip("La  stânga pe   Strada Unu", "ro")
    assert s.clip("La stânga pe Strada Unu", "ro") == first          # spaces do not make a new phrase
    assert len(provider.said) == 1 and provider.said[0][1] == "La stânga pe Strada Unu"
    assert len(list(tmp_path.glob("*/*.mp3"))) == 1 and not list(tmp_path.glob("*/*.part"))
    again, provider2 = speaker(tmp_path)                             # the server restarted: the disk still has it
    assert again.clip("La stânga pe Strada Unu", "ro") == first and provider2.said == []
    again.clip("La stânga pe Strada Unu", "en")                      # another language is another recording
    assert len(provider2.said) == 1


def test_another_voice_or_model_does_not_reuse_the_old_recording(tmp_path):
    s, _ = speaker(tmp_path)
    s.clip("Înainte", "ro")
    other, provider = speaker(tmp_path, voices={"ro": "another-voice"})
    assert other.clip("Înainte", "ro").endswith("another-voice|ro|Înainte".encode()) and len(provider.said) == 1


def test_only_new_phrases_are_limited_per_visitor_and_for_everybody():
    now = [0.0]
    s, provider = speaker(clock=lambda: now[0])
    for i in range(SPEAK["per_client_per_min"]):
        s.clip(f"phrase {i}", "en", client="a")
    with pytest.raises(SpeakError) as e:
        s.clip("one more", "en", client="a")
    assert (e.value.code, e.value.status) == ("too_many", 429)
    assert s.clip("phrase 3", "en", client="a").startswith(MP3)      # a phrase already made is never limited
    s.clip("one more", "en", client="b")                             # another visitor is not affected
    now[0] = 61
    s.clip("one more", "en", client="a")
    assert len(provider.said) == SPEAK["per_client_per_min"] + 1     # "one more" was made once, for b


def test_the_days_budget_of_new_characters_protects_the_quota(monkeypatch):
    monkeypatch.setitem(SPEAK, "chars_per_day", 25)
    day = ["2026-11-15"]
    s, provider = speaker(today=lambda: day[0])
    s.clip("ten chars!", "en")
    s.clip("ten chars?", "en")
    with pytest.raises(SpeakError) as e:
        s.clip("ten chars.", "en")
    assert (e.value.code, e.value.status) == ("voice_busy", 503)
    day[0] = "2026-11-16"
    s.clip("ten chars.", "en")
    assert len(provider.said) == 3


def test_a_failed_call_is_not_cached_and_the_next_one_tries_again(tmp_path):
    s, provider = speaker(tmp_path, error=SpeakError("voice_unavailable", 502, "timeout"))
    with pytest.raises(SpeakError):
        s.clip("Înainte", "ro")
    provider.error = None
    assert s.clip("Înainte", "ro").startswith(MP3) and len(provider.said) == 1


def test_voices_come_from_the_environment_and_romanian_takes_the_old_variable():
    assert voices_from_env({"ELEVENLABS_VOICE_ID": "old"}) == {"ro": "old"}
    assert voices_from_env({"ELEVENLABS_VOICE_ID": "old", "ELEVENLABS_VOICE_ID_RO": " new ", "ELEVENLABS_VOICE_ID_EN": "eng", "ELEVENLABS_VOICE_ID_RU": ""}) == \
        {"ro": "new", "en": "eng"}
    assert voices_from_env({}) == {}
    assert voices_from_env({"ELEVENLABS_VOICE_ID_RU": "must-not-be-used"}) == {}


def test_no_key_or_no_voice_means_no_speaker(monkeypatch):
    for name in ("ELEVENLABS_VOICE_ID", "ELEVENLABS_VOICE_ID_RO", "ELEVENLABS_VOICE_ID_EN", "ELEVENLABS_VOICE_ID_RU", "ELEVENLABS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "key")
    assert Speaker.from_env() is None                                # a key without any voice
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_EN", "eng")
    made = Speaker.from_env()
    assert made.languages() == ["en"] and isinstance(made.provider, ElevenLabs) and made.provider.model == SPEAK["model"]
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    assert Speaker.from_env() is None


def test_the_request_to_elevenlabs_names_the_language_and_keeps_the_key_in_a_header(monkeypatch):
    seen = {}

    class Answer:
        def __enter__(self): return self
        def __exit__(self, *_a): return False
        def read(self): return MP3

    def fake_urlopen(req, timeout, context):
        seen.update(url=req.full_url, headers={k.lower(): v for k, v in req.header_items()}, body=json.loads(req.data), timeout=timeout)
        return Answer()

    monkeypatch.setattr("backend.speak.urllib.request.urlopen", fake_urlopen)
    assert ElevenLabs("secret-key")._post("voice-ro", "Înainte", "ro") == MP3
    assert seen["url"] == f"https://api.elevenlabs.io/v1/text-to-speech/voice-ro?output_format={SPEAK['format']}"
    assert seen["body"] == {"text": "Înainte", "model_id": SPEAK["model"], "language_code": "ro"}
    assert seen["headers"]["xi-api-key"] == "secret-key" and "secret-key" not in seen["url"]


# ---------- through the API ----------

def city(tmp_path):
    path = tmp_path / "segments.geojson.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "meta": {"as_of": "2026-11-14"}, "features": FEATURES}, f)
    return path


def test_api_speaks_mp3_and_health_lists_the_languages_with_a_voice(tmp_path):
    s, provider = speaker(tmp_path / "cache")
    with TestClient(create_app(city(tmp_path), speaker=s)) as client:
        assert client.get("/api/health").json()["speak"] == ["ro", "en"]
        r = client.get("/api/speak", params={"text": "50 de metri. La dreapta pe Strada Cluj.", "lang": "ro"})
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content.startswith(MP3)
        client.get("/api/speak", params={"text": "50 de metri. La dreapta pe Strada Cluj.", "lang": "ro"})
        assert len(provider.said) == 1
        assert client.get("/api/speak", params={"text": "Прямо", "lang": "ru"}).json()["detail"]["code"] == "bad_lang"
        assert client.get("/api/speak", params={"text": " ", "lang": "ro"}).status_code == 422
        assert client.get("/api/speak", params={"lang": "ro"}).status_code == 422


def test_api_without_a_key_says_so_and_a_provider_failure_does_not_leak_its_reason(tmp_path):
    with TestClient(create_app(city(tmp_path))) as client:           # conftest keeps the key empty
        assert client.get("/api/health").json()["speak"] == []
        r = client.get("/api/speak", params={"text": "Înainte", "lang": "ro"})
        assert r.status_code == 503 and r.json()["detail"]["code"] == "voice_not_configured"
        assert client.get("/api/speak", params={"text": "Прямо", "lang": "ru"}).status_code == 422
    s, _ = speaker(error=SpeakError("voice_busy", 503, "quota_exceeded for key sk_secret"))
    with TestClient(create_app(city(tmp_path), speaker=s)) as client:
        r = client.get("/api/speak", params={"text": "Înainte", "lang": "ro"})
        assert r.status_code == 503 and r.json()["detail"] == {"code": "voice_busy", "message": "voice_busy"}
