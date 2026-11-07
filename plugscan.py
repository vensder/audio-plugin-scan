#!/usr/bin/env python3
"""plugscan - inventory of installed Linux audio plugins.

Usage:
    plugscan.py scan    [-o FILE] [--extra-path FORMAT:DIR ...] [-q]
    plugscan.py compare [HOST ...] [--all] [-f FORMATS] [-x FORMATS]
    plugscan.py check   PROJECT|DIR [...] [--host HOST ... | -a] [--missing]
                        [-f FORMATS] [-x FORMATS]

Writes a JSON file (default: scan-results/<hostname>.json next to this
script) listing every VST2, VST3,
LV2, CLAP, LADSPA and DSSI plugin found in the standard home and system
locations, plus any directories listed in VST_PATH, LXVST_PATH, VST3_PATH,
LV2_PATH, CLAP_PATH, LADSPA_PATH and DSSI_PATH.

Only the Python 3 standard library is used.
"""

import argparse
import datetime
import glob
import json
import os
import platform
import re
import signal
import socket
import sys

SCHEMA_VERSION = 1

# Host files live next to the script, so a git checkout collects them.
RESULTS_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                           "scan-results")

HOME = os.path.expanduser("~")

# Directory names used under the lib dirs, per format.
FORMAT_DIRS = {
    "vst2": ["vst", "lxvst", "linux_vst"],
    "vst3": ["vst3"],
    "lv2": ["lv2"],
    "clap": ["clap"],
    "ladspa": ["ladspa"],
    "dssi": ["dssi"],
    "jsfx": [],
}

HOME_DIRS = {
    "vst2": ["~/.vst", "~/.lxvst"],
    "vst3": ["~/.vst3"],
    "lv2": ["~/.lv2"],
    "clap": ["~/.clap"],
    "ladspa": ["~/.ladspa"],
    "dssi": ["~/.dssi"],
    "jsfx": ["~/.config/REAPER/Effects", "~/opt/REAPER/InstallData/Effects",
             "/opt/REAPER/InstallData/Effects"],
}

ENV_VARS = {
    "vst2": ["VST_PATH", "LXVST_PATH"],
    "vst3": ["VST3_PATH"],
    "lv2": ["LV2_PATH"],
    "clap": ["CLAP_PATH"],
    "ladspa": ["LADSPA_PATH"],
    "dssi": ["DSSI_PATH"],
    "jsfx": [],
}

LIB_ROOTS = [
    "/usr/lib", "/usr/lib64", "/usr/local/lib", "/usr/local/lib64",
    "/opt/lib", "/opt/lib64",
]

# Reaper ships its own VST2 plugins (ReaEQ, ReaComp, ...) in its install dir.
REAPER_PLUGIN_DIRS = [
    "~/opt/REAPER/Plugins", "/opt/REAPER/Plugins",
    "/usr/local/REAPER/Plugins", "/usr/lib/REAPER/Plugins",
    "/usr/local/lib/REAPER/Plugins",
]


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
        for d in REAPER_PLUGIN_DIRS:
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


# ---------------------------------------------------------------- Turtle --
# A tiny Turtle reader, just enough to find "<uri> a lv2:Plugin" and
# "doap:name" / "lv2:minorVersion" etc. at the top level of LV2 .ttl files.

_TOKEN_RE = re.compile(r'''
      (?P<ws>\s+|\#[^\n]*)
    | (?P<iri><[^>]*>)
    | (?P<str3>"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\')
    | (?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
    | (?P<lang>@[A-Za-z][A-Za-z0-9-]*)
    | (?P<dtype>\^\^)
    | (?P<punct>[;,.\[\]()])
    | (?P<word>[^\s;,\[\]()<>"']+)
''', re.X)


def _tokens(text):
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            pos += 1
            continue
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        val = m.group()
        if kind == "word" and val.endswith(".") and len(val) > 1 \
                and not re.match(r"^[+-]?\d", val):
            # "foo:bar." -> "foo:bar" "."
            yield ("word", val[:-1])
            yield ("punct", ".")
            continue
        yield (kind, val)


def _unquote(tok):
    kind, val = tok
    if kind == "str3":
        return val[3:-3]
    if kind == "str":
        return val[1:-1].encode("utf-8").decode("unicode_escape", "ignore") \
            if "\\" in val else val[1:-1]
    return val


