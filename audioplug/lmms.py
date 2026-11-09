"""LMMS .mmp / .mmpz project reader."""

import os
import xml.etree.ElementTree as ET
import zlib

from . import carla
from .formats import file_key, file_stem

# LMMS plugins that load external plugins; everything else is built in.
_LMMS_HOSTS = {"vestige", "vsteffect", "ladspaeffect", "lv2effect",
               "lv2instrument", "carlarack", "carlapatchbay"}


def parse(path):
    """Return wanted plugins from an LMMS .mmp / .mmpz file."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if path.lower().endswith(".mmpz"):
        raw = zlib.decompress(raw[4:])  # Qt qCompress: 4-byte size + zlib
    root = ET.fromstring(raw)
    out = []

    def keyattrs(el):
        k = el.find("key")
        if k is None:
            return {}
        return {a.get("name"): a.get("value", "") for a in k.findall("attribute")}

    for el in root.iter():
        if el.tag not in ("instrument", "effect"):
            continue
        kind = el.get("name", "")
        attrs = keyattrs(el)
        if kind == "vestige":
            v = el.find("vestige")
            f = v.get("plugin", "") if v is not None else ""
            if f:
                out.append({"format": "vst2", "key": file_key(f),
                            "name": file_stem(os.path.basename(f)),
                            "display": "VeSTige: " + os.path.basename(f)})
        elif kind == "vsteffect":
            f = attrs.get("file", "")
            if f:
                out.append({"format": "vst2", "key": file_key(f),
                            "name": attrs.get("plugin") or file_stem(
                                os.path.basename(f)),
                            "display": "VST effect: " + os.path.basename(f)})
        elif kind == "ladspaeffect":
            f = attrs.get("file", "")
            if f:
                out.append({"format": "ladspa", "key": file_key(f),
                            "name": file_stem(os.path.basename(f)),
                            "display": "LADSPA: %s / %s" % (
                                file_key(f), attrs.get("plugin", ""))})
        elif kind in ("lv2effect", "lv2instrument"):
            uri = attrs.get("uri", "")
            if not uri:
                for sub in el.iter():
                    if sub.get("uri"):
                        uri = sub.get("uri")
                        break
            if uri:
                out.append({"format": "lv2", "key": uri,
                            "name": uri.rstrip("/").rsplit("/", 1)[-1],
                            "display": "LV2: " + uri})
        elif kind.startswith("carla"):
            # LMMS keeps Carla's state as plain XML (a CARLA-PROJECT
            # element) inside the instrument/effect, not base64 as REAPER.
            host = "Carla Patchbay" if "patchbay" in kind else "Carla Rack"
            for w in carla.plugins(ET.tostring(el, encoding="utf-8"), host):
                w["display"] = w["display"].strip()
                out.append(w)
        elif kind:
            out.append({"format": "lmms", "key": kind, "name": kind,
                        "display": "LMMS built-in: " + kind,
                        "unchecked": True})
    return out
