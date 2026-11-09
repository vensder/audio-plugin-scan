"""Run: python3 -m unittest discover -s tests"""

import io
import os
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audioplug import lmms  # noqa: E402
from audioplug.cli import lmms_info  # noqa: E402
from audioplug.hosts import Host  # noqa: E402

EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                       "example.mmp")


def slots(chain):
    return [(s["name"], s["on"]) for s in chain]


class TestSong(unittest.TestCase):
    def setUp(self):
        self.song = lmms.song(lmms.read(EXAMPLE))
        self.tracks = self.song["tracks"]

    def test_tracks_in_order(self):
        self.assertEqual(self.song["version"], "1.2.2")
        self.assertEqual([(t["name"], t["kind"]) for t in self.tracks],
                         [("Lead", "instrument"), ("Keys", "instrument"),
                          ("Pads", "instrument"),
                          ("Beat/Bassline 0", "pattern"),
                          ("Vocals", "sample"),
                          ("Automation track", "automation")])
        self.assertEqual([t["name"] for t in self.song["patterns"]],
                         ["Kicker"])

    def test_chain_and_state(self):
        lead, keys = self.tracks[0], self.tracks[1]
        self.assertEqual(slots(lead["chain"]),
                         [("tripleoscillator", True),
                          ("LADSPA caps/Plate", True),
                          ("bassbooster", False)])
        self.assertEqual(lead["mixer"], 1)
        self.assertTrue(keys["muted"])
        self.assertFalse(keys["fx_on"])
        self.assertEqual(slots(keys["chain"]),
                         [("VST Dexed", True), ("LV2 hall", True)])

    def test_carla(self):
        pads = self.tracks[2]
        carla = pads["chain"][0]["carla"]
        self.assertEqual([(w["name"], w["active"]) for w in carla],
                         [("Surge XT", True), ("Calf Reverb", False)])
        self.assertEqual(carla[0]["carla_paths"],
                         ["/home/me/.lv2", "/usr/lib/lv2"])

    def test_mixer(self):
        mixer = self.song["mixer"]
        self.assertEqual(mixer[0]["name"], "Master")
        self.assertEqual(slots(mixer[0]["chain"]), [("eq", True)])
        self.assertTrue(mixer[2]["muted"])

    def test_flat_plugin_list(self):
        got = [(w["format"], w["key"]) for w in lmms.parse(EXAMPLE)
               if not w.get("unchecked")]
        self.assertIn(("vst2", "dexed"), got)
        self.assertIn(("lv2", "urn:dragonfly:hall"), got)
        self.assertEqual(len(got), 6)

    def test_mmpz(self):
        with open(EXAMPLE, "rb") as fh:
            data = fh.read()
        fd, path = tempfile.mkstemp(suffix=".mmpz")
        with os.fdopen(fd, "wb") as fh:
            fh.write(struct.pack(">I", len(data)) + zlib.compress(data))
        try:
            self.assertEqual(len(lmms.song(lmms.read(path))["tracks"]), 6)
        finally:
            os.unlink(path)


class TestLmmsInfo(unittest.TestCase):
    def test_marks_missing(self):
        host = Host({"host": "h", "plugins": [
            {"format": "vst2", "name": "Dexed",
             "file": "Dexed.so", "path": "/home/me/.vst/Dexed.so"}]})
        report = lmms_info.LmmsReport([host])
        out = io.StringIO()
        with redirect_stdout(out):
            lmms_info.print_project(EXAMPLE, report)
        text = out.getvalue()
        self.assertIn("2 Keys [muted, FX off]: VST Dexed (v) -> "
                      "LV2 hall (v, missing)", text)
        self.assertIn("Carla Rack [Surge XT (v, missing), "
                      "Calf Reverb (-, missing)] (v)", text)
        self.assertIn("1 Kicker: kicker (v)", text)
        self.assertNotIn("FX 3", text)  # unused, no effects


if __name__ == "__main__":
    unittest.main()
