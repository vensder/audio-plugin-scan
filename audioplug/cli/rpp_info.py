"""rpp-info - tracks of a REAPER project with their FX chains, in order.

Usage:
    rpp-info PROJECT|DIR [...] [-c | --host HOST ... | -a]

Prints one line per track: the track number and name (indented inside
folders), then its FX in chain order, each with its state:

     2   Kick: ReaEQ (v) -> "Kick comp" ReaComp (-)

(v) = active, (-) = bypassed, (x) = offline. A renamed FX shows its name
in quotes before the plugin name. Containers and Carla racks list what
is inside them in [ ]. Input FX, take FX and the master FX chain are
shown too.

-c checks every plugin against this machine (scanned now), --host / -a
against saved host files, like "plugscan check". Plugins that are not
installed are marked, e.g. "Diva (v, missing)". The exit code is then 1
when anything is missing.
"""

import argparse
import os
import signal
import sys

from .. import rpp
from ..hosts import add_host_args, load_hosts
from ..projects import find_projects, is_rpp

STATE_LEGEND = "(v) = active, (-) = bypassed, (x) = offline"
CHECK_LEGEND = ("missing = not installed, name = only a plugin with the "
                "same name, alt = same name in another format only,\n"
                "path = installed, but outside REAPER's (or Carla's) plugin "
                "paths")
CELL_WORD = {"-": "missing"}


class Report:
    """Formats FX chains; with hosts, marks plugins not installed."""

    def __init__(self, hosts=None):
        self.hosts = hosts or []
        self.missing = 0

    def problems(self, w):
        """'missing' or 'ubuntu: missing, fedora: path'; '' if all yes."""
        out = []
        for h in self.hosts:
            cell = h.status(w, reaper=True)
            if cell != "yes":
                word = CELL_WORD.get(cell, cell)
                out.append(word if len(self.hosts) == 1
                           else "%s: %s" % (h.label, word))
        if out:
            self.missing += 1
        return ", ".join(out)

    def fx(self, fx):
        state = "x" if fx["offline"] else "-" if fx["bypass"] else "v"
        if fx.get("container"):
            text = "%s [%s]" % (fx["name"], self.chain(fx["chain"]))
            return "%s (%s)" % (text, state)
        name = fx["name"]
        if fx["format"] == "jsfx":
            name = os.path.basename(name)
            if name.lower().endswith(".jsfx"):
                name = name[:-5]
        if fx.get("custom"):
            name = '"%s" %s' % (fx["custom"], name)
        inside = []
        for w in fx.get("carla", []):
            p = self.problems(w)
            inside.append(w["name"] + (" (%s)" % p if p else ""))
        if inside:
            name += " [%s]" % ", ".join(inside)
        p = self.problems(fx)
        return "%s (%s%s)" % (name, state, ", " + p if p else "")

    def chain(self, chain):
        return " -> ".join(self.fx(fx) for fx in chain)


def print_project(path, report):
    project = rpp.read(path)
    tracks = rpp.tracks(project)
    width = len(str(len(tracks)))
    pad = " " * (width + 3)
    master = rpp.master_fx(project)
    if master:
        print("Master: " + report.chain(master))
    for t in tracks:
        label = t["name"] or "(unnamed)"
        tags = [x for x, on in (("muted", t["muted"]),
                                ("FX off", not t["fx_on"])) if on]
        if tags:
            label += " [%s]" % ", ".join(tags)
        line = "%*d %s%s" % (width, t["number"], "  " * t["depth"], label)
        if t["fx"]:
            line += ": " + report.chain(t["fx"])
        print(line)
        sub = pad + "  " * t["depth"]
        if t["input_fx"]:
            print("%sinput FX: %s" % (sub, report.chain(t["input_fx"])))
        for take, chain in t["items"]:
            print('%stake "%s": %s' % (sub, take, report.chain(chain)))
    if not tracks and not master:
        print("No tracks.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="rpp-info",
        description="List the tracks of REAPER projects with their FX "
                    "chains in order and the state of each FX.")
    ap.add_argument("projects", nargs="+", metavar="PROJECT",
                    help=".RPP file, or a directory to search")
    ap.add_argument("-c", "--check", action="store_true",
                    help="mark plugins that are not installed on this "
                         "machine (scanned now)")
    add_host_args(ap)
    args = ap.parse_args(argv)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet "| head"

    projects = [p for p in find_projects(args.projects, (".rpp",))
                if is_rpp(p)]
    if not projects:
        sys.exit("no .RPP files found")
    hosts = None
    if args.check or args.host or args.all_hosts:
        hosts = load_hosts(args.host, args.all_hosts)
    report = Report(hosts)

    for i, proj in enumerate(projects):
        if i:
            print()
        print("== %s" % proj)
        try:
            print_project(proj, report)
        except OSError as exc:
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
