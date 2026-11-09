"""REAPER: install folders, resource folder and the plugin path lists in
reaper.ini.

REAPER only loads plugins from its own path lists (Preferences >
Plug-ins), stored in reaper.ini. A plugin can be installed and still be
invisible to REAPER, e.g. Fedora puts VST2 in /usr/lib64/vst.
"""

import glob
import os
import re
import shutil

from .formats import short_name

# REAPER resource folder (settings, Effects, UserPlugins, reapack.ini).
RESOURCE_DIR = os.path.expanduser("~/.config/REAPER")

# Where REAPER itself may be installed (the folder with the reaper binary).
INSTALL_DIRS = ["~/opt/REAPER", "/opt/REAPER", "/usr/local/REAPER",
                "/usr/lib/REAPER", "/usr/lib64/REAPER"]

# REAPER ships its own VST2 plugins (ReaEQ, ReaComp, ...) in its install dir.
PLUGIN_DIRS = [
    "~/opt/REAPER/Plugins", "/opt/REAPER/Plugins",
    "/usr/local/REAPER/Plugins", "/usr/lib/REAPER/Plugins",
    "/usr/local/lib/REAPER/Plugins",
]

INI = os.environ.get("REAPER_INI", "~/.config/REAPER/reaper.ini")
# Used when reaper.ini has no VST path yet (REAPER default, assumed).
VST_DEFAULT = ("~/.vst;~/.vst3;/usr/lib/vst;/usr/lib/vst3;"
               "/usr/local/lib/vst;/usr/local/lib/vst3")
# Same for CLAP (what REAPER 7 writes once the list is edited; no lib64).
CLAP_DEFAULT = "/usr/local/lib/clap;/usr/lib/clap;~/.clap;%CLAP_PATH%"
FORMAT_KIND = {"vst2": "vst", "vst3": "vst", "clap": "clap", "lv2": "lv2"}


def plugin_paths(ini=None):
    """Return {"ini": path, "paths": {"vst"|"clap"|"lv2": {...}}} or None.

    Each entry is {"keys": [ini keys], "dirs": [...]}. Keys are matched
    loosely (vstpath*, *clap*path*, *lv2*path*) because their names differ
    between platforms and REAPER versions.
    """
    ini = os.path.expanduser(ini or INI)
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
            for d in split_dirs(val):
                if d not in e["dirs"]:
                    e["dirs"].append(d)
    if "vst" not in out:
        out["vst"] = {"keys": [], "dirs": split_dirs(VST_DEFAULT)}
    if "clap" not in out:
        out["clap"] = {"keys": [], "dirs": split_dirs(CLAP_DEFAULT)}
    return {"ini": ini, "paths": out}


def split_dirs(val):
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


def visible(dirs):
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


def mark_visible(plugins, info):
    """Set rec["reaper"] = True/False where REAPER's path lists are known."""
    if not info:
        return
    vis = {k: visible(v["dirs"]) for k, v in info["paths"].items()}
    for rec in plugins:
        kind = FORMAT_KIND.get(rec["format"])
        if kind not in vis:
            continue
        rec["reaper"] = (rec.get("source") == "reaper"
                         or os.path.realpath(rec["path"]) in vis[kind])


def running():
    """True if a process named "reaper" runs."""
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open("/proc/%s/comm" % pid) as fh:
                    if fh.read().strip() == "reaper":
                        return True
            except OSError:
                pass
    return False


def find_install(explicit=None):
    """Return the REAPER folder (the one holding the reaper binary)."""
    if explicit:
        d = os.path.abspath(os.path.expanduser(explicit))
        return d if os.path.isfile(os.path.join(d, "reaper")) else None
    exe = shutil.which("reaper")
    if exe:
        d = os.path.dirname(os.path.realpath(exe))
        if os.path.isfile(os.path.join(d, "whatsnew.txt")):
            return d
    for c in INSTALL_DIRS:
        d = os.path.expanduser(c)
        if os.path.isfile(os.path.join(d, "reaper")):
            return d
    return None


def _cache_file_key(fname):
    """REAPER's cache writes 'lsp-plugins.so' as 'lsp_plugins.so'."""
    return re.sub(r"[^a-z0-9.]", "_", os.path.basename(fname).lower())


def vst_cache(ini=None):
    """Entries of REAPER's VST plugin cache (reaper-vstplugins64.ini and
    the like, next to reaper.ini): [(file, id, name)], e.g.
    ('lsp_plugins.so', '1668051571', 'Multi-Sampler x12 Stereo (LSP VST)').

    The lines look like
      reaeq.vst.so=<hash>,1919247729<...>,ReaEQ (Cockos)
      lsp_plugins.so<1668051571=<hash>,1668051571,Multi-Sampler ... !!!VSTi
    """
    res = os.path.dirname(os.path.expanduser(ini or INI))
    out = []
    for path in sorted(glob.glob(os.path.join(res, "reaper-vstplugins*.ini"))):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                key, sep, val = line.strip().partition("=")
                parts = val.split(",", 2)
                if not sep or len(parts) < 3:
                    continue
                m = re.match(r"\d+", parts[1])
                name = parts[2].split("!!!", 1)[0].strip()
                if m and m.group() != "0" and name:
                    out.append((key.split("<", 1)[0].lower(), m.group(), name))
    return out


def add_vst_ids(plugins, ini=None):
    """Set rec["vst_ids"] = {id: name} on VST2 / VST3 records from REAPER's
    cache, so plugins inside a shell library (one .so with many plugins)
    can be matched by the id a project stores."""
    files = {}
    for rec in plugins:
        if rec["format"] in ("vst2", "vst3"):
            files.setdefault(_cache_file_key(rec["file"]), []).append(rec)
    for fname, vid, name in vst_cache(ini):
        for rec in files.get(fname, []):
            rec.setdefault("vst_ids", {})[vid] = short_name(name)


# Project lines / blocks written by an extension, by name prefix.
EXTENSION_TOKENS = {"SWS": ("SWS", "S&M")}


def extensions(res=None):
    """Extension libraries in UserPlugins, e.g. ['reaper_sws-x86_64.so']."""
    d = os.path.join(res or RESOURCE_DIR, "UserPlugins")
    return sorted(os.path.basename(p)
                  for p in glob.glob(os.path.join(d, "reaper_*.so")))


def has_extension(installed, name):
    """True if the list from extensions() holds name ('SWS' -> reaper_sws)."""
    pre = "reaper_%s" % name.lower()
    return any(f.lower().startswith(pre) for f in installed)
