"""System plugins and their symlinks in the home folders (~/.lv2 etc.).

Some hosts only look in the home folders (LMMS's Carla, Flatpak DAWs,
Carla racks saved with another distro's paths), so a plugin installed in
/usr/lib64/lv2 can be "missing" there until ~/.lv2 has a link to it.
"""

import datetime
import filecmp
import functools
import glob
import os
import re
import shutil

from .formats import FORMAT_DIRS, HOME_DIRS, LIB_ROOTS, norm_name
from .lv2 import scan_lv2_bundle
from .scanner import _vst3_version, scan_dir

# Formats with separate system and home folders (JSFX has neither).
FORMATS = [f for f in FORMAT_DIRS if FORMAT_DIRS[f]]

EXTS = {"lv2": ".lv2", "vst3": ".vst3", "clap": ".clap"}


def system_dirs(fmt, roots=None):
    """Existing system folders for fmt, one per real path."""
    if roots is None:
        roots = list(LIB_ROOTS) + sorted(glob.glob("/usr/lib/*-linux-gnu*"))
    out, seen = [], set()
    for root in roots:
        for sub in FORMAT_DIRS[fmt]:
            d = os.path.join(root, sub)
            real = os.path.realpath(d)
            if os.path.isdir(d) and real not in seen:
                seen.add(real)
                out.append(d)
    return out


def home_dirs(fmt):
    return [os.path.expanduser(d) for d in HOME_DIRS[fmt]]


def is_plugin(fmt, path):
    """True for a top-level entry of a plugin folder that holds a plugin:
    a bundle (x.lv2, x.vst3, x.clap), a .so file, or a folder with any."""
    ext = EXTS.get(fmt)
    if ext and path.lower().endswith(ext):
        return True
    if not ext and os.path.isfile(path):
        return path.endswith(".so")
    return os.path.isdir(path) and bool(scan_dir(fmt, path))


