"""Run: python3 -m unittest discover -s tests"""

import gzip
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audioplug import lmms2rpp, rpp  # noqa: E402

EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                       "example.mmp")


def notes(item):
    return [(t, key, vel) for t, on, key, vel in item["midi"] if on]


class TestConvert(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.c = lmms2rpp.Converter(EXAMPLE, self.tmp, lv2={})
        self.by_name = {t.name: t for t in self.c.tracks}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_tracks(self):
        self.assertEqual([t.name for t in self.c.tracks],
                         ["Lead", "Keys", "Pads", "Vocals", "Pattern editor",
                          "Kicker", "Mixer 1: Lead bus", "Mixer 2: FX 2"])
        self.assertEqual(self.by_name["Pattern editor"].folder, 1)
        self.assertEqual(self.by_name["Kicker"].folder, -1)
        self.assertTrue(self.by_name["Keys"].muted)
        self.assertTrue(self.by_name["Pads"].solo)

    def test_pattern_notes(self):
        lead = self.by_name["Lead"]
        self.assertEqual(len(lead.items), 1)
        item = lead.items[0]
        self.assertAlmostEqual(item["pos"], 2.0)       # bar 2 at 120 BPM
        self.assertAlmostEqual(item["len"], 2.0)
        # LMMS key 57 (A4) -> MIDI 69, vol 100 -> velocity 64
        self.assertEqual(notes(item), [(0, 69, 64), (960, 72, 127)])

    def test_pattern_editor_loops(self):
        kick = self.by_name["Kicker"]
        self.assertEqual(len(kick.items), 1)
        # 1-bar beat pattern in a 2-bar clip: played twice
        self.assertEqual([t for t, _, _ in notes(kick.items[0])],
                         [0, 1920, 3840, 5760])

    def test_mixer_routing(self):
        lead = self.by_name["Lead"]
        bus = self.by_name["Mixer 1: Lead bus"]
        self.assertFalse(lead.main_send)
        self.assertEqual(bus.receives, [(0, 1.0)])
        self.assertEqual(bus.vol, 0.5)
        self.assertTrue(bus.main_send)
        self.assertEqual([f.label for f in self.c.master_fx], ["eq"])

    def test_plugins(self):
        lead = self.by_name["Lead"].fx
        self.assertEqual([(f.label, f.names, f.stand_in, f.on) for f in lead],
                         [("tripleoscillator", ["Surge XT"], ["ReaSynth"],
                           True),
                          ("LADSPA caps/Plate", ["C* Plate"], ["ReaVerbate"],
                           True),
                          ("bassbooster", [], ["ReaEQ"], False)])
        pads = self.by_name["Pads"].fx
        self.assertEqual([(f.names, f.on) for f in pads],
                         [(["Surge XT"], True), (["Calf Reverb"], False)])
        self.assertEqual(self.c.notes["carla"][0][:2], ("Pads", "Carla-Rack"))

    def test_guide(self):
        text = lmms2rpp.guide(self.c, "x.RPP", "x-plugins.lua")
        self.assertIn("Lead: tripleoscillator (3-oscillator", text)
        self.assertIn("Vocals: vocals.wav at bar 3 (not found)", text)
        self.assertIn('"Bus volume": Mixer 1 Lead bus: volume', text)

    def test_rpp_reads_back(self):
        _, text = lmms2rpp.convert(EXAMPLE, self.tmp)
        names = sorted(os.listdir(self.tmp))
        self.assertEqual(names, ["Pads.carxp", "example-plugins.lua",
                                 "example-steps.txt", "example.RPP"])
        proj = rpp.read(os.path.join(self.tmp, "example.RPP"))
        self.assertEqual(proj.value("TEMPO"), ["120", "4", "4"])
        tracks = rpp.tracks(proj)
        self.assertEqual([(t["name"], t["depth"]) for t in tracks][4:6],
                         [("Pattern editor", 0), ("Kicker", 1)])
        lua = open(os.path.join(self.tmp, "example-plugins.lua")).read()
        self.assertIn('try = {"C* Plate"}', lua)


class TestSamplesAndZyn(unittest.TestCase):
    def test_found_sample_and_zyn(self):
        tmp = tempfile.mkdtemp()
        try:
            with open(EXAMPLE) as fh:
                xml = fh.read()
            xml = xml.replace(
                '<instrument name="kicker">\n                  <kicker/>',
                '<instrument name="zynaddsubfx">\n                  '
                '<zynaddsubfx><ZynAddSubFX-data version-major="2">'
                '<MASTER/></ZynAddSubFX-data></zynaddsubfx>')
            proj = os.path.join(tmp, "song.mmp")
            with open(proj, "w") as fh:
                fh.write(xml)
            open(os.path.join(tmp, "vocals.wav"), "wb").close()
            out = os.path.join(tmp, "out")
            c, _ = lmms2rpp.convert(proj, out)
            vocals = [t for t in c.tracks if t.name == "Vocals"][0]
            self.assertEqual(vocals.items[0]["audio"],
                             os.path.join(tmp, "vocals.wav"))
            self.assertEqual(vocals.items[0]["type"], "WAVE")
            self.assertEqual(c.notes["zyn"], [("Kicker", "Kicker.xmz")])
            with gzip.open(os.path.join(out, "Kicker.xmz")) as fh:
                self.assertIn(b"<MASTER", fh.read())
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
