"""Run: python3 -m unittest discover -s tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audioplug.cli.plugin_summary import compare  # noqa: E402
from audioplug.hosts import Host  # noqa: E402


def rec(fmt, name, file=None, **kw):
    r = {"format": fmt, "name": name, "file": file or name,
         "path": "/usr/lib/%s/%s" % (fmt, file or name), "source": "system"}
    r.update(kw)
    return r


A = Host({"host": "a", "plugins": [
    rec("vst3", "Surge XT", "Surge XT.vst3"),
    rec("clap", "Surge XT", "Surge XT.clap"),
    rec("vst3", "Vital", "Vital.vst3"),
    rec("lv2", "Calf Reverb", "calf.lv2", id="urn:calf:Reverb"),
    rec("lv2", "Calf Flanger", "calf.lv2", id="urn:calf:Flanger"),
    rec("vst2", "multisampler-x12", "multisampler-x12.so"),
    rec("jsfx", "Saike Tools/Ravager.jsfx", "Saike Tools/Ravager.jsfx"),
]})
B = Host({"host": "b", "plugins": [
    rec("vst3", "Surge XT", "Surge XT.vst3"),
    rec("lv2", "Calf Reverb", "calf.lv2", id="urn:calf:Reverb"),
    rec("vst2", "lsp-plugins", "lsp-plugins.so",
        vst_ids={"123": "Multisampler x12"}),
    rec("lv2", "Dexed", "dexed.lv2", id="urn:dexed"),
]})


class TestCompare(unittest.TestCase):
    def test_both_ways(self):
        text = compare(A, B)
        self.assertIn("## On a, missing on b (1)\n\n- Vital: vst3\n", text)
        self.assertIn("- Surge XT: clap (b has vst3)", text)
        self.assertIn("- calf: lv2 [Calf Flanger] (b has lv2)", text)
        # Found inside b's VST shell library by name.
        self.assertNotIn("multisampler", text)
        self.assertIn("- Saike Tools (1): Ravager.jsfx", text)
        self.assertIn("## On b, missing on a (1)\n\n- dexed: lv2\n", text)
        self.assertTrue(text.isascii())

    def test_same(self):
        self.assertIn("Everything on b is also on b.", compare(B, B))


if __name__ == "__main__":
    unittest.main()