def stem(name):
    """'Dexed.vst3' -> 'Dexed', 'carla.vst' -> 'carla', 'x.so' -> 'x'."""
    for ext in (".vst3", ".lv2", ".clap", ".vst", ".so"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name


def name_key(name):
    """Group key for one entry: 'Surge XT.vst3' and 'surge-xt.clap' match."""
    return norm_name(stem(name))


def version(fmt, path):
    """Version from a VST3 moduleinfo.json or LV2 Turtle, else None."""
    try:
        if fmt == "vst3" and os.path.isdir(path):
            return _vst3_version(path)[1]
        if fmt == "lv2" and os.path.isdir(path):
            for rec in scan_lv2_bundle(path):
                if rec.get("version"):
                    return rec["version"]
    except (OSError, ValueError):
        pass
    return None


def same_files(a, b):
    """True if a and b (files or folders) hold the same file contents."""
    if os.path.isfile(a) or os.path.isfile(b):
        return (os.path.isfile(a) and os.path.isfile(b)
                and filecmp.cmp(a, b, shallow=False))

    def files(top):
        out = set()
        for root, _, names in os.walk(top):
            for n in names:
                out.add(os.path.relpath(os.path.join(root, n), top))
        return out
    fa, fb = files(a), files(b)
    if fa != fb:
        return False
    return all(filecmp.cmp(os.path.join(a, f), os.path.join(b, f),
                           shallow=False) for f in fa)


def _files(path):
    if os.path.isfile(path):
        return [path]
    out = []
    for root, _, names in os.walk(path):
        out.extend(os.path.join(root, n) for n in names)
    return out


def binary_kind(path):
    """'debug info', 'not stripped' or 'stripped' for the largest .so in
    path (a file or a bundle), None if there is no ELF file."""
    sos = [f for f in _files(path) if f.endswith((".so", ".clap"))
           and os.path.isfile(f)]
    if not sos:
        return None
    try:
        with open(max(sos, key=os.path.getsize), "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if not data.startswith(b"\x7fELF"):
        return None
    if b".debug_info\0" in data:
        return "debug info"
    if b".symtab\0" in data:
        return "not stripped"
    return "stripped"


def newest(path):
    """Date of the newest file in path, as YYYY-MM-DD, or None."""
    times = []
    for f in _files(path):
        try:
            times.append(os.path.getmtime(f))
        except OSError:
            pass
    if not times:
        return None
    return datetime.date.fromtimestamp(max(times)).isoformat()


def copy_info(fmt, path):
    """{'version', 'date', 'binary'} of one copy (values may be None)."""
    return {"version": version(fmt, path), "date": newest(path),
            "binary": binary_kind(path)}


def _vkey(v):
    return [int(x) for x in re.findall(r"\d+", v or "")]


@functools.lru_cache(maxsize=None)
def compare_copy(fmt, sys_path, home_path):
    """Compare a home copy with the system one.

    Returns (text, verdict). text is "same files" or e.g. "different files;
    home 1.1.0, 2026-11-06, debug info; system 1.1.0, 2026-11-09,
    stripped". verdict: "same", "home newer" (higher version), "older"
    (lower home version), "same version" or "unknown".
    """
    if same_files(sys_path, home_path):
        return "same files", "same"
    h, s = copy_info(fmt, home_path), copy_info(fmt, sys_path)

    def desc(i):
        return ", ".join(x for x in (i["version"], i["date"], i["binary"])
                         if x) or "?"
    text = "different files; home %s; system %s" % (desc(h), desc(s))
    if h["version"] and s["version"]:
        hv, sv = _vkey(h["version"]), _vkey(s["version"])
        verdict = ("same version" if hv == sv else
                   "home newer" if hv > sv else "older")
    else:
        verdict = "unknown"
    return text, verdict


BACKUP_DIR = os.path.join("~", ".local", "share", "audio-plugin-scan",
                          "backup")


def relink(sys_path, home_path, stamp, dry_run=False):
    """Move home_path to the backup folder and link it to sys_path.

    Backup: ~/.local/share/audio-plugin-scan/backup/<stamp>/<home folder>/
    <name>, e.g. .../20261111-001200/.vst3/Dexed.vst3. Returns it.
    """
    home = os.path.expanduser("~")
    rel = os.path.relpath(home_path, home)
    if rel.startswith(".." + os.sep):
        rel = home_path.lstrip(os.sep)
    backup = os.path.join(os.path.expanduser(BACKUP_DIR), stamp, rel)
    if not dry_run:
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.move(home_path, backup)
        os.symlink(sys_path, home_path)
    return backup


def _entries(d):
    try:
        return sorted(os.listdir(d), key=str.lower)
    except OSError:
        return []


def check(fmt, roots=None):
    """Return a dict for one format:

    system:  [(sys_dir, name, state, home_path)], state one of
             linked  - a home symlink points to it (home_path)
             dirlink - the home folder itself links to sys_dir
             copy    - home has a real file/folder with the same name
                       (or the same name in other case / spelling)
             other   - home has a symlink with this name to somewhere else
             missing - nothing in home
    broken:  [(home_path, target)] home symlinks whose target is gone
    elsewhere: [(home_path, target)] home symlinks to non-system places
    home_only: [home_path] real plugins in home with no system copy
    """
    sdirs = system_dirs(fmt, roots)
    sys_real = [os.path.realpath(d) for d in sdirs]
    hdirs = [d for d in home_dirs(fmt) if os.path.isdir(d)]

    # Home symlinks by the real path they resolve to.
    links_to = {}
    broken, elsewhere = [], []
    home_real = {}  # name_key -> real (not symlinked) plugin in home
    for hd in hdirs:
        if os.path.islink(hd):
            continue  # whole folder is a link; handled as dirlink
        for name in _entries(hd):
            p = os.path.join(hd, name)
            if not os.path.islink(p):
                if not name.startswith(".") and is_plugin(fmt, p):
                    home_real.setdefault(name_key(name), p)
                continue
            target = os.readlink(p)
            if not os.path.exists(p):
                broken.append((p, target))
                continue
            real = os.path.realpath(p)
            links_to.setdefault(real, []).append(p)
            if not any(real == r or real.startswith(r + os.sep)
                       for r in sys_real):
                elsewhere.append((p, target))

    dir_linked = {os.path.realpath(hd) for hd in hdirs}

    rows, matched = [], set()
    for sd, sreal in zip(sdirs, sys_real):
        for name in _entries(sd):
            p = os.path.join(sd, name)
            if name.startswith(".") or not is_plugin(fmt, p):
                continue
            if sreal in dir_linked:
                hd = next(h for h in hdirs if os.path.realpath(h) == sreal)
                rows.append((sd, name, "dirlink", hd))
                continue
            hits = links_to.get(os.path.realpath(p))
            if hits:
                rows.append((sd, name, "linked", hits[0]))
                continue
            state, where = "missing", None
            for hd in hdirs:
                hp = os.path.join(hd, name)
                if os.path.lexists(hp):
                    where = hp
                    state = "other" if os.path.islink(hp) else "copy"
                    break
            if state == "missing" and name_key(name) in home_real:
                state, where = "copy", home_real[name_key(name)]
            if state == "copy":
                matched.add(where)
            rows.append((sd, name, state, where))
    home_only = sorted((p for p in home_real.values() if p not in matched),
                       key=lambda p: os.path.basename(p).lower())
    return {"system": rows, "broken": broken, "elsewhere": elsewhere,
            "home_only": home_only}


def by_name(results):
    """Group system and home plugins of all formats by name.

    results: {fmt: check(fmt)}. Returns [(display name, [(fmt, where,
    state, sys_path, home_path)])] for names found in more than one
    format or with a real copy in both home and system; where is
    "system" or "home".
    """
    groups = {}
    for fmt, res in results.items():
        for sd, name, state, hp in res["system"]:
            groups.setdefault(name_key(name), []).append(
                (fmt, "system", state, os.path.join(sd, name), hp))
        for hp in res["home_only"]:
            groups.setdefault(name_key(os.path.basename(hp)), []).append(
                (fmt, "home", "home", None, hp))
    out = []
    for key, items in groups.items():
        fmts = {i[0] for i in items}
        if len(fmts) < 2 and not any(i[2] == "copy" for i in items):
            continue
        first = next((i for i in items if i[1] == "system"), items[0])
        disp = stem(os.path.basename(first[3] or first[4]))
        order = list(FORMAT_DIRS)
        items.sort(key=lambda i: (order.index(i[0]), i[1] != "system"))
        out.append((disp, items))
    out.sort(key=lambda g: g[0].lower())
    return out


def make_link(fmt, sys_path, dry_run=False):
    """Link sys_path into the first home folder of fmt; return the link,
    or None if that name is already taken."""
    hd = home_dirs(fmt)[0]
    dst = os.path.join(hd, os.path.basename(sys_path))
    if os.path.lexists(dst):
        return None
    if not dry_run:
        os.makedirs(hd, exist_ok=True)
        os.symlink(sys_path, dst)
    return dst
