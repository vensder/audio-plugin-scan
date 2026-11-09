"""LMMS .mmp / .mmpz project reader.

Works with LMMS 1.2 (bbtrack, fxmixer / fxchannel, fxch) and 1.3
(patterntrack, mixer / mixerchannel, mixch) projects.
"""

import os
import xml.etree.ElementTree as ET
import zlib

from . import carla
from .formats import file_key, file_stem

# <track type="...">
TRACK_TYPES = {"0": "instrument", "1": "pattern", "2": "sample",
               "5": "automation", "6": "automation"}


def read(path):
    """Root element of an LMMS project."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if path.lower().endswith(".mmpz"):
        raw = zlib.decompress(raw[4:])  # Qt qCompress: 4-byte size + zlib
    return ET.fromstring(raw)


def _keyattrs(el):
    k = el.find("key")
    if k is None:
        return {}
    return {a.get("name"): a.get("value", "") for a in k.findall("attribute")}


def _uri_name(uri):
    """'http://calf.sourceforge.net/plugins/Reverb' -> 'Reverb',
    'urn:dragonfly:hall' -> 'hall'."""
    tail = uri.rstrip("/#").replace("#", "/").rsplit("/", 1)[-1]
    return tail.rsplit(":", 1)[-1] if "/" not in uri else tail


def wants(el):
    """Wanted plugins of one <instrument> / <effect> element: one entry,
    the plugins inside a Carla rack, or a built-in (unchecked) entry.
    Each has a "label" for listing it in a chain."""
    kind = el.get("name", "")
    attrs = _keyattrs(el)
    if kind == "vestige":
        v = el.find("vestige")
        f = v.get("plugin", "") if v is not None else ""
        if f:
            name = file_stem(os.path.basename(f))
            return [{"format": "vst2", "key": file_key(f), "name": name,
                     "display": "VeSTige: " + os.path.basename(f),
                     "label": "VST " + name}]
        return []
    if kind == "vsteffect":
        f = attrs.get("file", "")
        if f:
            name = attrs.get("plugin") or file_stem(os.path.basename(f))
            return [{"format": "vst2", "key": file_key(f), "name": name,
                     "display": "VST effect: " + os.path.basename(f),
                     "label": "VST " + name}]
        return []
    if kind == "ladspaeffect":
        f = attrs.get("file", "")
        if f:
            label = attrs.get("plugin", "")
            return [{"format": "ladspa", "key": file_key(f),
                     "name": file_stem(os.path.basename(f)),
                     "display": "LADSPA: %s / %s" % (file_key(f), label),
                     "label": "LADSPA %s/%s" % (file_key(f), label)}]
        return []
    if kind in ("lv2effect", "lv2instrument"):
        uri = attrs.get("uri", "")
        if not uri:
            for sub in el.iter():
                if sub.get("uri"):
                    uri = sub.get("uri")
                    break
        if uri:
            name = _uri_name(uri)
            return [{"format": "lv2", "key": uri, "name": name,
                     "display": "LV2: " + uri, "label": "LV2 " + name}]
        return []
    if kind.startswith("carla"):
        # LMMS keeps Carla's state as plain XML (a CARLA-PROJECT
        # element) inside the instrument/effect, not base64 as REAPER.
        host = "Carla Patchbay" if "patchbay" in kind else "Carla Rack"
        out = []
        for w in carla.plugins(ET.tostring(el, encoding="utf-8"), host):
            w["display"] = w["display"].strip()
            w["label"] = w["name"]
            out.append(w)
        return out
    if kind:
        return [{"format": "lmms", "key": kind, "name": kind,
                 "display": "LMMS built-in: " + kind, "label": kind,
                 "unchecked": True}]
    return []


def parse(path):
    """Return wanted plugins from an LMMS .mmp / .mmpz file."""
    out = []
    for el in read(path).iter():
        if el.tag in ("instrument", "effect"):
            out.extend(wants(el))
    return out


def _slot(el, on=True):
    """One instrument / effect in a chain."""
    kind = el.get("name", "")
    ws = wants(el)
    if kind.startswith("carla"):
        name = "Carla Patchbay" if "patchbay" in kind else "Carla Rack"
        return {"name": name, "on": on, "want": None, "carla": ws}
    w = ws[0] if ws else None
    return {"name": w["label"] if w else kind or "?", "on": on,
            "want": w, "carla": []}


def _fx_chain(parent):
    """(chain, enabled) of the <fxchain> directly under parent."""
    fc = parent.find("fxchain") if parent is not None else None
    if fc is None:
        return [], True
    chain = [_slot(e, e.get("on", "1") != "0") for e in fc.findall("effect")]
    return chain, fc.get("enabled", "1") != "0"


def _track(t):
    kind = TRACK_TYPES.get(t.get("type", ""), "other")
    info = {"name": t.get("name", ""), "kind": kind,
            "muted": t.get("muted", "0") == "1",
            "solo": t.get("solo", "0") == "1",
            "chain": [], "effects": 0, "fx_on": True, "mixer": None}
    body = t.find("instrumenttrack")
    if body is None:
        body = t.find("sampletrack")
    if body is not None:
        inst = body.find("instrument")
        if inst is not None:
            info["chain"].append(_slot(inst))
        fx, info["fx_on"] = _fx_chain(body)
        info["chain"] += fx
        info["effects"] = len(fx)
        ch = body.get("mixch", body.get("fxch"))
        if ch not in (None, "", "0"):
            info["mixer"] = int(ch)
    return info


def _tracks(container):
    return [_track(t) for t in container.findall("track")]


def song(root):
    """Song editor tracks, pattern editor tracks, mixer channels and the
    LMMS version of a project:

    {"version": "1.2.2", "tracks": [...], "patterns": [...],
     "mixer": [{"num": 0, "name": "Master", "muted": False,
                "chain": [...], "fx_on": True}, ...]}

    A track is {"name", "kind" (instrument / pattern / sample /
    automation), "muted", "solo", "chain", "effects", "fx_on", "mixer"};
    its chain starts with the instrument, then the "effects" effects. A chain slot is
    {"name", "on", "want", "carla"}.
    """
    out = {"version": root.get("creatorversion", ""), "tracks": [],
           "patterns": [], "mixer": []}
    s = root.find("song")
    if s is None:
        return out
    main = s.find("trackcontainer")
    if main is not None:
        out["tracks"] = _tracks(main)
        # The pattern (Beat/Bassline) editor's tracks are shared by all
        # pattern tracks and saved inside the first one.
        for t in main.findall("track"):
            for sub in t.iter("trackcontainer"):
                out["patterns"] += _tracks(sub)
    mixer = s.find("mixer")
    if mixer is None:
        mixer = s.find("fxmixer")
    if mixer is not None:
        for c in list(mixer):
            if c.tag not in ("mixerchannel", "fxchannel"):
                continue
            num = int(c.get("num", "0"))
            chain, on = _fx_chain(c)
            out["mixer"].append({
                "num": num,
                "name": c.get("name") or ("Master" if num == 0
                                          else "Channel %d" % num),
                "muted": c.get("muted", "0") == "1",
                "solo": c.get("soloed", c.get("solo", "0")) == "1",
                "chain": chain, "fx_on": on})
    return out
