"""Tests never talk to outside services. Tiger Data: the transit history is off unless a test passes its own History."""
import os

os.environ["TIGER_HISTORY"] = "off"
# and never to ElevenLabs: an empty key is kept by load_env, so no Speaker is built unless a test passes its own
os.environ["ELEVENLABS_API_KEY"] = ""
