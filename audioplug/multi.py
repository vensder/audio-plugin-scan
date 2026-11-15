"""One multitimbral instrument played by several MIDI tracks.

Each instance of a DSP emulator such as OsTIrus (Gearmulator Virus TI)
uses CPU all the time, even when silent. The Virus has a Multi mode with
up to 16 parts, each on its own MIDI channel, so one instance can play
several parts:

    1 OsTIrus (multi)   the instrument, receives MIDI from:
    2   Noomed2Chord    MIDI only, send -> channel 1
    3   AftrglowMS      MIDI only, send -> channel 2

make() takes an existing project, finds the tracks with the instrument
and rewrites them into this layout: the first instance moves to a new
instrument track (with its saved state), the old tracks keep their MIDI
items and only send MIDI. With empty=True, only the instrument track and
empty MIDI tracks are written (a template).

REAPER stores plugin state as binary data that cannot be written by
hand, which is why the instrument is copied from an existing project.
"""

import copy
import os
import uuid

from . import rpp

MAX_PARTS = 16
# REC armed input monitor ...: input 6112 = MIDI, all devices, all channels.
MIDI_INPUT = 4096 + (63 << 5)


def guid():
    return "{%s}" % str(uuid.uuid4()).upper()


def track_name(t):
    return (t.value("NAME") or [""])[0]


def chain_fx(track):
    """Plugin dicts of the FX in a track's FX chain."""
    out = []
    for chain in track.nodes("FXCHAIN"):
        for n in chain.nodes():
            w = rpp.plugin(n) if n.tag in rpp.FX_TAGS else None
            if w:
                out.append(w)
    return out


def instrument_fx(track, plugin):
    """Plugin dicts of the FX in a track's chain whose name has plugin."""
    want = plugin.lower()
    return [w for w in chain_fx(track)
            if want in (w["name"] + " " + w["display"]).lower()]


def set_line(node, key, value):
    """Replace the first 'KEY ...' line, or add it before the blocks."""
    line = key + " " + value
    for i, it in enumerate(node.items):
        if isinstance(it, str) and (it == key or it.startswith(key + " ")):
            node.items[i] = line
            return
    for i, it in enumerate(node.items):
        if isinstance(it, rpp.Node):
            node.items.insert(i, line)
            return
    node.items.append(line)


def drop(node, keys=(), tags=()):
    node.items = [it for it in node.items
                  if not (isinstance(it, str) and it.split(" ", 1)[0] in keys)
                  and not (isinstance(it, rpp.Node) and it.tag in tags)]


def receive(src, channel):
    """AUXRECV line: MIDI only (audio: none), all channels -> channel.

    Fields: source track (0-based), mode (0 = post-fader), volume, pan,
    mute, mono, phase, source audio channels (-1 = none), destination
    channels, pan law, MIDI (source channel | destination channel << 5),
    automation mode.
    """
    return "AUXRECV %d 0 1 0 0 0 0 -1 0 -1:U %d -1 ''" % (src, channel << 5)


def midi_track(t, armed=None):
    """Turn a track into a MIDI-only track: no FX, no master send, MIDI
    input with monitoring (so playing the keyboard reaches the synth)."""
    drop(t, keys=("FX",), tags=("FXCHAIN", "PARMENV"))
    set_line(t, "MAINSEND", "0 0")
    rec = t.value("REC") or []
    arm = armed if armed is not None else (rec[0] if rec else "0")
    rest = rec[3:] if len(rec) > 3 else ["0", "0", "0", "0", "0"]
    set_line(t, "REC", " ".join([arm, str(MIDI_INPUT), "1"] + rest))


def new_midi_track(name):
    g = guid()
    t = rpp.Node("TRACK", [g], "<TRACK " + g)
    t.items = ["NAME " + rpp_str(name), "TRACKID " + g, "ISBUS 0 0"]
    midi_track(t, armed="0")
    return t


def rpp_str(s):
    for q in ('"', "'", "`"):
        if q not in s:
            return q + s + q
    return '"' + s.replace('"', "'") + '"'


def remap_receives(t, index):
    """Renumber AUXRECV sources after tracks moved; index[old] = new.
    Receives that end up twice from the same track are dropped."""
    seen = set()
    items = []
    for it in t.items:
        if isinstance(it, str) and it.startswith("AUXRECV "):
            parts = it.split(" ")
            try:
                parts[1] = str(index[int(parts[1])])
            except (ValueError, KeyError, IndexError):
                pass
            if parts[1] in seen:
                continue
            seen.add(parts[1])
            it = " ".join(parts)
        items.append(it)
    t.items = items


class Result:
    def __init__(self):
        self.project = None      # rpp.Node to write
        self.instrument = ""     # instrument track name
        self.source = ""         # track the instance was taken from
        self.fx = ""             # FX display name
        self.parts = []          # (track name, channel, from source?)
        self.dropped = []        # (track name, FX names) dropped
        self.lines = []          # listing of the new track list


