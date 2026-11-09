"""Plugins saved inside a Carla rack / patchbay.

Carla keeps its state as XML: base64 inside a REAPER .RPP, plain XML
inside an LMMS project. Carla also saves its own search paths in that
state (<LV2_PATH>...) and uses them when the project is loaded, also on
another machine.
"""

import binascii
import re

from .formats import file_key

TYPES = {"LV2": "lv2", "VST2": "vst2", "VST": "vst2", "VST3": "vst3",
         "CLAP": "clap", "LADSPA": "ladspa", "DSSI": "dssi"}


def plugins(data, host="Carla"):
    """Wanted plugins from a Carla state (the XML Carla saves in its
    VST/LV2 state), e.g. an LV2 Yoshimi inside Carla-Rack."""
    text = data.decode("utf-8", "replace")
    # Carla saves its own search paths in the state, e.g.
    # <LV2_PATH>/home/me/.lv2:/usr/lib/lv2</LV2_PATH>, and uses them when
    # the project is loaded, also on another machine.
    paths = {}
    for k, v in re.findall(r"<(\w+)_PATH>(.*?)</\1_PATH>", text, re.S):
        fmt = TYPES.get(k.upper())
        if fmt:
            paths[fmt] = [d for d in v.strip().split(":") if d]
    out = []
    for block in re.findall(r"<Info>(.*?)</Info>", text, re.S):
        info = {}
        for k in ("Type", "Name", "Label", "URI", "Binary"):
            m = re.search(r"<%s>(.*?)</%s>" % (k, k), block, re.S)
            if m:
                info[k] = (m.group(1).replace("&amp;", "&")
                           .replace("&lt;", "<").replace("&gt;", ">").strip())
        fmt = TYPES.get(info.get("Type", "").upper())
        name = info.get("Name") or info.get("Label") or ""
        if not fmt or not name:
            continue  # internal plugins, SF2/SFZ files
        if fmt == "lv2":
            key = info.get("URI") or info.get("Label") or name
        elif fmt == "clap":
            key = "clap-id:" + info.get("Label", name)
        else:
            key = file_key(info.get("Binary") or name)
        out.append({"format": fmt, "key": key, "name": name,
                    "display": "  %s > %s: %s" % (host, info["Type"], name),
                    "inside": host, "carla_paths": paths.get(fmt)})
    return out


def b64_lines(lines):
    """Decode REAPER's base64 state lines one by one (each line is a whole
    number of base64 groups); undecodable lines are skipped."""
    out = b""
    for ln in lines:
        try:
            out += binascii.a2b_base64(ln)
        except (binascii.Error, ValueError):
            pass
    return out
