"""lmms2rpp - convert an LMMS project to a REAPER project.

Usage:
    lmms2rpp PROJECT.mmpz [-o DIR] [-n]

Writes into DIR (default: <project dir>/<name>-reaper/):

    <name>.RPP           tracks, MIDI items, sample items, tempo, mixer
                         buses with sends
    <name>-plugins.lua   ReaScript that adds the plugins to the tracks
    <name>-steps.txt     the steps printed below
    <track>.xmz          ZynAddSubFX sounds saved in the project
    <track>.carxp        Carla rack states saved in the project

and prints the tracks with their plugins (original => alternatives) and
the steps for what has to be done by hand. -n prints only, nothing is
written.
"""

import argparse
import signal
import sys
import zlib
import xml.etree.ElementTree as ET

from .. import lmms2rpp


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="lmms2rpp",
        description="Convert an LMMS project (.mmp / .mmpz) to a REAPER "
                    "project, plus a ReaScript that adds the plugins and "
                    "a list of the steps left to do by hand.")
    ap.add_argument("project", help=".mmp / .mmpz file")
    ap.add_argument("-o", "--outdir", metavar="DIR",
                    help="output folder (default: <name>-reaper next to "
                         "the project)")
    ap.add_argument("-n", "--dry-run", action="store_true",
                    help="only print the tracks and steps")
    args = ap.parse_args(argv)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet "| head"
    try:
        c, text = lmms2rpp.convert(args.project, args.outdir,
                                   write=not args.dry_run)
    except (OSError, zlib.error, ET.ParseError) as exc:
        sys.exit("cannot read %s: %s" % (args.project, exc))
    sys.stdout.write(text)
    if not args.dry_run:
        print()
        print("Written to %s" % c.outdir)
    return 0
