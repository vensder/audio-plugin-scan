"""Virus Multi settings inside a Gearmulator plugin state (OsTIrus,
Osirus).

The plugin saves the Virus memory as Access SysEx dumps:

    F0 00 20 33 01 <dev> 11 <bank> <prog> <256 bytes> <sum> F7   Multi
    F0 00 20 33 01 <dev> 10 <bank> <prog> <data> <sum> F7         Single

Bank 0 holds the edit buffers: the Multi in use (prog 0) and the Single
of each part (prog 0-15). Offsets in the Multi data (16 values each, one
per part): 64 MIDI channel (0 = ch 1), 176 output. Single data: name at
240 (10 chars). Found by saving two states that differ in one setting.
"""

import re

_DUMP = re.compile(rb"\xf0\x00\x20\x33\x01[\x00-\x7f]([\x10\x11])"
                   rb"([\x00-\x7f])([\x00-\x7f])([\x00-\x7f]*)\xf7")

CHANNEL, OUTPUT, NAME = 64, 176, 240
OUT_SIDES = ("L", "L+R", "R")


def output_name(v):
    """1 -> 'Out 1 L+R', 7 -> 'Out 3 L+R'; Out 1-3 are 0-8."""
    if 0 <= v < 9:
        return "Out %d %s" % (v // 3 + 1, OUT_SIDES[v % 3])
    return "output %d" % v


def output_channels(v):
    """Plugin output channels (first, count) of an output value, or None."""
    if not 0 <= v < 9:
        return None
    first = (v // 3) * 2
    return {0: (first, 1), 1: (first, 2), 2: (first + 1, 1)}[v % 3]


def text(b):
    return "".join(chr(c) if 32 <= c < 127 else " " for c in b).strip()


def multi(state):
    """{"name": multi name, "parts": [{"part", "channel", "output",
    "patch"} x 16]} from a plugin state (bytes), or None."""
    edit = None
    singles = {}
    for m in _DUMP.finditer(state):
        cmd, bank, prog, data = m.group(1)[0], m.group(2)[0], \
            m.group(3)[0], m.group(4)[:-1]  # last byte: checksum
        if bank != 0:
            continue
        if cmd == 0x11 and prog == 0 and len(data) >= 256:
            edit = data
        elif cmd == 0x10 and prog < 16 and len(data) >= NAME + 10:
            singles[prog] = text(data[NAME:NAME + 10])
    if edit is None:
        return None
    parts = [{"part": p + 1, "channel": edit[CHANNEL + p] + 1,
              "output": edit[OUTPUT + p], "patch": singles.get(p, "")}
             for p in range(16)]
    return {"name": text(edit[4:14]), "parts": parts}
