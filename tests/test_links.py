"""Run: python3 -m unittest discover -s tests"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audioplug import links  # noqa: E402


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()


class TestLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.old_home = os.environ.get("HOME")
        self.home = os.path.join(t, "home")
        os.environ["HOME"] = self.home
        self.lib = os.path.join(t, "usr", "lib64")
        self.roots = [self.lib]
        lv2 = os.path.join(self.lib, "lv2")
        for b in ("calf.lv2", "x42.lv2", "yoshimi.lv2", "zyn.lv2"):
            touch(os.path.join(lv2, b, "manifest.ttl"))
        touch(os.path.join(lv2, "README"))
        hl = os.path.join(self.home, ".lv2")
        os.makedirs(hl)
        os.symlink(os.path.join(lv2, "calf.lv2"),
                   os.path.join(hl, "calf.lv2"))
        touch(os.path.join(hl, "yoshimi.lv2", "manifest.ttl"))   # copy
        os.symlink("/nonexistent/zyn.lv2", os.path.join(hl, "zyn.lv2"))
        os.symlink(os.path.join(t, "src", "my.lv2"),
                   os.path.join(hl, "my.lv2"))
        touch(os.path.join(t, "src", "my.lv2", "manifest.ttl"))
        # VST2: a .so file and a folder with a .so inside
        vst = os.path.join(self.lib, "vst")
        touch(os.path.join(vst, "reaeq.so"))
        touch(os.path.join(vst, "carla.vst", "CarlaRack.so"))
        touch(os.path.join(vst, "notes.txt"))

    def tearDown(self):
        if self.old_home is None:
            del os.environ["HOME"]
        else:
            os.environ["HOME"] = self.old_home
        self.tmp.cleanup()

    def states(self, fmt):
        res = links.check(fmt, self.roots)
        return {name: state for _, name, state, _ in res["system"]}, res

    def test_lv2_states(self):
        st, res = self.states("lv2")
        self.assertEqual(st, {"calf.lv2": "linked", "x42.lv2": "missing",
                              "yoshimi.lv2": "copy", "zyn.lv2": "other"})
        self.assertEqual([os.path.basename(p) for p, _ in res["broken"]],
                         ["zyn.lv2"])
        self.assertEqual([os.path.basename(p) for p, _ in res["elsewhere"]],
                         ["my.lv2"])

    def test_vst2_entries(self):
        st, _ = self.states("vst2")
        self.assertEqual(st, {"carla.vst": "missing", "reaeq.so": "missing"})

    def test_make_link(self):
        src = os.path.join(self.lib, "vst", "reaeq.so")
        dst = links.make_link("vst2", src)
        self.assertEqual(dst, os.path.join(self.home, ".vst", "reaeq.so"))
        self.assertEqual(os.path.realpath(dst), os.path.realpath(src))
        self.assertIsNone(links.make_link("vst2", src))
        st, _ = self.states("vst2")
        self.assertEqual(st["reaeq.so"], "linked")

    def test_home_dir_is_link(self):
        os.symlink(os.path.join(self.lib, "vst"),
                   os.path.join(self.home, ".vst"))
        st, _ = self.states("vst2")
        self.assertEqual(set(st.values()), {"dirlink"})


if __name__ == "__main__":
    unittest.main()
