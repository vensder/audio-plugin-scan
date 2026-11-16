"""Run: python3 -m unittest discover -s tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audioplug import virus  # noqa: E402

HEAD = b"\xf0\x00\x20\x33\x01\x10"


def dump(cmd, bank, prog, data):
    return HEAD + bytes([cmd, bank, prog]) + bytes(data) + b"\x00\xf7"


def state():
    m = [0] * 256
    m[4:14] = b"Test Multi"
    for p in range(16):
        m[virus.CHANNEL + p] = p
        m[virus.OUTPUT + p] = 1
    m[virus.OUTPUT + 1] = 7          # part 2: Out 3 L+R
    single = [0] * 512
    single[virus.NAME:virus.NAME + 10] = b"Astr@     "
    stored = list(m)
    stored[virus.OUTPUT] = 4          # a stored Multi (bank 1): ignored
    return (b"DSP56300junk" + dump(0x11, 1, 0, stored) + dump(0x11, 0, 0, m)
            + dump(0x10, 0, 1, single) + b"GAIN")


class TestVirus(unittest.TestCase):
    def test_multi(self):
        vm = virus.multi(state())
        self.assertEqual(vm["name"], "Test Multi")
        p1, p2 = vm["parts"][:2]
        self.assertEqual((p1["channel"], p1["output"]), (1, 1))
        self.assertEqual((p2["channel"], p2["output"], p2["patch"]),
                         (2, 7, "Astr@"))

    def test_outputs(self):
        self.assertEqual(virus.output_name(1), "Out 1 L+R")
        self.assertEqual(virus.output_name(7), "Out 3 L+R")
        self.assertEqual(virus.output_name(3), "Out 2 L")
        self.assertEqual(virus.output_channels(4), (2, 2))
        self.assertEqual(virus.output_channels(5), (3, 1))

    def test_no_state(self):
        self.assertIsNone(virus.multi(b"nothing here"))


if __name__ == "__main__":
    unittest.main()
