"""Convert an LMMS project (.mmp / .mmpz) to a REAPER project.

What is converted into the .RPP:
  - tempo and time signature, master volume
  - song editor instrument tracks -> REAPER tracks with one MIDI item per
    LMMS pattern (notes, velocities, mute state)
  - pattern (Beat/Bassline) editor tracks -> a "Pattern editor" folder
    with one track per pattern-editor track; every pattern clip in the
    song becomes MIDI items there (looped like LMMS does)
  - sample tracks -> audio items (when the sample file is found)
  - mixer channels -> bus tracks with sends, the master channel's
    effects go to the REAPER master
  - track volume, pan, mute and solo

Plugins are not written into the .RPP (REAPER keeps a binary state per
plugin that cannot be made by hand). A ReaScript (.lua) is written next
to it instead: run once in REAPER, it adds each track's instrument and
effects through the REAPER API, trying the original plugin first and a
close alternative after that.

Everything else (LMMS-only synth sounds, plugin settings, automation,
arpeggiator) is listed as manual steps by guide().
"""

import gzip
import json
import os
import re
import textwrap
import uuid
import xml.etree.ElementTree as ET

from . import lmms
from .common import HOME, RESULTS_DIR

TICKS_PER_QN = 48           # LMMS: 192 ticks per 4/4 bar
PPQ = 960                   # REAPER MIDI items
SCALE = PPQ // TICKS_PER_QN
STEP = 12                   # one 1/16 step, for LMMS "step" notes (len < 0)

SYNTH_ALT = ["Surge XT"]
INSTRUMENTS = {
    # LMMS built-in instrument: (close alternatives, note)
    "tripleoscillator": (SYNTH_ALT, "3-oscillator subtractive synth"),
    "lb302": (SYNTH_ALT, "303-style bass synth"),
    "bitinvader": (SYNTH_ALT, "drawn-wavetable synth"),
    "monstro": (SYNTH_ALT, "3-oscillator modular synth"),
    "watsyn": (SYNTH_ALT, "4-oscillator wavetable synth"),
    "xpressive": (SYNTH_ALT, "formula synth"),
    "organic": (["setBfree"] + SYNTH_ALT, "additive organ"),
    "sid": (SYNTH_ALT, "C64 SID chip emulation"),
    "papu": (SYNTH_ALT, "Game Boy sound emulation"),
    "freeboy": (SYNTH_ALT, "Game Boy sound emulation"),
    "nes": (SYNTH_ALT, "NES sound emulation"),
    "sfxr": (SYNTH_ALT, "8-bit sound effects"),
    "opl2": (["ADLplug", "OPNplug"], "OPL2 FM chip emulation"),
    "vibedstrings": (SYNTH_ALT, "string physical model"),
    "malletsstk": (SYNTH_ALT, "mallet physical model"),
    "kicker": (["Geonkick"], "kick drum synth"),
    "zynaddsubfx": (["ZynAddSubFX"], "ZynAddSubFX"),
    "sf2player": (["Fluida", "FluidSynth", "Calf Fluidsynth"],
                  "SoundFont player"),
    "gigplayer": (["LinuxSampler"], "GIG player"),
    "patman": ([], "GUS patch player"),
    "audiofileprocessor": (["ReaSamplOmatic5000"], "sample player"),
    "slicert": (["ReaSamplOmatic5000"], "beat slicer"),
}
# Stand-ins that every REAPER has.
SYNTH_STAND_IN = "ReaSynth"

EFFECTS = {
    # LMMS built-in effect: REAPER plugins to try ([] = skip it)
    "eq": ["ReaEQ"], "bassbooster": ["ReaEQ"], "dualfilter": ["ReaEQ"],
    "crossovereq": ["ReaXcomp"], "compressor": ["ReaComp"],
    "dynamicsprocessor": ["ReaComp"], "delay": ["ReaDelay"],
    "multitapecho": ["ReaDelay"], "reverbsc": ["ReaVerbate"],
    "flanger": ["JS: Flanger"], "waveshaper": ["JS: Distortion"],
    "bitcrush": ["JS: Distortion"], "amplifier": ["JS: Volume Adjustment"],
    "granularpitchshifter": ["ReaPitch"],
    "stereoenhancer": [], "stereomatrix": [], "spectrumanalyzer": [],
    "peakcontrollereffect": [],
}
SKIP_NOTES = {
    "spectrumanalyzer": "analyser only, skipped",
    "peakcontrollereffect": "peak controller, use REAPER parameter "
                            "modulation (FX > Param > Parameter modulation)",
    "stereoenhancer": "no stock REAPER equivalent, skipped",
    "stereomatrix": "no stock REAPER equivalent, skipped",
}
# Stock REAPER effects by words in a plugin's name.
KEYWORDS = [
    (r"reverb|verb|plate|hall|room", "ReaVerbate"),
    (r"delay|echo", "ReaDelay"),
    (r"compress|limit|dynamic", "ReaComp"),
    (r"gate", "ReaGate"),
    (r"eq\b|equal|filter|shelf|pass|bass|treble", "ReaEQ"),
    (r"pitch", "ReaPitch"),
    (r"flang", "JS: Flanger"),
    (r"chorus", "JS: Chorus"),
    (r"phaser", "JS: Phaser"),
    (r"distort|satur|drive|crush|shaper|tube|fuzz", "JS: Distortion"),
]

