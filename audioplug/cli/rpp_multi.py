"""rpp-multi - one multitimbral synth instance played by several MIDI tracks.

Usage:
    rpp-multi PROJECT.RPP [-p PLUGIN] [-n N] [-u N] [-e] [-o OUT.RPP]
              [--force]

Finds the tracks of PROJECT that use PLUGIN (default: OsTIrus, the
Gearmulator Virus TI) and writes OUT.RPP (default: PROJECT-multi.RPP)
with one instance on a new instrument track and the old tracks turned
into MIDI-only tracks that send their MIDI to it, track 1 on channel 1,
track 2 on channel 2, ... Empty MIDI tracks are added up to N parts
(default 2). The instance and its state are copied from the first track
that has it; the other instances are removed.

-e writes a template instead: only the instrument track and N empty
MIDI tracks ("Part 1" ...), no other tracks and no items.

-u N gives each of the synth's N stereo outputs its own audio track
("OsTIrus out 3/4"), so every part can have its own FX: the instrument
track gets 2*N channels and no master send.
"""

import argparse
import os
import signal
import sys

from .. import multi


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="rpp-multi",
        description="Rewrite a REAPER project so that one instance of a "
                    "multitimbral synth (OsTIrus in Multi mode) is played "
                    "by several MIDI tracks, each on its own MIDI channel.")
    ap.add_argument("project", help=".RPP with the synth on some track")
    ap.add_argument("-p", "--plugin", default="OsTIrus",
                    help="plugin name to look for (default: OsTIrus)")
    ap.add_argument("-n", "--parts", type=int, default=2, metavar="N",
                    help="at least N MIDI tracks / channels (default: 2)")
    ap.add_argument("-e", "--empty", action="store_true",
                    help="template: only the synth and N empty MIDI tracks")
    ap.add_argument("-u", "--outputs", type=int, default=0, metavar="N",
                    help="N stereo outputs of the synth, each to its own "
                         "audio track for FX per part (OsTIrus TI: 3)")
    ap.add_argument("--name", help="instrument track name "
                                   "(default: '<plugin> (multi)')")
    ap.add_argument("-o", "--output", metavar="OUT.RPP",
                    help="output file (default: PROJECT-multi.RPP)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite the output file")
    args = ap.parse_args(argv)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    if args.parts < 1:
        ap.error("-n must be 1 or more")
    if not 0 <= args.outputs <= 32:
        ap.error("-u must be 0-32")
    out = multi.out_path(args.project, args.output)
    if os.path.abspath(out) == os.path.abspath(args.project):
        sys.exit("will not overwrite the source project, use -o")
    if os.path.exists(out) and not args.force:
        sys.exit("%s exists, use --force to overwrite" % out)
    try:
        r = multi.make(args.project, args.plugin, args.parts, args.empty,
                       args.name, args.outputs)
    except OSError as exc:
        sys.exit("cannot read %s: %s" % (args.project, exc))
    except ValueError as exc:
        sys.exit(str(exc))
    print("== %s -> %s" % (args.project, out))
    print("%s copied from track \"%s\"" % (r.fx, r.source))
    for line in r.lines:
        print(line)
    for track, names in r.dropped:
        print("dropped FX of \"%s\": %s" % (track, ", ".join(names)))
    try:
        multi.write(r, out)
    except OSError as exc:
        sys.exit("cannot write %s: %s" % (out, exc))
    print()
    sys.stdout.write(multi.notes(r))
    return 0
