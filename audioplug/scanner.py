"""Scan this machine for installed plugins (the host file data)."""

import datetime
import glob
import json
import os
import platform
import re
import socket

from . import reaper
from .common import read_text
from .formats import ENV_VARS, FORMAT_DIRS, HOME_DIRS, LIB_ROOTS, file_stem
from .lv2 import scan_lv2_bundle

SCHEMA_VERSION = 1


def search_dirs(fmt, extra):
    """Return a de-duplicated list of (dir, source) for one format."""
    cands = []
    for var in ENV_VARS[fmt]:
        for d in os.environ.get(var, "").split(":"):
            if d:
                cands.append((d, "env:" + var))
    for d in HOME_DIRS[fmt]:
        cands.append((d, "home"))
    roots = list(LIB_ROOTS) + sorted(glob.glob("/usr/lib/*-linux-gnu*"))
    for root in roots:
        for sub in FORMAT_DIRS[fmt]:
            cands.append((os.path.join(root, sub), "system"))
    if fmt == "vst2":
        for d in reaper.PLUGIN_DIRS:
            cands.append((d, "reaper"))
    if fmt == "ladspa":
        # LMMS ships its own LADSPA plugins (caps, tap, cmt, calf, swh).
        for root in roots:
            cands.append((os.path.join(root, "lmms", "ladspa"), "lmms"))
    for f, d in extra:
        if f == fmt:
            cands.append((d, "extra"))

    out, seen = [], set()
    for d, src in cands:
        d = os.path.expanduser(d)
        if not os.path.isdir(d):
            continue
        real = os.path.realpath(d)
        if real in seen:
            continue
        seen.add(real)
        out.append((d, src))
    return out


def _walk(top, match, prune_dirs=False):
    """Yield paths under top for which match(path, is_dir) is true.

    With prune_dirs, matching directories are yielded and not entered.
    """
    for root, dirs, files in os.walk(top, followlinks=True):
        if prune_dirs:
            keep = []
            for d in dirs:
                p = os.path.join(root, d)
                if match(p, True):
                    yield p
                else:
                    keep.append(d)
            dirs[:] = keep
        for f in files:
            p = os.path.join(root, f)
            if match(p, False):
                yield p


def _vst3_version(bundle):
    p = os.path.join(bundle, "Contents", "moduleinfo.json")
    if not os.path.isfile(p):
        return None, None
    txt = read_text(p)
    # moduleinfo.json is JSON5-ish; strip trailing commas before parsing.
    txt = re.sub(r",(\s*[}\]])", r"\1", txt)
    try:
        data = json.loads(txt)
    except ValueError:
        return None, None
    return data.get("Name"), data.get("Version")


def scan_dir(fmt, top):
    out = []
    if fmt == "lv2":
        for b in _walk(top, lambda p, isdir: isdir and p.endswith(".lv2"),
                       prune_dirs=True):
            out.extend(scan_lv2_bundle(b))
        return out

    if fmt == "jsfx":
        skip = (".png", ".jpg", ".txt", ".md", ".jsfx-inc", ".rpl", ".ini",
                ".wav", ".dat", ".ttf")
        for root, dirs, files in os.walk(top, followlinks=True):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f.startswith(".") or f.lower().endswith(skip):
                    continue
                p = os.path.join(root, f)
                rel = os.path.relpath(p, top)
                out.append({"format": "jsfx", "name": rel, "file": rel,
                            "path": p})
        return out

    if fmt == "vst3":
        def m(p, isdir):
            return p.lower().endswith(".vst3")
        for p in _walk(top, m, prune_dirs=True):
            rec = {"format": "vst3", "name": file_stem(os.path.basename(p)),
                   "file": os.path.basename(p), "path": p}
            if os.path.isdir(p):
                name, ver = _vst3_version(p)
                if name:
                    rec["name"] = name
                if ver:
                    rec["version"] = ver
            out.append(rec)
        return out

    if fmt == "clap":
        def m(p, isdir):
            return p.lower().endswith(".clap")
        for p in _walk(top, m, prune_dirs=True):
            out.append({"format": "clap",
                        "name": file_stem(os.path.basename(p)),
                        "file": os.path.basename(p), "path": p})
        return out

    # vst2, ladspa, dssi: plain .so files. Skip anything inside bundles of
    # other formats that might sit in the same tree.
    def m(p, isdir):
        if isdir:
            low = p.lower()
            return low.endswith((".vst3", ".lv2", ".clap"))
        return p.endswith(".so")
    for p in _walk(top, m, prune_dirs=True):
        if not p.endswith(".so"):
            continue  # pruned bundle dir
        out.append({"format": fmt, "name": file_stem(os.path.basename(p)),
                    "file": os.path.basename(p), "path": p})
    return out


def os_name():
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.system()


def scan(extra):
    plugins, dirs_used = [], []
    seen = {}
    for fmt in FORMAT_DIRS:
        for d, src in search_dirs(fmt, extra):
            dirs_used.append({"format": fmt, "dir": d, "source": src})
            for rec in scan_dir(fmt, d):
                key = (fmt, os.path.realpath(rec["path"]), rec.get("id"))
                if key in seen:
                    # Same plugin seen again through a symlink, e.g.
                    # ~/.lv2/yoshimi.lv2 -> /usr/lib64/lv2/yoshimi.lv2.
                    first = seen[key]
                    if rec["path"] != first["path"]:
                        first.setdefault("links", [])
                        if rec["path"] not in first["links"]:
                            first["links"].append(rec["path"])
                    continue
                seen[key] = rec
                rec["source"] = src
                plugins.append(rec)
    plugins.sort(key=lambda r: (r["format"], r["name"].lower(), r["path"]))
    info = reaper.plugin_paths()
    reaper.mark_visible(plugins, info)
    reaper.add_vst_ids(plugins)
    return {
        "schema": SCHEMA_VERSION,
        "host": socket.gethostname(),
        "os": os_name(),
        "user": os.environ.get("USER", ""),
        "generated": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "search_dirs": dirs_used,
        "reaper": info,
        "plugins": plugins,
    }
