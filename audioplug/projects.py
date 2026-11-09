"""Find and read DAW projects of every supported type."""

import os

from . import lmms, rpp

PROJECT_EXTS = (".rpp", ".mmp", ".mmpz")
RPP_EXTS = (".rpp", ".rpp-bak")


def is_rpp(path):
    return path.lower().endswith(RPP_EXTS)


def parse_project(path):
    """Wanted plugins of a .RPP / .mmp / .mmpz project."""
    low = path.lower()
    if low.endswith(RPP_EXTS):
        return rpp.plugins(path)
    if low.endswith((".mmp", ".mmpz")):
        return lmms.parse(path)
    raise ValueError("unknown project type: " + path)


def find_projects(paths, exts=PROJECT_EXTS):
    """Files given, plus projects under the directories given ("Backups"
    folders skipped)."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d.lower() != "backups")
                for f in sorted(files):
                    if f.lower().endswith(exts):
                        out.append(os.path.join(root, f))
        else:
            out.append(p)
    return out
