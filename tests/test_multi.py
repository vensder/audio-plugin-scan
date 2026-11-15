"""Run: python3 -m unittest discover -s tests"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audioplug import multi, rpp  # noqa: E402

VIRUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                     "virus.RPP")


def written(r):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.RPP")
        multi.write(r, path)
        return rpp.read(path)


class TestMulti(unittest.TestCase):
    def test_consolidate(self):
        p = written(multi.make(VIRUS, count=3))
        t = p.nodes("TRACK")
        self.assertEqual([multi.track_name(x) for x in t],
                         ["OsTIrus (multi)", "Noomed2Chord", "AftrglowMS",
                          "Part 3", "Reverb"])
        # one instance left, with the first track's state
        fx = [n for n in p.walk() if n.tag == "CLAP"]
        self.assertEqual(len(fx), 1)
        self.assertEqual(fx[0].nodes("STATE")[0].lines(), ["AAAAstate1=="])
        # MIDI only (audio -1) to channels 1, 2, 3
        recv = [s.split() for s in t[0].lines() if s.startswith("AUXRECV")]
        self.assertEqual([(r[1], r[8], r[11]) for r in recv],
                         [("1", "-1", "32"), ("2", "-1", "64"),
                          ("3", "-1", "96")])
        for x in t[1:4]:
            self.assertEqual(x.value("MAINSEND"), ["0", "0"])
            self.assertFalse(x.nodes("FXCHAIN"))
        self.assertEqual(len(t[1].nodes("ITEM")), 1)
        self.assertFalse(t[0].nodes("ITEM"))
        # Reverb received AftrglowMS (old 1): now the instrument (0)
        self.assertEqual(t[4].value("AUXRECV")[0], "0")

    def test_dropped_fx(self):
        r = multi.make(VIRUS)
        self.assertEqual(r.dropped, [("AftrglowMS", ["ReaEQ"])])

    def test_empty(self):
        p = written(multi.make(VIRUS, count=4, empty=True))
        names = [multi.track_name(x) for x in p.nodes("TRACK")]
        self.assertEqual(names, ["OsTIrus (multi)", "Part 1", "Part 2",
                                 "Part 3", "Part 4"])
        self.assertEqual(p.value("TEMPO"), ["120", "4", "4"])

    def test_outputs(self):
        p = written(multi.make(VIRUS, outputs=3))
        t = p.nodes("TRACK")
        self.assertEqual([multi.track_name(x) for x in t[3:6]],
                         ["OsTIrus out 1/2", "OsTIrus out 3/4",
                          "OsTIrus out 5/6"])
        self.assertEqual(t[0].value("NCHAN"), ["6"])
        self.assertEqual(t[0].value("MAINSEND"), ["0", "0"])
        # audio from pair 3/4 (channel index 2), MIDI none (31)
        r = t[4].value("AUXRECV")
        self.assertEqual((r[0], r[7], r[10]), ("0", "2", "31"))
        self.assertEqual(t[6].value("AUXRECV")[0], "0")  # Reverb

    def test_errors(self):
        with self.assertRaises(ValueError):
            multi.make(VIRUS, plugin="Diva")
        with self.assertRaises(ValueError):
            multi.make(VIRUS, count=17)


if __name__ == "__main__":
    unittest.main()
