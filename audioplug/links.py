"""System plugins and their symlinks in the home folders (~/.lv2 etc.).

Some hosts only look in the home folders (LMMS's Carla, Flatpak DAWs,
Carla racks saved with another distro's paths), so a plugin installed in
/usr/lib64/lv2 can be "missing" there until ~/.lv2 has a link to it.
"""

import glob
import os

from .formats import FORMAT_DIRS, HOME_DIRS, LIB_ROOTS
from .scanner import scan_dir

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
             other   - home has a symlink with this name to somewhere else
             missing - nothing in home
    broken:  [(home_path, target)] home symlinks whose target is gone
    elsewhere: [(home_path, target)] home symlinks to non-system places
    """
    sdirs = system_dirs(fmt, roots)
    sys_real = [os.path.realpath(d) for d in sdirs]
    hdirs = [d for d in home_dirs(fmt) if os.path.isdir(d)]

    # Home symlinks by the real path they resolve to.
    links_to = {}
    broken, elsewhere = [], []
    for hd in hdirs:
        if os.path.islink(hd):
            continue  # whole folder is a link; handled as dirlink
        for name in _entries(hd):
            p = os.path.join(hd, name)
            if not os.path.islink(p):
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

    rows = []
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
            rows.append((sd, name, state, where))
    return {"system": rows, "broken": broken, "elsewhere": elsewhere}


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
