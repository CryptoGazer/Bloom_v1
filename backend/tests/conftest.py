"""Tests never talk to Tiger Data: the transit history is switched off unless a test passes its own History."""
import os

os.environ["TIGER_HISTORY"] = "off"