def parse_turtle(text, base=""):
    """Yield (subject, predicate, object) triples at nesting depth 0.

    IRIs are expanded with @prefix declarations; literals are returned as
    plain strings. Blank-node contents are skipped.
    """
    prefixes = {}
    toks = list(_tokens(text))
    i, n = 0, len(toks)

    def expand(tok):
        kind, val = tok
        if kind == "iri":
            iri = val[1:-1]
            if base and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", iri):
                iri = base + iri
            return iri
        if kind == "word":
            if val == "a":
                return "rdf:type"
            if ":" in val:
                p, local = val.split(":", 1)
                if p in prefixes:
                    return prefixes[p] + local
            return val
        return _unquote(tok)

    while i < n:
        kind, val = toks[i]
        if kind in ("word", "lang") and val.lower() in ("@prefix", "prefix"):
            if i + 2 < n:
                name = toks[i + 1][1].rstrip(":")
                prefixes[name] = toks[i + 2][1][1:-1]
            i += 3
            if i < n and toks[i] == ("punct", "."):
                i += 1
            continue
        if kind in ("word", "lang") and val.lower() in ("@base", "base"):
            if i + 1 < n:
                base = toks[i + 1][1][1:-1]
            i += 2
            if i < n and toks[i] == ("punct", "."):
                i += 1
            continue

        # Statement: subject predicate object (, object)* (; predicate ...)* .
        if toks[i] == ("punct", "["):
            subj = None
            depth = 0
            while i < n:
                if toks[i] == ("punct", "["):
                    depth += 1
                elif toks[i] == ("punct", "]"):
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
        else:
            subj = expand(toks[i])
            i += 1
        pred = None
        expect_pred = True
        while i < n:
            tok = toks[i]
            if tok == ("punct", "."):
                i += 1
                break
            if tok == ("punct", ";"):
                expect_pred = True
                i += 1
                continue
            if tok == ("punct", ","):
                i += 1
                continue
            if tok[0] == "punct" and tok[1] in "[(":
                # skip nested blank node / collection
                opener, closer = tok[1], "]" if tok[1] == "[" else ")"
                depth = 0
                while i < n:
                    if toks[i] == ("punct", opener):
                        depth += 1
                    elif toks[i] == ("punct", closer):
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                i += 1
                expect_pred = False
                continue
            if tok[0] in ("lang",):
                i += 1
                continue
            if tok[0] == "dtype":
                i += 2
                continue
            if expect_pred:
                pred = expand(tok)
                expect_pred = False
            else:
                if subj is not None and pred is not None:
                    yield (subj, pred, expand(tok))
            i += 1


RDF_TYPE = "rdf:type"
LV2 = "http://lv2plug.in/ns/lv2core#"
DOAP = "http://usefulinc.com/ns/doap#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def scan_lv2_bundle(bundle):
    """Return a list of plugin dicts for one .lv2 bundle directory."""
    manifest = os.path.join(bundle, "manifest.ttl")
    if not os.path.isfile(manifest):
        return []
    base = "file://" + os.path.abspath(bundle) + "/"
    triples = list(parse_turtle(_read(manifest), base))

    plugins = [s for s, p, o in triples
               if p == RDF_TYPE and o == LV2 + "Plugin"]
    if not plugins:
        return []

    # Follow rdfs:seeAlso to pick up names / versions.
    see_also = {o for s, p, o in triples if p == RDFS + "seeAlso"}
    for ref in sorted(see_also):
        if ref.startswith(base):
            path = os.path.join(bundle, ref[len(base):])
            if os.path.isfile(path):
                triples.extend(parse_turtle(_read(path), base))

    info = {}
    for s, p, o in triples:
        if s in plugins:
            d = info.setdefault(s, {})
            if p == DOAP + "name" and "name" not in d:
                d["name"] = o
            elif p == LV2 + "minorVersion":
                d["minor"] = o
            elif p == LV2 + "microVersion":
                d["micro"] = o

    out = []
    for uri in plugins:
        d = info.get(uri, {})
        rec = {
            "format": "lv2",
            "name": d.get("name") or uri.rstrip("/").rsplit("/", 1)[-1],
            "id": uri,
            "file": os.path.basename(bundle.rstrip("/")),
            "path": bundle,
        }
        if "minor" in d:
            rec["version"] = "%s.%s" % (d["minor"], d.get("micro", "0"))
        out.append(rec)
    return out


