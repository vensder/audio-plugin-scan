"""plugscan - inventory of installed Linux audio plugins.

Usage:
    plugscan scan    [-o FILE] [--extra-path FORMAT:DIR ...] [-q]
    plugscan compare [HOST ...] [--all] [-f FORMATS] [-x FORMATS]
    plugscan check   PROJECT|DIR [...] [--host HOST ... | -a] [--missing]
                     [-f FORMATS] [-x FORMATS]
    plugscan links   [--missing] [--link] [--relink [-y] [--force]] [-n]
                     [-f FORMATS] [-x FORMATS]

Writes a JSON file (default: scan-results/<hostname>.json in the
checkout) listing every VST2, VST3, LV2, CLAP, LADSPA, DSSI and JSFX
plugin found in the standard home and system locations, plus any
directories listed in VST_PATH, LXVST_PATH, VST3_PATH, LV2_PATH,
CLAP_PATH, LADSPA_PATH and DSSI_PATH.
"""

import argparse
import datetime
import json
import os
import signal
import sys

from .. import links, reaper, rpp
from ..common import RESULTS_DIR, ask
from ..formats import FORMAT_DIRS, add_format_args, format_filter
from ..hosts import (LEGEND, Host, add_host_args, all_result_files,
                     load_hosts, plugin_folder, plugin_key)
from ..projects import find_projects, is_rpp, parse_project
from ..scanner import scan


def cmd_scan(args):
    extra = []
    for item in args.extra_path or []:
        if ":" not in item:
            sys.exit("--extra-path must look like FORMAT:DIR, got %r" % item)
        f, d = item.split(":", 1)
        if f not in FORMAT_DIRS:
            sys.exit("unknown format %r (use one of: %s)"
                     % (f, ", ".join(FORMAT_DIRS)))
        extra.append((f, d))

    data = scan(extra)
    out = args.output or os.path.join(RESULTS_DIR, data["host"] + ".json")
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    if not args.quiet:
        counts = {}
        for p in data["plugins"]:
            counts[p["format"]] = counts.get(p["format"], 0) + 1
        print("Host: %s (%s)" % (data["host"], data["os"]))
        for fmt in FORMAT_DIRS:
            print("  %-7s %5d" % (fmt, counts.get(fmt, 0)))
        print("  %-7s %5d" % ("total", len(data["plugins"])))
        print_reaper(data)
        print("Wrote %s" % out)


def print_reaper(data, formats=None):
    """Print REAPER's plugin path lists recorded in a scan."""
    info = data.get("reaper")
    if not info:
        return
    print("REAPER plugin paths (%s):" % info["ini"])
    for kind in ("vst", "clap", "lv2"):
        if formats and kind not in formats:
            continue
        e = info["paths"].get(kind)
        if not e:
            continue
        src = ", ".join(e["keys"]) or "not set, REAPER default assumed"
        print("  %-4s %s  [%s]" % (kind, ";".join(e["dirs"]), src))
    hidden = [r for r in data["plugins"] if r.get("reaper") is False]
    if hidden:
        print("  %d plugin(s) are outside these paths, REAPER will not "
              "see them." % len(hidden))


def print_table(rows, hosts, title_col="plugin"):
    """rows: list of (format, label, [cell per host])."""
    w_fmt = max([len("format")] + [len(r[0]) for r in rows])
    w_lab = min(60, max([len(title_col)] + [len(r[1]) for r in rows]))
    w_cols = [max(4, len(h.label)) for h in hosts]
    head = "%-*s  %-*s" % (w_fmt, "format", w_lab, title_col)
    for h, w in zip(hosts, w_cols):
        head += "  %-*s" % (w, h.label)
    print(head)
    print("-" * len(head))
    for fmt, label, cells in rows:
        if len(label) > w_lab:
            # keep the end: it is the part that tells long paths apart
            label = "..." + label[-(w_lab - 3):]
        line = "%-*s  %-*s" % (w_fmt, fmt, w_lab, label)
        for c, w in zip(cells, w_cols):
            line += "  %-*s" % (w, c)
        print(line.rstrip())


