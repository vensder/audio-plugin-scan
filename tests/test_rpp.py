"""Run: python3 -m unittest discover -s tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audioplug import rpp  # noqa: E402
from audioplug.cli import rpp_info  # noqa: E402
from audioplug.hosts import Host  # noqa: E402

EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                       "example.RPP")


def names(chain):
    return [(fx["name"], fx["bypass"], fx["offline"]) for fx in chain]


class TestTracks(unittest.TestCase):
    def setUp(self):
        self.project = rpp.read(EXAMPLE)
        self.tracks = rpp.tracks(self.project)

    def test_tracks_and_folders(self):
        self.assertEqual([(t["name"], t["depth"]) for t in self.tracks],
                         [("Drums", 0), ("Kick", 1), ("Snare top", 1),
                          ("Synth", 0), ("Pads", 0)])

    def test_chain_order_and_state(self):
        kick = self.tracks[1]
        self.assertEqual(names(kick["fx"]),
                         [("ReaEQ", False, False), ("ReaComp", True, False)])
        self.assertEqual(kick["fx"][1]["custom"], "Kick comp")
        snare = self.tracks[2]
        self.assertTrue(snare["muted"])
        self.assertFalse(snare["fx_on"])
        self.assertTrue(snare["fx"][0]["offline"])
        self.assertEqual(snare["items"][0][0], "snare.wav")

    def test_container_input_fx_carla(self):
        synth = self.tracks[3]
        box = synth["fx"][1]
        self.assertTrue(box["container"])
        self.assertEqual(box["name"], "Bus FX")
        self.assertEqual(names(box["chain"]),
                         [("Dragonfly Hall Reverb", False, False),
                          ("chmaha-fx/SpectrumAnalyzer.jsfx", True, False)])
        self.assertEqual(names(synth["input_fx"]), [("ReaTune", False, False)])
        rack = self.tracks[4]["fx"][0]
        self.assertEqual([w["name"] for w in rack["carla"]], ["Yoshimi"])

    def test_master(self):
        self.assertEqual(names(rpp.master_fx(self.project)),
                         [("loser/masterLimiter", False, False)])

    def test_flat_plugin_list(self):
        ws = rpp.plugins(EXAMPLE)
        self.assertEqual(len(ws), 12)
        self.assertIn(("lv2", "http://yoshimi.sourceforge.net/lv2_plugin"),
                      [(w["format"], w["key"]) for w in ws])


class TestReport(unittest.TestCase):
    def test_marks_missing(self):
        host = Host({"host": "h", "plugins": [
            {"format": "vst2", "name": "ReaEQ", "file": "reaeq.vst.so",
             "path": "/opt/REAPER/Plugins/reaeq.vst.so"}]})
        report = rpp_info.Report([host])
        kick = rpp.tracks(rpp.read(EXAMPLE))[1]
        self.assertEqual(report.chain(kick["fx"]),
                         'ReaEQ (v) -> "Kick comp" ReaComp (-, missing)')
        self.assertEqual(report.missing, 1)


class TestShellIds(unittest.TestCase):
    def test_vst_id_from_reaper_cache(self):
        # LSP 1.2 ships one lsp-plugins.so; REAPER's cache lists the
        # plugins in it by id, older projects name multisampler-x12.so.
        kick = rpp.tracks(rpp.read(EXAMPLE))[1]
        self.assertEqual(kick["fx"][0]["vst_id"], "1919247729")
        host = Host({"host": "h", "plugins": [
            {"format": "vst2", "name": "lsp-plugins", "file": "lsp-plugins.so",
             "path": "/usr/lib64/vst/lsp-plugins.vst/lsp-plugins.so",
             "vst_ids": {"1668051571": "Multi-Sampler x12 Stereo"}}]})
        want = {"format": "vst2", "key": "multisampler-x12",
                "name": "Multi-Sampler x12 Stereo", "vst_id": "1668051571"}
        self.assertEqual(host.match(want), "yes")
        want["name"] = "Something else"
        self.assertEqual(host.match(want), "-")


if __name__ == "__main__":
    unittest.main()