# ------------------------------------------------------------ other fmts --

def _stem(fname):
    for ext in (".vst.so", ".vst3", ".clap", ".so"):
        if fname.lower().endswith(ext):
            return fname[: -len(ext)]
    return fname


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
    txt = _read(p)
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
            rec = {"format": "vst3", "name": _stem(os.path.basename(p)),
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
            out.append({"format": "clap", "name": _stem(os.path.basename(p)),
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
        out.append({"format": fmt, "name": _stem(os.path.basename(p)),
                    "file": os.path.basename(p), "path": p})
    return out


# ------------------------------------------------------------------ main --

# ------------------------------------------------------- REAPER paths --
# REAPER only loads plugins from its own path lists (Preferences >
# Plug-ins), stored in reaper.ini. A plugin can be installed and still be
# invisible to REAPER, e.g. Fedora puts VST2 in /usr/lib64/vst.

REAPER_INI = os.environ.get("REAPER_INI", "~/.config/REAPER/reaper.ini")
# Used when reaper.ini has no VST path yet (REAPER default, assumed).
REAPER_VST_DEFAULT = ("~/.vst;~/.vst3;/usr/lib/vst;/usr/lib/vst3;"
                      "/usr/local/lib/vst;/usr/local/lib/vst3")
# Same for CLAP (what REAPER 7 writes once the list is edited; no lib64).
REAPER_CLAP_DEFAULT = "/usr/local/lib/clap;/usr/lib/clap;~/.clap;%CLAP_PATH%"
REAPER_FMT = {"vst2": "vst", "vst3": "vst", "clap": "clap", "lv2": "lv2"}


def reaper_paths(ini=None):
    """Return {"ini": path, "paths": {"vst"|"clap"|"lv2": {...}}} or None.

    Each entry is {"keys": [ini keys], "dirs": [...]}. Keys are matched
    loosely (vstpath*, *clap*path*, *lv2*path*) because their names differ
    between platforms and REAPER versions.
    """
    ini = os.path.expanduser(ini or REAPER_INI)
    if not os.path.isfile(ini):
        return None
    out = {}
    # The keys are read from any section: their section is not the same
    # in every REAPER version.
    with open(ini, encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(("[", ";", "#")) or "=" not in line:
                continue
            key, val = line.split("=", 1)
            k = key.strip().lower()
            if k.startswith("vstpath"):
                kind = "vst"
            elif "clap" in k and "path" in k:
                kind = "clap"
            elif "lv2" in k and "path" in k:
                kind = "lv2"
            else:
                continue
            e = out.setdefault(kind, {"keys": [], "dirs": []})
            e["keys"].append(key.strip())
            for d in _reaper_dirs(val):
                if d not in e["dirs"]:
                    e["dirs"].append(d)
    if "vst" not in out:
        out["vst"] = {"keys": [], "dirs": _reaper_dirs(REAPER_VST_DEFAULT)}
    if "clap" not in out:
        out["clap"] = {"keys": [], "dirs": _reaper_dirs(REAPER_CLAP_DEFAULT)}
    return {"ini": ini, "paths": out}


def _reaper_dirs(val):
    """Split a REAPER path list; '%CLAP_PATH%' expands to that env var."""
    out = []
    for d in val.split(";"):
        d = d.strip()
        m = re.match(r"^%(\w+)%$", d)
        if m:
            out += [x for x in os.environ.get(m.group(1), "").split(":") if x]
        elif d:
            out.append(d)
    return out


def reaper_visible(dirs):
    """Real paths of every file and folder REAPER can reach under dirs."""
    seen = set()
    for d in dirs:
        d = os.path.expanduser(d)
        if not os.path.isdir(d):
            continue
        for root, subdirs, files in os.walk(d, followlinks=True):
            real = os.path.realpath(root)
            if real in seen and root != d:
                subdirs[:] = []
                continue
            seen.add(real)
            for f in files:
                seen.add(os.path.realpath(os.path.join(root, f)))
    return seen


def mark_reaper(plugins, info):
    """Set rec["reaper"] = True/False where REAPER's path lists are known."""
    if not info:
        return
    vis = {k: reaper_visible(v["dirs"]) for k, v in info["paths"].items()}
    for rec in plugins:
        kind = REAPER_FMT.get(rec["format"])
        if kind not in vis:
            continue
        rec["reaper"] = (rec.get("source") == "reaper"
                         or os.path.realpath(rec["path"]) in vis[kind])


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
    reaper = reaper_paths()
    mark_reaper(plugins, reaper)
    return {
        "schema": SCHEMA_VERSION,
        "host": socket.gethostname(),
        "os": os_name(),
        "user": os.environ.get("USER", ""),
        "generated": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "search_dirs": dirs_used,
        "reaper": reaper,
        "plugins": plugins,
    }


def cmd_scan(args):
    extra = []
    for item in args.extra_path or []:
        if ":" not in item:
            sys.exit("--extra-path must look like FORMAT:DIR, got %r" % item)
        f, d = item.split(":", 1)
        if f not in FORMAT_DIRS:
            sys.exit("unknown format %r (use one of: %s)"
                     % (f, ", ".join(FORMAT_DIRS)))
        extra.append((f, d))

    data = scan(extra)
    out = args.output or os.path.join(RESULTS_DIR, data["host"] + ".json")
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    if not args.quiet:
        counts = {}
        for p in data["plugins"]:
            counts[p["format"]] = counts.get(p["format"], 0) + 1
        print("Host: %s (%s)" % (data["host"], data["os"]))
        for fmt in FORMAT_DIRS:
            print("  %-7s %5d" % (fmt, counts.get(fmt, 0)))
        print("  %-7s %5d" % ("total", len(data["plugins"])))
        print_reaper(data)
        print("Wrote %s" % out)


# --------------------------------------------------------------- matching --
# A plugin is identified by (format, key). key is the LV2 URI, or the file
# basename (lowercased, ".so" dropped) for every other format. When the key
# does not match, the plugin name is tried as a fallback.

def file_key(fname):
    k = os.path.basename(fname.rstrip("/")).lower()
    return k[:-3] if k.endswith(".so") else k


def plugin_key(rec):
    if rec["format"] == "lv2" and rec.get("id"):
        return rec["id"]
    if rec["format"] == "jsfx":
        return rec["file"].lower()
    return file_key(rec["file"])


def norm_name(name):
    return re.sub(r"[^a-z0-9]+", "", name.lower())


class Host:
    def __init__(self, data, label=None):
        self.data = data
        self.label = label or data.get("host", "?")
        self.keys, self.names, self.any_names = set(), set(), {}
        self.recs = {}  # (fmt, key or name) -> [records]
        for rec in data["plugins"]:
            fmt = rec["format"]
            self.keys.add((fmt, plugin_key(rec)))
            n = norm_name(rec["name"])
            self.names.add((fmt, n))
            self.any_names.setdefault(n, set()).add(fmt)
            self.recs.setdefault((fmt, plugin_key(rec)), []).append(rec)
            self.recs.setdefault((fmt, "name:" + n), []).append(rec)

    @classmethod
    def load(cls, path):
        if not os.path.exists(path) and os.sep not in path:
            # bare host name -> scan-results/<name>.json
            name = path if path.endswith(".json") else path + ".json"
            cand = os.path.join(RESULTS_DIR, name)
            if os.path.exists(cand):
                path = cand
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        label = data.get("host") or os.path.basename(path)
        return cls(data, label)

    def found(self, want):
        """Installed records matching a wanted plugin (key, else name)."""
        fmt, n = want["format"], norm_name(want["name"])
        return (self.recs.get((fmt, want["key"]))
                or self.recs.get((fmt, "name:" + n)) or [])

    def match(self, want, reaper=False):
        """Return 'yes', 'name', 'alt', 'path' or '-' for a wanted plugin.

        With reaper=True, a plugin installed only outside REAPER's plugin
        paths (as recorded at scan time) is 'path'.
        """
        fmt, n = want["format"], norm_name(want["name"])
        hit = None
        if (fmt, want["key"]) in self.keys:
            hit = "yes"
        elif n and (fmt, n) in self.names:
            # RPP stores CLAP plugin ids, which a file scan cannot see, so
            # for CLAP the name is the normal way to match.
            hit = "yes" if fmt == "clap" else "name"
        if hit:
            if reaper and hit == "yes":
                recs = self.found(want)
                if recs and all(r.get("reaper") is False for r in recs):
                    return "path"
            return hit
        if n and self.any_names.get(n):
            return "alt"
        return "-"


LEGEND = ("yes = installed, name = only a plugin with the same name, "
          "alt = same name in another format only, - = missing,\n"
          "path = installed, but outside REAPER's (or Carla's) plugin paths")


def in_dirs(path, dirs):
    """True if path (or its real path) is inside one of dirs."""
    cands = {path}
    if os.path.exists(path):
        cands.add(os.path.realpath(path))
    for d in dirs:
        d = os.path.expanduser(d).rstrip("/")
        for real in {d, os.path.realpath(d)}:
            if any(p == real or p.startswith(real + "/") for p in cands):
                return True
    return False


def plugin_folder(fmt, path):
    """'/usr/lib64/vst/carla.vst/CarlaRack.so' -> '/usr/lib64/vst'."""
    names = FORMAT_DIRS.get(fmt, []) + ["." + n for n in
                                        FORMAT_DIRS.get(fmt, [])]
    d = os.path.dirname(path)
    while d not in ("/", ""):
        if os.path.basename(d).lower() in names:
            return d
        d = os.path.dirname(d)
    return os.path.dirname(path)


def print_reaper(data, formats=None):
    """Print REAPER's plugin path lists recorded in a scan."""
    info = data.get("reaper")
    if not info:
        return
    print("REAPER plugin paths (%s):" % info["ini"])
    for kind in ("vst", "clap", "lv2"):
        if formats and kind not in formats:
            continue
        e = info["paths"].get(kind)
        if not e:
            continue
        src = ", ".join(e["keys"]) or "not set, REAPER default assumed"
        print("  %-4s %s  [%s]" % (kind, ";".join(e["dirs"]), src))
    hidden = [r for r in data["plugins"] if r.get("reaper") is False]
    if hidden:
        print("  %d plugin(s) are outside these paths, REAPER will not "
              "see them." % len(hidden))


def print_table(rows, hosts, title_col="plugin"):
    """rows: list of (format, label, [cell per host])."""
    w_fmt = max([len("format")] + [len(r[0]) for r in rows])
    w_lab = min(60, max([len(title_col)] + [len(r[1]) for r in rows]))
    w_cols = [max(4, len(h.label)) for h in hosts]
    head = "%-*s  %-*s" % (w_fmt, "format", w_lab, title_col)
    for h, w in zip(hosts, w_cols):
        head += "  %-*s" % (w, h.label)
    print(head)
    print("-" * len(head))
    for fmt, label, cells in rows:
        if len(label) > w_lab:
            # keep the end: it is the part that tells long paths apart
            label = "..." + label[-(w_lab - 3):]
        line = "%-*s  %-*s" % (w_fmt, fmt, w_lab, label)
        for c, w in zip(cells, w_cols):
            line += "  %-*s" % (w, c)
        print(line.rstrip())


FORMAT_ALIASES = {"vst": ["vst2", "vst3"]}


def parse_formats(values):
    """['lv2,vst', 'clap'] -> {'lv2', 'vst2', 'vst3', 'clap'}; None if empty."""
    out = set()
    for v in values or []:
        for f in v.lower().split(","):
            f = f.strip()
            if not f:
                continue
            fmts = FORMAT_ALIASES.get(f, [f])
            for x in fmts:
                if x not in FORMAT_DIRS:
                    sys.exit("unknown format %r (use: %s, or vst for vst2+vst3)"
                             % (f, ", ".join(FORMAT_DIRS)))
            out.update(fmts)
    return out or None


def format_filter(args):
    """Return a function format -> bool from --only / --exclude."""
    only = parse_formats(args.only)
    excl = parse_formats(args.exclude) or set()
    return lambda f: (only is None or f in only) and f not in excl


def all_result_files():
    return sorted(glob.glob(os.path.join(RESULTS_DIR, "*.json")))


def cmd_compare(args):
    paths = args.hosts or all_result_files()
    if len(paths) < 2:
        sys.exit("need at least two host files (found %d in %s)"
                 % (len(paths), RESULTS_DIR))
    hosts = [Host.load(p) for p in paths]
    keep = format_filter(args)
    wanted = {}
    for h in hosts:
        for rec in h.data["plugins"]:
            if not keep(rec["format"]):
                continue
            k = (rec["format"], plugin_key(rec))
            wanted.setdefault(k, {"format": rec["format"], "key": k[1],
                                  "name": rec["name"]})
    rows = []
    for k in sorted(wanted, key=lambda k: (k[0], wanted[k]["name"].lower())):
        w = wanted[k]
        cells = [h.match(w) for h in hosts]
        if args.all or any(c != "yes" for c in cells):
            label = w["name"]
            if w["format"] == "lv2":
                label += "  <" + w["key"] + ">"
            rows.append((w["format"], label, cells))
    for h in hosts:
        print("%s: %s, %d plugins, scanned %s" % (
            h.label, h.data.get("os", "?"), len(h.data["plugins"]),
            h.data.get("generated", "?")))
    print()
    if not rows:
        print("All hosts have the same plugins.")
        return
    print_table(rows, hosts)
    print()
    print(LEGEND)
    if not args.all:
        print("%d of %d plugins differ (use --all to list every plugin)."
              % (len(rows), len(wanted)))


# ---------------------------------------------------------- project files --

_RPP_TOKEN = re.compile(r'"[^"]*"|\'[^\']*\'|`[^`]*`|\S+')
_RPP_PREFIX = {"VST": "vst2", "VSTI": "vst2", "VST3": "vst3", "VST3I": "vst3",
               "LV2": "lv2", "LV2I": "lv2", "CLAP": "clap", "CLAPI": "clap",
               "LADSPA": "ladspa", "DSSI": "dssi", "DSSII": "dssi"}


def _unq(tok):
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'`":
        return tok[1:-1]
    return tok


def _display_name(disp):
    """'VST3i: Surge XT (Surge Synth Team) (2->6ch)' -> 'Surge XT'."""
    name = disp.split(": ", 1)[1] if ": " in disp else disp
    while True:
        new = re.sub(r"\s*\([^()]*\)\s*$", "", name)
        if new == name or not new:
            break
        name = new
    return name.strip()


_CARLA_TYPES = {"LV2": "lv2", "VST2": "vst2", "VST": "vst2", "VST3": "vst3",
                "CLAP": "clap", "LADSPA": "ladspa", "DSSI": "dssi"}


def carla_plugins(data, host="Carla"):
    """Wanted plugins from a Carla state (the XML Carla saves in its
    VST/LV2 state), e.g. an LV2 Yoshimi inside Carla-Rack."""
    text = data.decode("utf-8", "replace")
    # Carla saves its own search paths in the state, e.g.
    # <LV2_PATH>/home/me/.lv2:/usr/lib/lv2</LV2_PATH>, and uses them when
    # the project is loaded, also on another machine.
    paths = {}
    for k, v in re.findall(r"<(\w+)_PATH>(.*?)</\1_PATH>", text, re.S):
        fmt = _CARLA_TYPES.get(k.upper())
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
        fmt = _CARLA_TYPES.get(info.get("Type", "").upper())
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


def _b64_lines(lines):
    """Decode REAPER's base64 state lines one by one (each line is a whole
    number of base64 groups); undecodable lines are skipped."""
    import binascii
    out = b""
    for ln in lines:
        try:
            out += binascii.a2b_base64(ln)
        except (binascii.Error, ValueError):
            pass
    return out


def parse_rpp(path):
    """Return a list of wanted plugin dicts from a Reaper .RPP file.

    Plugins loaded inside a Carla rack/patchbay are listed too, from the
    Carla state stored in the project.
    """
    out = []
    carla, state = None, []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if carla is not None:
                if s == ">":
                    out.extend(carla_plugins(_b64_lines(state), carla))
                    carla, state = None, []
                elif not s.startswith("<"):
                    state.append(s)
                continue
            if not s.startswith(("<VST ", "<LV2 ", "<CLAP ", "<JS ",
                                 "<LADSPA ", "<DSSI ")):
                continue
            toks = [_unq(t) for t in _RPP_TOKEN.findall(s)]
            tag = toks[0][1:]
            if tag == "JS":
                if len(toks) > 1:
                    out.append({"format": "jsfx", "key": toks[1].lower(),
                                "name": toks[1], "display": "JS: " + toks[1]})
                continue
            if len(toks) < 3:
                continue
            disp, ident = toks[1], toks[2]
            prefix = disp.split(":", 1)[0].upper() if ":" in disp else tag
            fmt = _RPP_PREFIX.get(prefix, _RPP_PREFIX.get(tag, tag.lower()))
            name = _display_name(disp)
            if fmt == "lv2":
                key = ident
            elif fmt == "clap":
                # RPP stores the CLAP plugin id, not the file; match by name.
                key = "clap-id:" + ident
            else:
                key = file_key(ident)
            out.append({"format": fmt, "key": key, "name": name,
                        "display": disp})
            if "carla" in (name + " " + ident).lower():
                carla = name
    return out


# LMMS plugins that load external plugins; everything else is built in.
_LMMS_HOSTS = {"vestige", "vsteffect", "ladspaeffect", "lv2effect",
               "lv2instrument", "carlarack", "carlapatchbay"}


def parse_lmms(path):
    """Return wanted plugins from an LMMS .mmp / .mmpz file."""
    import xml.etree.ElementTree as ET
    import zlib
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
                            "name": _stem(os.path.basename(f)),
                            "display": "VeSTige: " + os.path.basename(f)})
        elif kind == "vsteffect":
            f = attrs.get("file", "")
            if f:
                out.append({"format": "vst2", "key": file_key(f),
                            "name": attrs.get("plugin") or _stem(
                                os.path.basename(f)),
                            "display": "VST effect: " + os.path.basename(f)})
        elif kind == "ladspaeffect":
            f = attrs.get("file", "")
            if f:
                out.append({"format": "ladspa", "key": file_key(f),
                            "name": _stem(os.path.basename(f)),
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
            for w in carla_plugins(ET.tostring(el, encoding="utf-8"), host):
                w["display"] = w["display"].strip()
                out.append(w)
        elif kind:
            out.append({"format": "lmms", "key": kind, "name": kind,
                        "display": "LMMS built-in: " + kind,
                        "unchecked": True})
    return out


PROJECT_EXTS = (".rpp", ".mmp", ".mmpz")


def parse_project(path):
    low = path.lower()
    if low.endswith((".rpp", ".rpp-bak")):
        return parse_rpp(path)
    if low.endswith((".mmp", ".mmpz")):
        return parse_lmms(path)
    raise ValueError("unknown project type: " + path)


def find_projects(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d.lower() != "backups")
                for f in sorted(files):
                    if f.lower().endswith(PROJECT_EXTS):
                        out.append(os.path.join(root, f))
        else:
            out.append(p)
    return out


def cmd_check(args):
    if args.all_hosts:
        hosts = [Host.load(p) for p in all_result_files()]
        if not hosts:
            sys.exit("no host files in " + RESULTS_DIR)
    elif args.host:
        hosts = [Host.load(p) for p in args.host]
    else:
        hosts = [Host(scan([]), socket.gethostname() + " (live)")]

    projects = find_projects(args.projects)
    if not projects:
        sys.exit("no .RPP / .mmp / .mmpz files found")

    total_missing = 0
    for proj in projects:
        try:
            wanted = parse_project(proj)
        except Exception as exc:  # bad file should not stop the run
            print("== %s\n   cannot read: %s\n" % (proj, exc))
            continue
        uniq, seen = [], set()
        for w in wanted:
            k = (w["format"], w["key"])
            if k not in seen:
                seen.add(k)
                uniq.append(w)

        rows, unchecked, missing = [], {}, 0
        outside, carla_out = {}, {}
        keep = format_filter(args)
        uniq = [w for w in uniq if w.get("unchecked") or keep(w["format"])]
        for w in uniq:
            if w.get("unchecked"):
                unchecked.setdefault(w["format"], set()).add(w["name"])
                continue
            rpp = proj.lower().endswith((".rpp", ".rpp-bak"))
            cells = [h.match(w, reaper=rpp and not w.get("inside"))
                     for h in hosts]
            if "path" in cells:
                for h, c in zip(hosts, cells):
                    if c == "path":
                        for r in h.found(w):
                            outside.setdefault(h.label, []).append(
                                (w["format"], r["path"]))
            if w.get("carla_paths") is not None:
                for i, h in enumerate(hosts):
                    recs = h.found(w) if cells[i] == "yes" else []
                    if recs and not any(in_dirs(x, w["carla_paths"])
                                        for r in recs
                                        for x in [r["path"]]
                                        + r.get("links", [])):
                        cells[i] = "path"
                        carla_out.setdefault(h.label, []).append(
                            (w, recs[0]["path"]))
            if any(c != "yes" for c in cells):
                missing += 1
            elif args.missing:
                continue
            rows.append((w["format"], w["display"], cells))
        total_missing += missing

        print("== %s" % proj)
        if rows:
            print_table(rows, hosts)
        elif not uniq:
            print("No plugins found.")
        else:
            print("All plugins present.")
        for label, items in outside.items():
            print("Outside REAPER's plugin paths on %s:" % label)
            h = [x for x in hosts if x.label == label][0]
            info = h.data.get("reaper") or {}
            for kind in sorted({REAPER_FMT[f] for f, _ in items}):
                e = info.get("paths", {}).get(kind, {})
                print("  REAPER %s path [%s]: %s" % (
                    kind, ", ".join(e.get("keys", [])) or "default, assumed",
                    ";".join(e.get("dirs", []))))
            dirs = []
            for fmt, path in items:
                print("  %s" % path)
                top = plugin_folder(fmt, path)
                if top not in dirs:
                    dirs.append(top)
            print("  Fix: add %s in REAPER Preferences > Plug-ins (VST / "
                  "CLAP / LV2 path list), then Re-scan;" % ", ".join(dirs))
            print("  or symlink the plugin into ~/.vst, ~/.vst3, ~/.clap "
                  "or ~/.lv2.")
        for label, items in carla_out.items():
            print("Outside the Carla paths saved in the project on %s:"
                  % label)
            for w, path in items:
                print("  %s: %s" % (w["name"], path))
                print("    Carla %s path: %s" % (w["format"].upper(),
                                                ":".join(w["carla_paths"])))
            print("  Fix: in the Carla window, Configure Carla > Paths, add "
                  "%s, then save the project (Carla keeps these paths in "
                  "the project);" % ", ".join(sorted(
                      {plugin_folder(w["format"], p) for w, p in items})))
            print("  or symlink the plugin into a folder from that list, "
                  "e.g. ~/.lv2.")
        if "lmms" in unchecked:
            print("LMMS built-ins (not checked): "
                  + ", ".join(sorted(unchecked["lmms"])))
        print()

    print(LEGEND)
    if total_missing:
        print("%d plugin(s) are missing or uncertain on at least one host."
              % total_missing)
    return 1 if total_missing else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="plugscan", description="Inventory of Linux audio plugins.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("scan", help="scan this host and write a JSON file")
    sp.add_argument("-o", "--output",
                    help="output file (default: scan-results/<hostname>.json "
                         "next to this script)")
    sp.add_argument("--extra-path", action="append", metavar="FORMAT:DIR",
                    help="extra directory to scan, e.g. vst3:/mnt/plugins "
                         "(can be repeated)")
    sp.add_argument("-q", "--quiet", action="store_true",
                    help="do not print a summary")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("compare", help="compare JSON files from several hosts")
    sp.add_argument("hosts", nargs="*", metavar="HOST",
                    help="host JSON file or host name from scan-results/ "
                         "(default: every file in scan-results/)")
    sp.add_argument("--all", action="store_true",
                    help="list every plugin, not only the differences")
    sp.add_argument("-f", "--only", action="append", metavar="FORMATS",
                    help="only these formats, comma-separated, e.g. lv2,vst "
                         "(vst = vst2+vst3; can be repeated)")
    sp.add_argument("-x", "--exclude", action="append", metavar="FORMATS",
                    help="skip these formats, e.g. jsfx,ladspa")
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("check", help="check Reaper/LMMS projects for "
                                      "missing plugins")
    sp.add_argument("projects", nargs="+", metavar="PROJECT",
                    help=".RPP, .mmp or .mmpz file, or a directory to search")
    sp.add_argument("--host", action="append", metavar="HOST",
                    help="check against this host file or host name from "
                         "scan-results/ (can be repeated); default: scan "
                         "this machine now")
    sp.add_argument("-a", "--all-hosts", action="store_true",
                    help="check against every host in scan-results/")
    sp.add_argument("--missing", action="store_true",
                    help="only list plugins that are missing somewhere")
    sp.add_argument("-f", "--only", action="append", metavar="FORMATS",
                    help="only these formats, comma-separated, e.g. lv2,vst "
                         "(vst = vst2+vst3; can be repeated)")
    sp.add_argument("-x", "--exclude", action="append", metavar="FORMATS",
                    help="skip these formats, e.g. jsfx,ladspa")
    sp.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet "| head"
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
