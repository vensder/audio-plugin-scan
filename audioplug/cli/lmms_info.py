"""lmms-info - tracks of an LMMS project with their instrument and
effects, in order.

Usage:
    lmms-info PROJECT|DIR [...] [-c | --host HOST ... | -a]

Prints one line per track: the track number and name, then the
instrument and the effect chain, each with its state:

    1 Lead [mixer 1]: tripleoscillator (v) -> LADSPA caps/Plate (-)

(v) = on, (-) = off. A Carla rack lists the plugins inside it in [ ].
The pattern (Beat/Bassline) editor's tracks and the mixer channels with
effects (or used by a track) follow.

-c checks every plugin against this machine (scanned now), --host / -a
against saved host files, like "plugscan check". Plugins that are not
installed are marked, e.g. "VST Dexed (v, missing)". The exit code is
then 1 when anything is missing. LMMS built-in instruments and effects
are not checked.
"""

import argparse
import signal
import sys
import zlib
import xml.etree.ElementTree as ET

from .. import lmms
from ..hosts import add_host_args, load_hosts
from ..projects import find_projects
from .rpp_info import Report

STATE_LEGEND = "(v) = on, (-) = off"
CHECK_LEGEND = ("missing = not installed, name = only a plugin with the "
                "same name, alt = same name in another format only,\n"
                "path = installed, but outside the Carla paths saved in "
                "the project")
EXTS = (".mmp", ".mmpz")


class LmmsReport(Report):
    def __init__(self, hosts=None):
        Report.__init__(self, hosts, reaper=False)

    def slot(self, s):
        name = s["name"]
        inside = []
        for w in s["carla"]:
            p = self.problems(w)
            st = "v" if w.get("active", True) else "-"
            inside.append("%s (%s%s)" % (w["name"], st, ", " + p if p else ""))
        if s["carla"] or name.startswith("Carla"):
            name += " [%s]" % ", ".join(inside)
        w = s["want"]
        p = self.problems(w) if w and not w.get("unchecked") else ""
        return "%s (%s%s)" % (name, "v" if s["on"] else "-",
                              ", " + p if p else "")

    def chain(self, chain):
        return " -> ".join(self.slot(s) for s in chain)


def track_line(num, width, t, report):
    tags = []
    if t["kind"] not in ("instrument", "other"):
        tags.append(t["kind"])
    if t["mixer"] is not None:
        tags.append("mixer %d" % t["mixer"])
    tags += [x for x, on in (("muted", t["muted"]), ("solo", t["solo"]),
                             ("FX off", t["effects"] and not t["fx_on"]))
             if on]
    line = "%*d %s" % (width, num, t["name"] or "(unnamed)")
    if tags:
        line += " [%s]" % ", ".join(tags)
    if t["chain"]:
        line += ": " + report.chain(t["chain"])
    return line


def print_project(path, report):
    song = lmms.song(lmms.read(path))
    if song["version"]:
        print("LMMS %s" % song["version"])
    for title, tracks in (("", song["tracks"]),
                          ("Pattern editor:", song["patterns"])):
        if not tracks:
            continue
        if title:
            print(title)
        width = len(str(len(tracks)))
        for i, t in enumerate(tracks, 1):
            print(track_line(i, width, t, report))
    if not song["tracks"]:
        print("No tracks.")
    used = {t["mixer"] for t in song["tracks"] + song["patterns"]}
    chans = [c for c in song["mixer"]
             if c["num"] == 0 or c["chain"] or c["num"] in used]
    if chans:
        print("Mixer:")
        width = len(str(max(c["num"] for c in chans)))
        for c in chans:
            tags = [x for x, on in (("muted", c["muted"]),
                                    ("solo", c["solo"]),
                                    ("FX off", c["chain"] and not c["fx_on"]))
                    if on]
            line = "%*d %s" % (width, c["num"], c["name"])
            if tags:
                line += " [%s]" % ", ".join(tags)
            if c["chain"]:
                line += ": " + report.chain(c["chain"])
            print(line)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="lmms-info",
        description="List the tracks of LMMS projects with their "
                    "instrument and effects in order and the state of "
                    "each.")
    ap.add_argument("projects", nargs="+", metavar="PROJECT",
                    help=".mmp / .mmpz file, or a directory to search")
    ap.add_argument("-c", "--check", action="store_true",
                    help="mark plugins that are not installed on this "
                         "machine (scanned now)")
    add_host_args(ap)
    args = ap.parse_args(argv)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet "| head"

    projects = [p for p in find_projects(args.projects, EXTS)
                if p.lower().endswith(EXTS)]
    if not projects:
        sys.exit("no .mmp / .mmpz files found")
    hosts = None
    if args.check or args.host or args.all_hosts:
        hosts = load_hosts(args.host, args.all_hosts)
    report = LmmsReport(hosts)

    for i, proj in enumerate(projects):
        if i:
            print()
        print("== %s" % proj)
        try:
            print_project(proj, report)
        except (OSError, zlib.error, ET.ParseError) as exc:
            print("   cannot read: %s" % exc)
    print()
    print(STATE_LEGEND)
    if hosts:
        print("Checked against: %s" % ", ".join(h.label for h in hosts))
        print(CHECK_LEGEND)
        if report.missing:
            print("%d plugin use(s) are missing or uncertain."
                  % report.missing)
            return 1
    return 0