def cmd_compare(args):
    paths = args.hosts or all_result_files()
    if len(paths) < 2:
        sys.exit("need at least two host files (found %d in %s)"
                 % (len(paths), RESULTS_DIR))
    hosts = [Host.load(p) for p in paths]
    keep = format_filter(args)
    wanted = {}
    for h in hosts:
        for rec in h.data["plugins"]:
            if not keep(rec["format"]):
                continue
            k = (rec["format"], plugin_key(rec))
            wanted.setdefault(k, {"format": rec["format"], "key": k[1],
                                  "name": rec["name"]})
    rows = []
    for k in sorted(wanted, key=lambda k: (k[0], wanted[k]["name"].lower())):
        w = wanted[k]
        cells = [h.match(w) for h in hosts]
        if args.all or any(c != "yes" for c in cells):
            label = w["name"]
            if w["format"] == "lv2":
                label += "  <" + w["key"] + ">"
            rows.append((w["format"], label, cells))
    for h in hosts:
        print("%s: %s, %d plugins, scanned %s" % (
            h.label, h.data.get("os", "?"), len(h.data["plugins"]),
            h.data.get("generated", "?")))
    print()
    if not rows:
        print("All hosts have the same plugins.")
        return
    print_table(rows, hosts)
    print()
    print(LEGEND)
    if not args.all:
        print("%d of %d plugins differ (use --all to list every plugin)."
              % (len(rows), len(wanted)))


def cmd_check(args):
    hosts = load_hosts(args.host, args.all_hosts)

    projects = find_projects(args.projects)
    if not projects:
        sys.exit("no .RPP / .mmp / .mmpz files found")

    total_missing = 0
    for proj in projects:
        try:
            wanted = parse_project(proj)
        except Exception as exc:  # bad file should not stop the run
            print("== %s\n   cannot read: %s\n" % (proj, exc))
            continue
        uniq, seen = [], set()
        for w in wanted:
            k = (w["format"], w["key"])
            if k not in seen:
                seen.add(k)
                uniq.append(w)

        rows, unchecked, missing = [], {}, 0
        outside, carla_out = {}, {}
        keep = format_filter(args)
        uniq = [w for w in uniq if w.get("unchecked") or keep(w["format"])]
        for w in uniq:
            if w.get("unchecked"):
                unchecked.setdefault(w["format"], set()).add(w["name"])
                continue
            cells = [h.status(w, reaper=is_rpp(proj)) for h in hosts]
            for h, c in zip(hosts, cells):
                if c != "path":
                    continue
                if w.get("carla_paths") is not None:
                    carla_out.setdefault(h.label, []).append(
                        (w, h.found(w)[0]["path"]))
                else:
                    for r in h.found(w):
                        outside.setdefault(h.label, []).append(
                            (w["format"], r["path"]))
            if any(c != "yes" for c in cells):
                missing += 1
            elif args.missing:
                continue
            rows.append((w["format"], w["display"], cells))
        total_missing += missing

        print("== %s" % proj)
        if rows:
            print_table(rows, hosts)
        elif not uniq:
            print("No plugins found.")
        else:
            print("All plugins present.")
        for label, items in outside.items():
            print("Outside REAPER's plugin paths on %s:" % label)
            h = [x for x in hosts if x.label == label][0]
            info = h.data.get("reaper") or {}
            for kind in sorted({reaper.FORMAT_KIND[f] for f, _ in items}):
                e = info.get("paths", {}).get(kind, {})
                print("  REAPER %s path [%s]: %s" % (
                    kind, ", ".join(e.get("keys", [])) or "default, assumed",
                    ";".join(e.get("dirs", []))))
            dirs = []
            for fmt, path in items:
                print("  %s" % path)
                top = plugin_folder(fmt, path)
                if top not in dirs:
                    dirs.append(top)
            print("  Fix: add %s in REAPER Preferences > Plug-ins (VST / "
                  "CLAP / LV2 path list), then Re-scan;" % ", ".join(dirs))
            print("  or symlink the plugin into ~/.vst, ~/.vst3, ~/.clap "
                  "or ~/.lv2.")
        for label, items in carla_out.items():
            print("Outside the Carla paths saved in the project on %s:"
                  % label)
            for w, path in items:
                print("  %s: %s" % (w["name"], path))
                print("    Carla %s path: %s" % (w["format"].upper(),
                                                ":".join(w["carla_paths"])))
            print("  Fix: in the Carla window, Configure Carla > Paths, add "
                  "%s, then save the project (Carla keeps these paths in "
                  "the project);" % ", ".join(sorted(
                      {plugin_folder(w["format"], p) for w, p in items})))
            print("  or symlink the plugin into a folder from that list, "
                  "e.g. ~/.lv2.")
        if is_rpp(proj):
            print_extensions(proj, hosts)
        if "lmms" in unchecked:
            print("LMMS built-ins (not checked): "
                  + ", ".join(sorted(unchecked["lmms"])))
        print()

    print(LEGEND)
    if total_missing:
        print("%d plugin(s) are missing or uncertain on at least one host."
              % total_missing)
    return 1 if total_missing else 0


