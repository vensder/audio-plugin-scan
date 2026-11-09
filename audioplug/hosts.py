"""Host files (scan results) and matching wanted plugins against them.

A plugin is identified by (format, key). key is the LV2 URI, the path
under Effects for JSFX, or the file basename (lowercased, ".so" dropped)
for every other format. When the key does not match, the plugin name is
tried as a fallback.
"""

import glob
import json
import os
import sys

from .common import RESULTS_DIR
from .formats import FORMAT_DIRS, file_key, norm_name
from .scanner import scan

LEGEND = ("yes = installed, name = only a plugin with the same name, "
          "alt = same name in another format only, - = missing,\n"
          "path = installed, but outside REAPER's (or Carla's) plugin paths")


def plugin_key(rec):
    if rec["format"] == "lv2" and rec.get("id"):
        return rec["id"]
    if rec["format"] == "jsfx":
        return rec["file"].lower()
    return file_key(rec["file"])


def vst_id_key(vid, name):
    """VST unique id plus the plugin name (ids alone can collide)."""
    return "vstid:%s:%s" % (vid, norm_name(name))


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
            # Plugins inside a VST shell library (e.g. LSP's single
            # lsp-plugins.so), from REAPER's plugin cache at scan time.
            for vid, vname in rec.get("vst_ids", {}).items():
                k = vst_id_key(vid, vname)
                self.keys.add((fmt, k))
                self.recs.setdefault((fmt, k), []).append(rec)

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
                or self.recs.get((fmt, vst_id_key(want.get("vst_id"),
                                                  want["name"])))
                or self.recs.get((fmt, "name:" + n)) or [])

    def match(self, want, reaper=False):
        """Return 'yes', 'name', 'alt', 'path' or '-' for a wanted plugin.

        With reaper=True, a plugin installed only outside REAPER's plugin
        paths (as recorded at scan time) is 'path'.
        """
        fmt, n = want["format"], norm_name(want["name"])
        hit = None
        if (fmt, want["key"]) in self.keys or (
                want.get("vst_id") and (fmt, vst_id_key(
                    want["vst_id"], want["name"])) in self.keys):
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

    def status(self, want, reaper=False):
        """match(), plus 'path' for a plugin inside Carla that is installed
        only outside the Carla paths saved in the project.

        reaper=True checks REAPER's plugin paths (for plugins in an .RPP
        that REAPER loads itself, not the ones inside Carla).
        """
        cell = self.match(want, reaper=reaper and not want.get("inside"))
        dirs = want.get("carla_paths")
        if cell == "yes" and dirs is not None:
            recs = self.found(want)
            if recs and not any(in_dirs(x, dirs) for r in recs
                                for x in [r["path"]] + r.get("links", [])):
                return "path"
        return cell


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


def all_result_files():
    return sorted(glob.glob(os.path.join(RESULTS_DIR, "*.json")))


def live_host(label=None):
    """Scan this machine now; label defaults to "<hostname> (live)"."""
    data = scan([])
    return Host(data, label or data["host"] + " (live)")


def load_hosts(names=None, all_hosts=False):
    """Hosts for --host NAME ... / -a; this machine (scanned now) if none."""
    if all_hosts:
        hosts = [Host.load(p) for p in all_result_files()]
        if not hosts:
            sys.exit("no host files in " + RESULTS_DIR)
        return hosts
    if names:
        return [Host.load(p) for p in names]
    return [live_host()]


def add_host_args(parser):
    """--host HOST ... and -a/--all-hosts."""
    parser.add_argument("--host", action="append", metavar="HOST",
                        help="check against this host file or host name from "
                             "scan-results/ (can be repeated); default: scan "
                             "this machine now")
    parser.add_argument("-a", "--all-hosts", action="store_true",
                        help="check against every host in scan-results/")
