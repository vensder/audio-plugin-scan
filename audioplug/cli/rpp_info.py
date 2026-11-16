"""rpp-info - tracks of a REAPER project with their FX chains, in order.

Usage:
    rpp-info PROJECT|DIR [...] [-r] [-c | --host HOST ... | -a]

Prints one line per track: the track number and name (indented inside
folders), then its FX in chain order, each with its state:

     2   Kick: ReaEQ (v) -> "Kick comp" ReaComp (-)

(v) = active, (-) = bypassed, (x) = offline. A renamed FX shows its name
in quotes before the plugin name. Containers and Carla racks list what
is inside them in [ ]. Input FX, take FX and the master FX chain are
shown too.

-r adds a mix and routing overview under each track: volume, pan,
channel count, where the track goes (master, parent folder, nothing),
and its receives (<-) and sends (->) with their audio channels, MIDI
channels, volume and pan:

     1 OsTIrus (multi): OsTIrus (v)
         0.0 dB, C, 6 ch, no master send
         <- 2 Noomed2Chord: MIDI all -> ch 1
         -> 4 OsTIrus out 1/2: audio 1/2
     2 Noomed2Chord
         MIDI only (volume and pan do not change the sound)
         -> 1 OsTIrus (multi): MIDI all -> ch 1

-c checks every plugin against this machine (scanned now), --host / -a
against saved host files, like "plugscan check". Plugins that are not
installed are marked, e.g. "Diva (v, missing)". The exit code is then 1
when anything is missing.
"""

import argparse
import math
import os
import signal
import sys

from .. import rpp, virus
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

    def __init__(self, hosts=None, reaper=True):
        self.hosts = hosts or []
        self.reaper = reaper  # check REAPER's plugin paths too
        self.missing = 0

    def problems(self, w):
        """'missing' or 'ubuntu: missing, fedora: path'; '' if all yes."""
        out = []
        for h in self.hosts:
            cell = h.status(w, reaper=self.reaper)
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


def db(vol):
    if vol <= 0:
        return "-inf dB"
    return "%.1f dB" % (20 * math.log10(vol))


def pan(p):
    n = int(round(abs(p) * 100))
    return "C" if n == 0 else ("L%d" if p < 0 else "R%d") % n


def chans(c):
    first, count = c
    if count == 1:
        return str(first + 1)
    return "%d-%d" % (first + 1, first + count) if count > 2 \
        else "%d/%d" % (first + 1, first + 2)


def midi_text(m):
    src, dst = m
    out = "MIDI " + ("all" if src == 0 else "ch %d" % src)
    return out + (" -> ch %d" % dst if dst else "")


def send_text(r):
    parts = []
    if r["audio"]:
        a = "audio " + chans(r["audio"])
        if r["dst"] != r["audio"]:
            a += " -> " + chans(r["dst"])
        parts.append(a)
    if r["midi"]:
        parts.append(midi_text(r["midi"]))
    if not parts:
        parts.append("nothing (audio and MIDI off)")
    if r["audio"]:
        if abs(r["vol"] - 1) > 1e-6:
            parts.append(db(r["vol"]))
        if r["pan"]:
            parts.append("pan " + pan(r["pan"]))
        if r["mode"] != "post-fader":
            parts.append(r["mode"])
    if r["muted"]:
        parts.append("muted")
    return ", ".join(parts)


def fed_channels(t):
    """MIDI channels the track's receives deliver (send dest, else the
    source channel); 'all to original' tells nothing, so it is left out."""
    out = set()
    for r in t["receives"]:
        if r["midi"]:
            src, dst = r["midi"]
            if dst or src:
                out.add(dst or src)
    return out


def virus_parts(t, name, out_sends):
    """Lines for the Virus Multi parts that get MIDI from the receives:
    part, channel, patch, output and the track it ends up on."""
    lines = []
    fed = fed_channels(t)
    for fx in t["fx"]:
        vm = fx.get("virus")
        if not vm or not fed:
            continue
        for p in vm["parts"]:
            if p["channel"] not in fed:
                continue
            ch = virus.output_channels(p["output"])
            dest = []
            if ch:
                for dst, r in out_sends:
                    a = r["audio"]
                    if a and a[0] <= ch[0] < a[0] + a[1]:
                        dest.append(name(dst))
                if t["main_send"] and ch[0] < 2:
                    dest.append("parent" if t["parent"] else "master")
            lines.append('part %d: ch %d "%s", %s -> %s' % (
                p["part"], p["channel"], p["patch"],
                virus.output_name(p["output"]),
                ", ".join(dest) or "nothing (no send of these channels)"))
    return lines


def routing(t, tracks, sends):
    """Lines for -r: mix settings, then receives and sends."""
    def name(n):
        return "%d %s" % (n, tracks[n - 1]["name"] if 0 < n <= len(tracks)
                          else "(no track)")

    out_sends = sends.get(t["number"], [])
    midi_only = (not t["fx"] and not t["main_send"] and not t["hwout"]
                 and not any(r["audio"] for _, r in out_sends))
    if midi_only:
        head = ["MIDI only (volume and pan do not change the sound)"]
    else:
        head = [db(t["vol"]), pan(t["pan"])]
        if t["nchan"] != 2:
            head.append("%d ch" % t["nchan"])
        if not t["main_send"]:
            head.append("no master send")
        elif t["parent"]:
            head.append("-> folder " + name(t["parent"]))
        else:
            head.append("-> master")
        if t["hwout"]:
            head.append("%d hardware out%s" % (
                len(t["hwout"]), "s" if len(t["hwout"]) > 1 else ""))
    lines = [", ".join(head)] + virus_parts(t, name, out_sends)
    for r in t["receives"]:
        lines.append("<- %s: %s" % (name(r["src"] + 1), send_text(r)))
    for dst, r in out_sends:
        lines.append("-> %s: %s" % (name(dst), send_text(r)))
    return lines


def print_project(path, report, show_routing=False):
    project = rpp.read(path)
    tracks = rpp.tracks(project)
    width = len(str(len(tracks)))
    pad = " " * (width + 3)
    master = rpp.master_fx(project)
    sends = {}  # source track number -> [(dest number, receive)]
    for t in tracks:
        for r in t["receives"]:
            sends.setdefault(r["src"] + 1, []).append((t["number"], r))
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
        if show_routing:
            for s in routing(t, tracks, sends):
                print(sub + s)
        if t["input_fx"]:
            print("%sinput FX: %s" % (sub, report.chain(t["input_fx"])))
        for take, chain in t["items"]:
            print('%stake "%s": %s' % (sub, take, report.chain(chain)))
    if not tracks and not master:
        print("No tracks.")
    ext = rpp.extensions(project)
    if ext:
        print("Extension data: %s" % ", ".join(sorted(ext)))


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
    ap.add_argument("-r", "--routing", action="store_true",
                    help="also show volume, pan, sends and receives")
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
            print_project(proj, report, args.routing)
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