def print_extensions(proj, hosts):
    """Extensions (SWS) the project has data for, per host."""
    for name in sorted(rpp.extensions(rpp.read(proj))):
        cells = []
        for h in hosts:
            have = h.data.get("reaper_extensions")
            cells.append("%s: %s" % (h.label, "?" if have is None else
                                     "yes" if reaper.has_extension(have, name)
                                     else "-"))
        print("Extension %s: %s" % (name, ", ".join(cells)))
        if any(c.endswith(": ?") for c in cells):
            print("  (? = host file has no extension list: scan it again)")
        if any(c.endswith(": -") for c in cells):
            print("  Install it with: bin/reapack-helper install-%s"
                  % name.lower())


def tilde(path):
    home = os.path.expanduser("~")
    if path == home or path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


LINK_STATE = {
    "linked": "linked",
    "dirlink": "linked",
    "copy": "copy",
    "other": "other",
    "missing": "-",
}


def relink_copy(args, sys_path, home_path, verdict, stamp):
    """--relink for one copy; returns a note for the listing."""
    if verdict == "home newer" and not args.force:
        return "kept: home version is newer (--force to relink)"
    if not args.dry_run and not ask(
            "          Move %s to the backup folder and link it to %s?"
            % (tilde(home_path), sys_path), args.yes):
        return "kept"
    backup = links.relink(sys_path, home_path, stamp, args.dry_run)
    return "%s %s, %s now links to the system copy" % (
        "would move to" if args.dry_run else "moved to", tilde(backup),
        tilde(home_path))