def make(path, plugin="OsTIrus", count=2, empty=False, name=None):
    """Build the multi layout from a project. Raises ValueError when the
    project has no track with plugin, or more parts than MAX_PARTS."""
    project = rpp.read(path)
    tracks = project.nodes("TRACK")
    found = [(i, t, instrument_fx(t, plugin)) for i, t in enumerate(tracks)]
    found = [(i, t, fx) for i, t, fx in found if fx]
    if not found:
        raise ValueError("no track with %s in %s" % (plugin, path))
    first_i, first_t, first_fx = found[0]
    fx_w = first_fx[0]

    r = Result()
    r.source, r.fx = track_name(first_t), fx_w["display"]
    r.instrument = name or "%s (multi)" % fx_w["name"]

    # The instrument track: the first track's settings and FX chain, no
    # items, no receives; MIDI arrives through the new receives below.
    inst = copy.deepcopy(first_t)
    g = guid()
    inst.line, inst.args = "<TRACK " + g, [g]
    set_line(inst, "TRACKID", g)
    set_line(inst, "NAME", rpp_str(r.instrument))
    set_line(inst, "ISBUS", "0 0")
    drop(inst, keys=("AUXRECV",), tags=("ITEM",))
    set_line(inst, "REC", "0 0 1 0 0 0 0 0")

    if (count if empty else max(count, len(found))) > MAX_PARTS:
        raise ValueError("%d parts, the Virus has %d"
                         % (max(count, len(found)), MAX_PARTS))
    if empty:
        n = max(count, 1)
        parts = [new_midi_track("Part %d" % c) for c in range(1, n + 1)]
        r.parts = [("Part %d" % c, c, False) for c in range(1, n + 1)]
        new = [inst] + parts
        project.items = [it for it in project.items
                         if not (isinstance(it, rpp.Node)
                                 and it.tag == "TRACK")]
        project.items += new
        inst_i = 0
        part_idx = list(range(1, n + 1))
    else:
        # FX on the other instrument tracks go away with their instance.
        for i, t, fxs in found[1:]:
            names = [w["name"] for w in chain_fx(t)
                     if plugin.lower() not in w["name"].lower()]
            if names:
                r.dropped.append((track_name(t), names))
        extra = max(0, count - len(found))
        last_i = found[-1][0]
        order = []  # (old index or None, node)
        for i, t in enumerate(tracks):
            if i == first_i:
                order.append((None, inst))
            order.append((i, t))
            if i == last_i:
                for c in range(extra):
                    nm = "Part %d" % (len(found) + c + 1)
                    order.append((None, new_midi_track(nm)))
        inst_i = [k for k, (o, n) in enumerate(order) if n is inst][0]
        index = {o: k for k, (o, n) in enumerate(order) if o is not None}
        for i, t, fxs in found:
            index[i] = inst_i  # sends from the old tracks: now the synth
        # Old tracks' receives stay with them, the audio is now on inst.
        for o, n in order:
            if n is not inst:
                remap_receives(n, index)
        part_idx = []
        for c, (i, t, fxs) in enumerate(found, 1):
            midi_track(t)
            part_idx.append(index_of(order, t))
            r.parts.append((track_name(t), c, True))
        for o, n in order[last_i + 2:last_i + 2 + extra]:
            part_idx.append(index_of(order, n))
            r.parts.append((track_name(n), len(r.parts) + 1, False))
        new = [n for o, n in order]
        pos = [k for k, it in enumerate(project.items)
               if isinstance(it, rpp.Node) and it.tag == "TRACK"]
        head = project.items[:pos[0]]
        tail = project.items[pos[-1] + 1:]
        project.items = head + new + tail

    for c, k in enumerate(part_idx, 1):
        inst.items.insert(_recv_pos(inst), receive(k, c))
    r.project = project
    r.lines = listing(new, inst, part_idx)
    return r


def index_of(order, node):
    return [k for k, (o, n) in enumerate(order) if n is node][0]


def _recv_pos(t):
    """Where AUXRECV lines go: after the last plain line before blocks."""
    k = 0
    for i, it in enumerate(t.items):
        if isinstance(it, rpp.Node):
            break
        k = i + 1
    return k


def listing(tracks, inst, part_idx):
    chan = {k: c for c, k in enumerate(part_idx, 1)}
    out = []
    for k, t in enumerate(tracks):
        if t is inst:
            fx = " -> ".join(w["name"] for w in chain_fx(t))
            out.append("%-3d %s: %s" % (k + 1, track_name(t), fx))
        elif k in chan:
            items = len(t.nodes("ITEM"))
            out.append("%-3d %s: MIDI -> %s ch %d%s" % (
                k + 1, track_name(t), track_name(inst), chan[k],
                ", %d item%s" % (items, "s" if items > 1 else "")
                if items else ""))
    return out


def out_path(path, outfile=None):
    if outfile:
        return outfile
    base, ext = os.path.splitext(path)
    return base + "-multi" + (ext or ".RPP")


def write(r, path):
    text = "\n".join(rpp.dump(r.project)) + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


NOTES = """\
In the synth (once):
  1. Open the FX window of the track "%(inst)s" and switch the
     Virus play mode from Single to Multi.
  2. Load a patch into each of parts 1-%(n)d and check that part N
     listens on MIDI channel N.
%(sound)s  3. Save the project (the Multi is saved in the plugin state).
The sends turn all MIDI of a track into its channel, so the MIDI items do
not need to be changed. All parts play through output 1/2 unless an
output is set per part in the synth.
"""


def notes(r):
    sound = ""
    if any(src for _, _, src in r.parts[1:]):
        sound = ("     Only the instance of \"%s\" was kept. To keep the "
                 "other sounds,\n     save each patch from its instance in "
                 "the old project first.\n" % r.source)
    return NOTES % {"inst": r.instrument, "n": len(r.parts), "sound": sound}