SAMPLE_DIRS = ["~/Documents/lmms/samples", "~/lmms/samples",
               "/usr/share/lmms/samples", "/usr/local/share/lmms/samples"]
AUDIO_TYPES = {".wav": "WAVE", ".ogg": "VORBIS", ".flac": "FLAC",
               ".mp3": "MP3", ".aif": "WAVE", ".aiff": "WAVE"}


# ----------------------------------------------------------------- helpers --

def num(el, name, default=0.0):
    """Attribute value, or the value of a <name value=...> child (LMMS
    writes it that way when the knob is automated or controlled)."""
    if el is None:
        return default
    v = el.get(name)
    if v is None:
        c = el.find(name)
        if c is not None:
            v = c.get("value")
    try:
        return float(v) if v is not None else default
    except ValueError:
        return default


def safe_name(s):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")
    return s or "track"


def stand_in_for(name):
    low = name.lower()
    for rx, fx in KEYWORDS:
        if re.search(rx, low):
            return fx
    return None


def split_camel(s):
    """'VintageDelay' -> 'Vintage Delay', 'Equalizer8Band' ->
    'Equalizer 8 Band'."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", s)
    return re.sub(r"(?<=[0-9])(?=[A-Za-z])", " ", s)


def lv2_names():
    """LV2 URI -> plugin name, from the saved host scans."""
    out = {}
    if not os.path.isdir(RESULTS_DIR):
        return out
    for f in sorted(os.listdir(RESULTS_DIR)):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(RESULTS_DIR, f)) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        for p in data.get("plugins", []):
            if p.get("format") == "lv2" and p.get("id") and p.get("name"):
                out.setdefault(p["id"], p["name"])
    return out


def lmms_sample_dirs():
    """LMMS's own sample folders: the working dir from ~/.lmmsrc.xml
    first, then the usual places."""
    dirs = []
    try:
        rc = ET.parse(os.path.join(HOME, ".lmmsrc.xml")).getroot()
        paths = rc.find("paths")
        if paths is not None and paths.get("workingdir"):
            dirs.append(os.path.join(paths.get("workingdir"), "samples"))
    except (OSError, ET.ParseError):
        pass
    return dirs + [os.path.expanduser(d) for d in SAMPLE_DIRS]


# --------------------------------------------------------------- the song --

class Fx:
    """One plugin the ReaScript adds: try the names in order, then the
    stand-ins (stock REAPER plugins)."""

    def __init__(self, label, names, stand_in=None, on=True, file=None):
        self.label = label
        self.names = [n for n in names if n]
        self.stand_in = [n for n in (stand_in or []) if n and
                         n not in self.names]
        self.on = on
        self.file = file

    def text(self):
        alts = self.names + self.stand_in
        s = self.label
        if alts:
            s += " => " + " | ".join(alts)
        else:
            s += " => (skipped)"
        if not self.on:
            s += " (off)"
        return s


class Track:
    def __init__(self, name, guid):
        self.name, self.guid = name, guid
        self.vol, self.pan = 1.0, 0.0
        self.muted = self.solo = False
        self.folder = 0           # 1 opens a folder, -1 closes one
        self.mixer = 0            # LMMS mixer channel the track goes to
        self.main_send = True
        self.receives = []        # (source track index, volume)
        self.items = []
        self.fx = []
        self.lmms_only = []       # LMMS-only instruments with stand-ins


class Converter:
    def __init__(self, path, outdir, lv2=None):
        self.path = os.path.abspath(path)
        self.outdir = os.path.abspath(outdir)
        self.base = re.sub(r"\.mmpz?$", "", os.path.basename(path), flags=re.I)
        self.root = lmms.read(path)
        self.lv2 = lv2 if lv2 is not None else lv2_names()
        self._sample_dirs = None
        self.files = {}           # output file name -> bytes
        self.notes = {k: [] for k in ("zyn", "carla", "samples", "lmms_only",
                                      "vst_state", "automation", "arp",
                                      "skipped", "other")}
        head = self.root.find("head")
        self.bpm = num(head, "bpm", 120.0) or 120.0
        self.num = int(num(head, "timesig_numerator", 4)) or 4
        self.den = int(num(head, "timesig_denominator", 4)) or 4
        self.tpb = TICKS_PER_QN * 4 * self.num // self.den
        self.master_pitch = int(num(head, "masterpitch", 0))
        self.master_vol = num(head, "mastervol", 100) / 100.0
        self.version = self.root.get("creatorversion", "")
        self.tracks = []
        self.master_fx = []
        self.mixer = {}           # num -> mixer channel element
        self._parents = None
        self.build()

    # ------------------------------------------------------------ timing --
    def sec(self, ticks):
        return ticks * 60.0 / (self.bpm * TICKS_PER_QN)

    def bar(self, ticks):
        return ticks // self.tpb + 1

    def guid(self, n):
        u = uuid.uuid5(uuid.NAMESPACE_URL, "%s#%s" % (self.path, n))
        return "{%s}" % str(u).upper()

    def full_bars(self, ticks):
        bars = max(1, -(-ticks // self.tpb))
        return bars * self.tpb

    # ---------------------------------------------------------- patterns --
    def pattern_notes(self, pat):
        out = []
        for n in pat.findall("note"):
            ln = int(num(n, "len", 0))
            if ln == 0:
                continue
            out.append((int(num(n, "pos", 0)), ln if ln > 0 else STEP,
                        int(num(n, "key", 57)), num(n, "vol", 100)))
        return out

    def pattern_len(self, pat):
        """Length of an LMMS pattern in ticks, as LMMS computes it."""
        if pat.get("len"):
            return int(num(pat, "len", 0)) or self.tpb
        if pat.get("type", "1") == "0":     # beat pattern
            steps = int(num(pat, "steps", 16)) or 16
            return self.full_bars(steps * self.tpb // 16)
        end = max([p + ln for p, ln, _, _ in self.pattern_notes(pat)] or [0])
        return self.full_bars(end)

    def midi_item(self, name, pos, length, notes, pitch, muted=False):
        """notes: (pos in item, len, LMMS key, LMMS vol), ticks."""
        ev = []
        for p, ln, key, vol in notes:
            if p < 0 or p >= length:
                continue
            ln = min(ln, length - p)
            k = max(0, min(127, key + pitch))
            v = max(1, min(127, int(round(vol * 127 / 200.0))))
            ev.append((p * SCALE, 1, k, v))
            ev.append(((p + ln) * SCALE, 0, k, 0))
        if not ev:
            return None
        ev.sort(key=lambda e: (e[0], e[1]))
        return {"name": name, "pos": self.sec(pos), "len": self.sec(length),
                "muted": muted, "midi": ev, "end": length * SCALE}

    # ------------------------------------------------------------ plugins --
    def lv2_name(self, uri):
        if uri in self.lv2:
            return self.lv2[uri]
        return lmms._uri_name(uri)

    def write_file(self, name, data):
        base, ext = os.path.splitext(name)
        n, i = name, 2
        while n in self.files:
            n = "%s-%d%s" % (base, i, ext)
            i += 1
        self.files[n] = data
        return os.path.join(self.outdir, n)

    def find_sample(self, src):
        if not src:
            return None
        src = os.path.expanduser(src)
        if os.path.isabs(src):
            return src if os.path.exists(src) else None
        if self._sample_dirs is None:
            self._sample_dirs = [os.path.dirname(self.path)] + \
                lmms_sample_dirs()
        for d in self._sample_dirs:
            p = os.path.join(d, src)
            if os.path.exists(p):
                return p
        return None

    def external(self, w, instrument, on=True):
        """Fx for an external plugin (lmms.wants() / carla.plugins())."""
        name = w["name"]
        if w["format"] == "lv2" and not w.get("inside"):
            name = self.lv2_name(w["key"])   # Carla saves the real name
        names = [name]
        if w["format"] == "ladspa":
            # REAPER has no LADSPA host: try the LV2 ports by name.
            label = w.get("label", "").split("/", 1)[-1]
            lib = w["key"]
            if lib in ("calf", "veal"):
                names = ["Calf " + split_camel(label)]
            elif lib == "caps":
                names = ["C* " + label]
            else:
                names = [split_camel(label)]
            name = label
        if instrument:
            stand = [SYNTH_STAND_IN]
        else:
            stand = [stand_in_for(name + " " + w.get("label", ""))]
        label = w.get("label") or name
        if w.get("inside"):
            label = "%s > %s" % (w["inside"], name)
        return Fx(label, names, stand, on)

    def instrument(self, el, track):
        kind = el.get("name", "")
        if kind.startswith("carla"):
            return self.carla(el, track, True)
        ws = lmms.wants(el)
        if ws and not ws[0].get("unchecked"):
            fx = self.external(ws[0], True)
            if kind == "vestige":
                self.notes["vst_state"].append(
                    "%s: %s (choose the preset / program again)"
                    % (track.name, fx.names[0]))
            return [fx]
        alts, desc = INSTRUMENTS.get(kind, ([], "LMMS instrument"))
        sub = el.find(kind)
        if kind == "zynaddsubfx":
            data = sub.find("ZynAddSubFX-data") if sub is not None else None
            if data is not None:
                xml = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
                       b'<!DOCTYPE ZynAddSubFX-data>\n'
                       + ET.tostring(data, encoding="utf-8"))
                p = self.write_file(safe_name(track.name) + ".xmz",
                                    gzip.compress(xml))
                self.notes["zyn"].append((track.name, os.path.basename(p)))
            return [Fx("zynaddsubfx", alts, [SYNTH_STAND_IN])]
        if kind in ("audiofileprocessor", "slicert"):
            src = sub.get("src", "") if sub is not None else ""
            path = self.find_sample(src)
            if src.lower().endswith(".ds"):
                track.lmms_only.append("%s with DrumSynth file %s (REAPER "
                                       "cannot play .ds)" % (kind, src))
                path = None
            elif src and not path:
                self.notes["samples"].append("%s: %s (not found)"
                                             % (track.name, src))
            if kind == "slicert":
                track.lmms_only.append("slicert (beat slicer)")
            return [Fx(kind, alts, None, file=path)]
        if kind == "sf2player" and sub is not None and sub.get("src"):
            self.notes["other"].append("%s: SoundFont %s (load it in the "
                                       "SoundFont player)"
                                       % (track.name, sub.get("src")))
        track.lmms_only.append("%s (%s)" % (kind, desc))
        return [Fx(kind, alts, [SYNTH_STAND_IN])]

    def effect(self, el, track_name, on):
        kind = el.get("name", "")
        if kind.startswith("carla"):
            fxs = self.carla(el, None, False, track_name)
            for f in fxs:
                f.on = f.on and on
            return fxs
        ws = lmms.wants(el)
        if ws and not ws[0].get("unchecked"):
            return [self.external(ws[0], False, on)]
        names = EFFECTS.get(kind)
        if names == []:
            self.notes["skipped"].append("%s: %s (%s)" % (
                track_name, kind, SKIP_NOTES.get(kind, "skipped")))
            return []
        if names is None:
            names = [n for n in [stand_in_for(kind)] if n]
            if not names:
                self.notes["skipped"].append(
                    "%s: %s (no REAPER equivalent known)" % (track_name, kind))
                return []
        return [Fx(kind, [], names, on)]

    def carla(self, el, track, instrument, track_name=None):
        """Plugins inside a Carla rack are added directly; Carla's own
        project (with every plugin's settings) is saved as .carxp."""
        name = track.name if track else track_name
        proj = el.find(".//CARLA-PROJECT")
        if proj is not None:
            xml = (b"<?xml version='1.0' encoding='UTF-8'?>\n"
                   b"<!DOCTYPE CARLA-PROJECT>\n"
                   + ET.tostring(proj, encoding="utf-8"))
            p = self.write_file(safe_name(name) + ".carxp", xml)
            host = "Carla-Patchbay" if "patchbay" in el.get("name", "") \
                else "Carla-Rack"
            self.notes["carla"].append((name, host, os.path.basename(p)))
        out = []
        for i, w in enumerate(lmms.wants(el)):
            out.append(self.external(w, instrument and i == 0,
                                     w.get("active", True)))
        return out

    def chain(self, parent, name):
        """Effects of the <fxchain> under parent."""
        fc = parent.find("fxchain") if parent is not None else None
        if fc is None:
            return []
        chain_on = fc.get("enabled", "1") != "0"
        out = []
        for e in fc.findall("effect"):
            out += self.effect(e, name, chain_on and e.get("on", "1") != "0")
        return out

    # ------------------------------------------------------------- tracks --
    def track_common(self, t, body, n):
        tr = Track(t.get("name", "") or "Track %d" % n, self.guid(n))
        tr.vol = num(body, "vol", 100) / 100.0
        tr.pan = max(-1.0, min(1.0, num(body, "pan", 0) / 100.0))
        tr.muted = t.get("muted", "0") == "1"
        tr.solo = t.get("solo", "0") == "1"
        ch = body.get("mixch", body.get("fxch"))
        tr.mixer = int(ch) if ch and ch.isdigit() else 0
        return tr

    def pitch(self, body):
        p = 69 - int(num(body, "basenote", 57))
        if body.get("usemasterpitch", "1") != "0":
            p += self.master_pitch
        return p

    def instrument_track(self, t, n):
        body = t.find("instrumenttrack")
        tr = self.track_common(t, body, n)
        inst = body.find("instrument")
        if inst is not None:
            tr.fx += self.instrument(inst, tr)
        tr.fx += self.chain(body, tr.name)
        for tag, what in (("arpeggiator", "arp-enabled"),
                          ("chordcreator", "chord-enabled")):
            if num(body.find(tag), what, 0):
                self.notes["arp"].append("%s: LMMS %s is on" % (
                    tr.name, "arpeggiator" if tag == "arpeggiator"
                    else "chord stacking"))
        if tr.lmms_only:
            self.notes["lmms_only"].append((tr.name, tr.lmms_only))
        return tr, self.pitch(body)

    def song_patterns(self, t, tr, pitch):
        for pat in list(t.findall("pattern")) + list(t.findall("midiclip")):
            pos = int(num(pat, "pos", 0))
            item = self.midi_item(pat.get("name", "") or tr.name, pos,
                                  self.pattern_len(pat),
                                  self.pattern_notes(pat), pitch,
                                  pat.get("muted", "0") == "1")
            if item:
                tr.items.append(item)

    def sample_track(self, t, n):
        body = t.find("sampletrack")
        tr = self.track_common(t, body, n)
        tr.fx += self.chain(body, tr.name)
        for clip in list(t.findall("sampletco")) + \
                list(t.findall("sampleclip")):
            src = clip.get("src", "")
            pos = int(num(clip, "pos", 0))
            length = int(num(clip, "len", 0))
            path = self.find_sample(src)
            if not path:
                self.notes["samples"].append(
                    "%s: %s at bar %d (%s)" % (
                        tr.name, src or "embedded sample", self.bar(pos),
                        "not found" if src else
                        "export it from LMMS"))
                continue
            ext = os.path.splitext(path)[1].lower()
            tr.items.append({"name": os.path.basename(path),
                             "pos": self.sec(pos), "len": self.sec(length),
                             "muted": clip.get("muted", "0") == "1",
                             "audio": path,
                             "type": AUDIO_TYPES.get(ext, "WAVE")})
        return tr

    def build(self):
        s = self.root.find("song")
        main = s.find("trackcontainer") if s is not None else None
        if main is None:
            return
        n = 0
        song_tracks = main.findall("track")
        pattern_tracks = []       # (bb track element, index)
        container = None
        for t in song_tracks:
            kind = lmms.TRACK_TYPES.get(t.get("type", ""), "other")
            n += 1
            if kind == "instrument" and t.find("instrumenttrack") is not None:
                tr, pitch = self.instrument_track(t, n)
                self.song_patterns(t, tr, pitch)
                self.tracks.append(tr)
            elif kind == "sample" and t.find("sampletrack") is not None:
                self.tracks.append(self.sample_track(t, n))
            elif kind == "pattern":
                pattern_tracks.append(t)
                if container is None:
                    container = t.find(".//trackcontainer")
        if container is not None:
            self.pattern_editor(container, pattern_tracks, n)
        self.automation()
        self.mixer_buses(s)

    def pattern_editor(self, container, bb_tracks, n):
        """One REAPER track per pattern-editor track; each pattern clip in
        the song editor becomes an item on each of them."""
        ctracks = []
        for t in container.findall("track"):
            if t.find("instrumenttrack") is None:
                continue
            n += 1
            tr, pitch = self.instrument_track(t, n)
            pats = list(t.findall("pattern")) + list(t.findall("midiclip"))
            ctracks.append((tr, pitch, pats))
        if not ctracks:
            return
        # Pattern number i: the i-th pattern of every track; it loops at
        # the length of its longest track pattern (full bars).
        lengths = {}
        for _, _, pats in ctracks:
            for i, p in enumerate(pats):
                lengths[i] = max(lengths.get(i, self.tpb),
                                 self.pattern_len(p))
        lengths = {i: self.full_bars(v) for i, v in lengths.items()}
        for bb, t in enumerate(bb_tracks):
            muted = t.get("muted", "0") == "1"
            clips = list(t.findall("bbtco")) + list(t.findall("patternclip"))
            for clip in clips:
                pos = int(num(clip, "pos", 0))
                length = int(num(clip, "len", 0)) or self.tpb
                cmuted = muted or clip.get("muted", "0") == "1"
                loop = lengths.get(bb, self.tpb)
                for tr, pitch, pats in ctracks:
                    if bb >= len(pats) or pats[bb].get("muted", "0") == "1":
                        continue
                    base = self.pattern_notes(pats[bb])
                    notes = [(off + p, ln, k, v)
                             for off in range(0, length, loop)
                             for p, ln, k, v in base]
                    item = self.midi_item(t.get("name", "") or "Pattern",
                                          pos, length, notes, pitch, cmuted)
                    if item:
                        tr.items.append(item)
        n += 1
        folder = Track("Pattern editor", self.guid(n))
        folder.folder = 1
        self.tracks.append(folder)
        for tr, _, _ in ctracks:
            self.tracks.append(tr)
        ctracks[-1][0].folder = -1

    # ------------------------------------------------------------- mixer --
    def mixer_buses(self, s):
        mixer = s.find("mixer")
        if mixer is None:
            mixer = s.find("fxmixer")
        chans = {}
        if mixer is not None:
            for c in mixer:
                if c.tag in ("mixerchannel", "fxchannel"):
                    chans[int(num(c, "num", 0))] = c
        master = chans.get(0)
        if master is not None:
            self.master_vol *= num(master, "volume", 1.0)
            self.master_fx = self.chain(master, "Master")

        def sends(c):
            out = [(int(num(x, "channel", 0)), num(x, "amount", 1.0))
                   for x in c.findall("send")]
            return out or [(0, 1.0)]

        # Buses: channels used by a track, and the channels those send to.
        used = set()
        todo = [t.mixer for t in self.tracks if t.mixer]
        while todo:
            ch = todo.pop()
            if ch in used or ch == 0:
                continue
            used.add(ch)
            if ch in chans:
                todo += [d for d, _ in sends(chans[ch])]
        index = {}
        n = 10000
        for ch in sorted(used):
            c = chans.get(ch)
            label = c.get("name") if c is not None and c.get("name") \
                else "Channel %d" % ch
            n += 1
            bus = Track("Mixer %d: %s" % (ch, label), self.guid(n))
            if c is not None:
                bus.vol = num(c, "volume", 1.0)
                bus.muted = c.get("muted", "0") == "1"
                bus.solo = c.get("soloed", c.get("solo", "0")) == "1"
                bus.fx = self.chain(c, bus.name)
            index[ch] = len(self.tracks)
            self.tracks.append(bus)
        for i, tr in enumerate(self.tracks):
            if tr.mixer in index:
                tr.main_send = False
                self.tracks[index[tr.mixer]].receives.append((i, 1.0))
        for ch, i in index.items():
            c = chans.get(ch)
            out = sends(c) if c is not None else [(0, 1.0)]
            self.tracks[i].main_send = any(d == 0 for d, _ in out)
            for d, amount in out:
                if d in index:
                    self.tracks[index[d]].receives.append((i, amount))

    # -------------------------------------------------------- automation --
    def describe(self, oid):
        if self._parents is None:
            self._parents = {}
            self._ids = {}
            for p in self.root.iter():
                for c in p:
                    self._parents[c] = p
                    if c.get("id") and c.tag != "object":
                        self._ids[c.get("id")] = c
        el = self._ids.get(oid)
        if el is None:
            return "unknown control %s" % oid
        param = el.tag
        if param == "data" and el in self._parents:
            param = self._parents[el].tag
        where = []
        p = self._parents.get(el)
        while p is not None:
            if p.tag in ("effect", "instrument") and p.get("name"):
                where.append(p.get("name"))
            elif p.tag == "track":
                where.append(p.get("name", ""))
                break
            elif p.tag in ("fxchannel", "mixerchannel"):
                where.append("Mixer %s %s" % (p.get("num", ""),
                                              p.get("name", "")))
                break
            elif p.tag == "head":
                where.append("Song")
                break
            p = self._parents.get(p)
        return "%s: %s" % (" > ".join(reversed(where)) or "?", param)

    def automation(self):
        for clip in list(self.root.iter("automationpattern")) + \
                list(self.root.iter("automationclip")):
            objs = [o.get("id") for o in clip.findall("object")]
            if not objs or not clip.findall("time"):
                continue
            pos = int(num(clip, "pos", 0))
            length = int(num(clip, "len", 0))
            targets = sorted({self.describe(o) for o in objs})
            self.notes["automation"].append(
                "bars %d-%d \"%s\": %s" % (
                    self.bar(pos), self.bar(max(pos, pos + length - 1)),
                    clip.get("name", ""), ", ".join(targets)))

    # ------------------------------------------------------------- output --
    def rpp(self):
        out = ['<REAPER_PROJECT 0.1 "7.0/linux-x86_64" 0',
               "  TEMPO %s %d %d" % (fmt(self.bpm), self.num, self.den),
               "  MASTER_VOLUME %s 0 -1 -1 1" % fmt(self.master_vol)]
        for tr in self.tracks:
            out += track_rpp(tr)
        out.append(">")
        return "\n".join(out) + "\n"

    def lua(self):
        plan = []
        if self.master_fx:
            plan.append("  {master = true, name = \"Master\", fx = {\n%s  }},"
                        % fx_lua(self.master_fx))
        for tr in self.tracks:
            if tr.fx:
                plan.append("  {guid = %s, name = %s, fx = {\n%s  }},"
                            % (lua_str(tr.guid), lua_str(tr.name),
                               fx_lua(tr.fx)))
        return LUA_TEMPLATE % {"project": lua_str(os.path.basename(self.path)),
                               "plan": "\n".join(plan)}


def fmt(x):
    s = ("%.10f" % x).rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def rpp_str(s):
    s = s.replace("\n", " ")
    for q in ('"', "'", "`"):
        if q not in s:
            return q + s + q
    return '"' + s.replace('"', "'") + '"'


def track_rpp(tr):
    out = ["  <TRACK %s" % tr.guid,
           "    NAME %s" % rpp_str(tr.name),
           "    TRACKID %s" % tr.guid,
           "    VOLPAN %s %s -1 -1 1" % (fmt(tr.vol), fmt(tr.pan)),
           "    MUTESOLO %d %d 0" % (tr.muted, 2 if tr.solo else 0),
           "    ISBUS %s" % {1: "1 1", -1: "2 -1"}.get(tr.folder, "0 0"),
           "    MAINSEND %d 0" % tr.main_send]
    for src, vol in tr.receives:
        out.append("    AUXRECV %d 0 %s 0 0 0 0 0 0 -1:U 0 -1 ''"
                   % (src, fmt(vol)))
    for it in tr.items:
        out += ["    <ITEM",
                "      POSITION %s" % fmt(it["pos"]),
                "      LENGTH %s" % fmt(it["len"]),
                "      LOOP 0",
                "      MUTE %d 0" % it["muted"],
                "      NAME %s" % rpp_str(it["name"])]
        if "audio" in it:
            out += ["      <SOURCE %s" % it["type"],
                    "        FILE %s" % rpp_str(it["audio"]),
                    "      >"]
        else:
            out += ["      <SOURCE MIDI", "        HASDATA 1 %d QN" % PPQ]
            last = 0
            for t, on, key, vel in it["midi"]:
                out.append("        E %d %s %02x %02x"
                           % (t - last, "90" if on else "80", key, vel))
                last = t
            out += ["        E %d b0 7b 00" % max(0, it["end"] - last),
                    "      >"]
        out.append("    >")
    out.append("  >")
    return out


def lua_str(s):
    return '"%s"' % (s.replace("\\", "\\\\").replace('"', '\\"')
                     .replace("\n", "\\n"))


def fx_lua(fxs):
    out = []
    for f in fxs:
        parts = ["label = %s" % lua_str(f.label),
                 "try = {%s}" % ", ".join(lua_str(n) for n in f.names),
                 "stand_in = {%s}" % ", ".join(lua_str(n)
                                               for n in f.stand_in),
                 "on = %s" % ("true" if f.on else "false")]
        if f.file:
            parts.append("file = %s" % lua_str(f.file))
        out.append("    {%s},\n" % ", ".join(parts))
    return "".join(out)


LUA_TEMPLATE = r'''-- Adds the plugins of the LMMS project %(project)s
-- to the tracks of the open (converted) REAPER project.
-- Written by lmms2rpp (audio-plugin-scan). Run it once:
-- Actions > Show action list > New action > Load ReaScript..., then Run.
-- For each plugin the names in "try" are tried in order, then the
-- stock REAPER stand-ins. The ReaScript console lists what was added.

local plan = {
%(plan)s
}

local function msg(s) reaper.ShowConsoleMsg(s .. "\n") end

local function find_track(guid)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    if reaper.GetTrackGUID(tr) == guid then return tr end
  end
end

local function add(tr, names)
  for _, n in ipairs(names) do
    local idx = reaper.TrackFX_AddByName(tr, n, false, -1)
    if idx >= 0 then return idx, n end
  end
  return -1
end

local added, stand, missing = 0, 0, 0
reaper.Undo_BeginBlock()
for _, t in ipairs(plan) do
  local tr = t.master and reaper.GetMasterTrack(0) or find_track(t.guid)
  if not tr then
    msg(t.name .. ": track not found, is the converted project open?")
  elseif reaper.TrackFX_GetCount(tr) > 0 then
    msg(t.name .. ": has plugins already, skipped")
  else
    for _, fx in ipairs(t.fx) do
      local idx, name = add(tr, fx.try)
      local how = ""
      if idx < 0 then
        idx, name = add(tr, fx.stand_in)
        how = " (stand-in)"
      end
      if idx < 0 then
        missing = missing + 1
        msg(t.name .. ": " .. fx.label .. " -> NOT FOUND (tried: " ..
            table.concat(fx.try, ", ") .. ")")
      else
        if how == "" then added = added + 1 else stand = stand + 1 end
        if fx.file then
          reaper.TrackFX_SetNamedConfigParm(tr, idx, "FILE0", fx.file)
          reaper.TrackFX_SetNamedConfigParm(tr, idx, "DONE", "")
        end
        if not fx.on then reaper.TrackFX_SetEnabled(tr, idx, false) end
        msg(t.name .. ": " .. fx.label .. " -> " .. name .. how)
      end
    end
  end
end
reaper.Undo_EndBlock("Add plugins from LMMS project", -1)
msg(string.format("Done: %%d added, %%d stand-ins, %%d not found. " ..
                  "Save the project (Ctrl+S).", added, stand, missing))
'''


# -------------------------------------------------------------- the guide --

def chain_text(fxs):
    return " -> ".join(f.text() for f in fxs)


def guide(c, rpp_path, lua_path):
    """Step-by-step text for the parts that need hands in REAPER."""
    L = []
    L.append("LMMS %s project %s" % (c.version or "?", c.path))
    L.append("%s BPM, %d/%d, %d REAPER tracks" % (fmt(c.bpm), c.num, c.den,
                                                   len(c.tracks)))
    L.append("")
    L.append("Tracks (LMMS plugin => plugins the script tries, in order; "
             "the last ones are stock REAPER stand-ins):")
    width = len(str(len(c.tracks)))
    depth = 0
    for i, tr in enumerate(c.tracks, 1):
        tags = []
        if tr.mixer:
            tags.append("-> mixer %d" % tr.mixer)
        if tr.muted:
            tags.append("muted")
        if tr.solo:
            tags.append("solo")
        midi = sum(1 for it in tr.items if "midi" in it)
        audio = len(tr.items) - midi
        if midi:
            tags.append("%d MIDI item%s" % (midi, "s" if midi > 1 else ""))
        if audio:
            tags.append("%d audio item%s" % (audio, "s" if audio > 1 else ""))
        line = "%*d %s%s" % (width, i, "  " * depth, tr.name)
        if tags:
            line += " [%s]" % ", ".join(tags)
        if tr.fx:
            line += ": " + chain_text(tr.fx)
        L.append("  " + line)
        if tr.folder == 1:
            depth += 1
        elif tr.folder == -1:
            depth = max(0, depth - 1)
    if c.master_fx:
        L.append("  Master: " + chain_text(c.master_fx))
    L.append("")
    L.append("Steps:")
    steps = []
    L.append("Files are in %s" % c.outdir)
    steps.append(["Open %s in REAPER." % os.path.basename(rpp_path)])
    steps.append(["Add the plugins: Actions > Show action list > New action "
                  "> Load ReaScript..., choose %s and press Run."
                  % os.path.basename(lua_path),
                  "The ReaScript console lists each plugin "
                  "added, the stand-ins used and what was not found "
                  "(install it, e.g. with plugin-helper, and add it by "
                  "hand). Plugins start with their default settings."])
    if c.notes["zyn"]:
        s = ["ZynAddSubFX sounds: open each track's ZynAddSubFX window, "
             "File > Open Parameters... (Load Scene) and choose its file:"]
        s += ["   %s: %s" % x for x in c.notes["zyn"]]
        steps.append(s)
    if c.notes["carla"]:
        s = ["Carla racks: the plugins inside them were added to the track "
             "directly (default settings). To get the saved settings "
             "back, replace them with Carla's plugin (Carla-Rack / "
             "Carla-Patchbay) and load the saved Carla project in it "
             "(File > Open...):"]
        s += ["   %s: %s, %s" % x for x in c.notes["carla"]]
        steps.append(s)
    if c.notes["samples"]:
        s = ["Samples to check (sample tracks and AudioFileProcessor; "
             "found samples were loaded already):"]
        s += ["   " + x for x in c.notes["samples"]]
        steps.append(s)
    if c.notes["lmms_only"]:
        s = ["LMMS-only instruments (a stand-in synth plays the MIDI): to "
             "keep the original sound, render them in LMMS with File > "
             "Export Tracks... (one WAV per track), then in REAPER put "
             "each WAV on its track at the project start (Insert > Media "
             "file...) and mute that track's MIDI items:"]
        for name, descs in c.notes["lmms_only"]:
            s.append("   %s: %s" % (name, ", ".join(descs)))
        steps.append(s)
    if c.notes["vst_state"]:
        s = ["VST instruments start with their default sound; choose the "
             "preset again:"]
        s += ["   " + x for x in c.notes["vst_state"]]
        steps.append(s)
    manual = []
    if c.notes["automation"]:
        manual.append("   Automation (draw it as REAPER envelopes; tempo "
                      "changes go to the master track's Tempo map):")
        manual += ["     " + x for x in c.notes["automation"]]
    if c.notes["arp"]:
        manual.append("   Arpeggiator / chords (the MIDI has the plain "
                      "notes; add JS: MIDI Arpeggiator or render the "
                      "track):")
        manual += ["     " + x for x in c.notes["arp"]]
    if c.notes["skipped"]:
        manual.append("   LMMS effects not added:")
        manual += ["     " + x for x in c.notes["skipped"]]
    if c.notes["other"]:
        manual.append("   Other:")
        manual += ["     " + x for x in c.notes["other"]]
    if manual:
        steps.append(["Not converted, redo by hand if needed:"] + manual)
    steps.append(["Effect settings (EQ curves, reverb sizes, ...) are not "
                  "carried over: compare with LMMS by ear, then save the "
                  "project (Ctrl+S)."])
    for i, s in enumerate(steps, 1):
        L += textwrap.wrap(s[0], 76, initial_indent="%d. " % i,
                           subsequent_indent="   ", break_on_hyphens=False)
        for x in s[1:]:
            if x.startswith(" "):
                L.append("   " + x)
            else:
                L += textwrap.wrap(x, 76, initial_indent="   ",
                                   subsequent_indent="   ",
                                   break_on_hyphens=False)
    return "\n".join(L) + "\n"


def convert(path, outdir=None, write=True):
    """Convert one project. Returns (converter, guide text)."""
    base = re.sub(r"\.mmpz?$", "", os.path.basename(path), flags=re.I)
    if outdir is None:
        outdir = os.path.join(os.path.dirname(os.path.abspath(path)),
                              base + "-reaper")
    c = Converter(path, outdir)
    rpp_path = os.path.join(c.outdir, c.base + ".RPP")
    lua_path = os.path.join(c.outdir, c.base + "-plugins.lua")
    text = guide(c, rpp_path, lua_path)
    if write:
        os.makedirs(c.outdir, exist_ok=True)
        files = dict(c.files)
        files[c.base + ".RPP"] = c.rpp().encode("utf-8")
        files[c.base + "-plugins.lua"] = c.lua().encode("utf-8")
        files[c.base + "-steps.txt"] = text.encode("utf-8")
        for name, data in files.items():
            with open(os.path.join(c.outdir, name), "wb") as fh:
                fh.write(data)
    return c, text