def cmd_links(args):
    want = format_filter(args)
    made = 0
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    results = {}
    for fmt in links.FORMATS:
        if not want(fmt):
            continue
        res = results[fmt] = links.check(fmt)
        rows, broken, elsewhere = res["system"], res["broken"], res["elsewhere"]
        if not (rows or broken or elsewhere):
            continue
        homes = " ".join(tilde(d) for d in links.home_dirs(fmt))
        print("%s  (home: %s)" % (fmt.upper(), homes))
        counts = {}
        for sd, name, state, where in rows:
            counts[state] = counts.get(state, 0) + 1
            if args.missing and state in ("linked", "dirlink"):
                continue
            path = os.path.join(sd, name)
            note, pending = "", None
            if state == "linked":
                note = tilde(where)
            elif state == "dirlink":
                note = "%s is a link to %s" % (tilde(where), sd)
            elif state == "copy":
                text, verdict = links.compare_copy(fmt, path, where)
                note = "%s is a real copy (%s)" % (tilde(where), text)
                if args.relink:
                    pending = (path, where, verdict)
            elif state == "other":
                note = "%s -> %s" % (tilde(where), os.readlink(where))
            elif args.link:
                dst = links.make_link(fmt, path, args.dry_run)
                if dst:
                    made += 1
                    note = "%s %s" % ("would link" if args.dry_run
                                      else "linked now:", tilde(dst))
            print("  %-7s %-40s %s" % (LINK_STATE[state], path, note),
                  flush=True)
            if pending:
                print("          " + relink_copy(args, *pending, stamp=stamp))
        for p, target in broken:
            print("  %-7s %-40s -> %s" % ("broken", tilde(p), target))
        if not args.missing:
            for p, target in elsewhere:
                print("  %-7s %-40s -> %s" % ("home", tilde(p), target))
        linked = counts.get("linked", 0) + counts.get("dirlink", 0)
        parts = [("linked", linked), ("not linked", counts.get("missing", 0)),
                 ("copy in home", counts.get("copy", 0)),
                 ("other link", counts.get("other", 0)),
                 ("broken link", len(broken))]
        print("  %d in system folders: %s" % (len(rows), ", ".join(
            "%d %s" % (n, label) for label, n in parts if n)))
        print()

    groups = links.by_name(results)
    if args.missing:
        groups = [g for g in groups
                  if any(i[2] in ("missing", "copy", "other") for i in g[1])]
    if groups:
        print("By name (more than one format, or a copy in home and system)")
        width = min(30, max(len(g[0]) for g in groups))
        for disp, items in groups:
            cells = []
            for fmt, where, state, sp, hp in items:
                if where == "home":
                    cells.append("%s home" % fmt)
                elif state == "copy":
                    cells.append("%s system + home copy (%s)" % (
                        fmt, links.compare_copy(fmt, sp, hp)[1]))
                else:
                    cells.append("%s system %s" % (fmt, {
                        "linked": "linked", "dirlink": "linked",
                        "other": "other link", "missing": "-"}[state]))
            print("  %-*s %s" % (width, disp, ", ".join(cells)))
        print()

    if args.link:
        print("%s %d link(s)" % ("Would create" if args.dry_run else "Created",
                                 made))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="plugscan", description="Inventory of Linux audio plugins.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("scan", help="scan this host and write a JSON file")
    sp.add_argument("-o", "--output",
                    help="output file (default: "
                         "scan-results/<hostname>.json in the checkout)")
    sp.add_argument("--extra-path", action="append", metavar="FORMAT:DIR",
                    help="extra directory to scan, e.g. vst3:/mnt/plugins "
                         "(can be repeated)")
    sp.add_argument("-q", "--quiet", action="store_true",
                    help="do not print a summary")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("compare", help="compare JSON files from several hosts")
    sp.add_argument("hosts", nargs="*", metavar="HOST",
                    help="host JSON file or host name from scan-results/ "
                         "(default: every file in scan-results/)")
    sp.add_argument("--all", action="store_true",
                    help="list every plugin, not only the differences")
    add_format_args(sp)
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("check", help="check Reaper/LMMS projects for "
                                      "missing plugins")
    sp.add_argument("projects", nargs="+", metavar="PROJECT",
                    help=".RPP, .mmp or .mmpz file, or a directory to search")
    add_host_args(sp)
    sp.add_argument("--missing", action="store_true",
                    help="only list plugins that are missing somewhere")
    add_format_args(sp)
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("links", help="system plugins and their symlinks "
                                      "in ~/.lv2, ~/.vst3, ...")
    sp.add_argument("--missing", action="store_true",
                    help="hide plugins that are already linked")
    sp.add_argument("--link", action="store_true",
                    help="create the missing links in the home folders")
    sp.add_argument("--relink", action="store_true",
                    help="move real copies in home to ~/.local/share/"
                         "audio-plugin-scan/backup/ and link them to the "
                         "system copy (asks for each one)")
    sp.add_argument("-y", "--yes", action="store_true",
                    help="with --relink: do not ask")
    sp.add_argument("--force", action="store_true",
                    help="with --relink: also when the home version is newer")
    sp.add_argument("-n", "--dry-run", action="store_true",
                    help="with --link / --relink: only show what would "
                         "be done")
    add_format_args(sp)
    sp.set_defaults(func=cmd_links)

    args = ap.parse_args(argv)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet "| head"
    return args.func(args) or 0
