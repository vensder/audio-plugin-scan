"""plugin-summary - human-readable Markdown summary of plugscan results.

Usage:
    plugin-summary [SCAN.json ...] [-o DIR | -o -]
    plugin-summary -c HOST_A [HOST_B] [-o DIR]

Reads host files written by "plugscan scan" (default: every
scan-results/*.json in the checkout) and writes one Markdown file per
host (default: scan-results/<host>.md, next to its .json). "-o -" prints
to stdout instead.

Plugins are grouped by name, with the formats each one is installed in:

    - Surge XT: clap, lv2, vst3

Sections: system plugins, plugins in the home dir, Carla, REAPER (bundled
FX, other components, JSFX by folder) and LMMS (bundled LADSPA), as far as
they show up in the scan. Each heading shows how many plugins it lists,
counting a plugin once whatever formats it has.

-c HOST_A HOST_B compares two host files (or host names in scan-results/)
and lists, both ways, the plugins one host has and the other lacks: names
missing completely, names the other host has only in other formats (or,
for an LV2 bundle, with other plugins inside), and JSFX by folder.
Plugins are matched like "plugscan compare": file / LV2 URI / JSFX path,
then name, plus VST ids inside shell libraries. With only HOST_A, it is
compared with this machine, scanned now (nothing is written to
scan-results/). -p NAME (with -c) keeps only plugins whose name contains
NAME and lists what each host has of them first.
"""

import argparse
import json
import os
import re
import sys

from ..common import RESULTS_DIR
from ..formats import norm_name
from ..hosts import Host, all_result_files, live_host, plugin_key, vst_id_key

# Longest first, so "reaeq.vst.so" loses ".vst.so", not just ".so".
_EXTS = (".vst.so", ".vst3", ".clap", ".lv2", ".so")


def stem(p):
    """Plugin name without the file extension: 'Surge XT.lv2' -> 'Surge XT'.
    LV2 bundles use the bundle name, so all plugins of one bundle
    (lsp-plugins.lv2, calf.lv2, ...) end up on one line."""
    name = p["file"] if p["format"] in ("lv2", "vst2", "vst3", "clap",
                                        "ladspa", "dssi") else p["name"]
    name = os.path.basename(name)
    for ext in _EXTS:
        if name.lower().endswith(ext):
            return name[:-len(ext)]
    return name


def key(name):
    """Match key: 'libTAL-NoiseMaker' == 'TAL-NoiseMaker',
    'amsynth_vst' == 'amsynth', 'alias_1407' == 'alias-swh', case and
    punctuation ignored."""
    k = name.lower()
    if k.startswith("lib"):
        k = k[3:]
    # "alias_1407" (SWH LADSPA id) == "alias-swh" (its LV2 port).
    k = re.sub(r"([-_ ]vst|-swh|-ladspa|_\d+)$", "", k)
    return re.sub(r"[^a-z0-9]", "", k) or name.lower()


def group(plugins):
    """[(display name, formats, lv2 plugin count)], sorted by name."""
    groups = {}
    for p in plugins:
        name = stem(p)
        g = groups.setdefault(key(name), {"names": [], "formats": set(),
                                          "lv2": set()})
        g["names"].append((p["format"] == "vst2", name))
        g["formats"].add(p["format"])
        if p["format"] == "lv2":
            g["lv2"].add(p.get("id") or p["name"])
    out = []
    for g in groups.values():
        # Prefer a non-VST2 spelling ("TAL-NoiseMaker", not "libTAL-...").
        name = sorted(g["names"])[0][1]
        out.append((name, sorted(g["formats"]), len(g["lv2"])))
    return sorted(out, key=lambda x: x[0].lower())


def formats_text(formats, n_lv2):
    """'clap, lv2 (52 plugins), vst3'."""
    fmts = ", ".join(formats)
    if n_lv2 > 1:
        fmts = fmts.replace("lv2", "lv2 (%d plugins)" % n_lv2)
    return fmts


def plugin_lines(plugins):
    return ["- %s: %s" % (name, formats_text(formats, n_lv2))
            for name, formats, n_lv2 in group(plugins)]


def is_carla(p):
    return any(n.lower().startswith(("carla", "libcarla"))
               for n in (p["name"], stem(p)))


def is_home(p, home):
    return p["source"] == "home" or (
        home and (p["path"] + "/").startswith(home + "/"))


def section(out, title, lines, level=2):
    if not lines:
        return
    out.append("")
    out.append("#" * level + " " + title)
    out.append("")
    out.extend(lines)


def counted(out, title, lines, level=2):
    """Section titled "Title (N)", N = number of lines (plugins)."""
    section(out, "%s (%d)" % (title, len(lines)), lines, level)


def jsfx_lines(jsfx):
    """One line per JSFX folder; returns (lines, number of JSFX)."""
    folders = {}
    for p in jsfx:
        top, _, name = p["name"].partition("/")
        if not name:
            top, name = "(top level)", top
        folders.setdefault(top, set()).add(name)
    lines = ["- %s (%d): %s" % (f, len(n), ", ".join(sorted(n)))
             for f, n in sorted(folders.items(), key=lambda x: x[0].lower())]
    return lines, sum(len(n) for n in folders.values())


def summary(scan):
    host = scan.get("host", "?")
    user = scan.get("user", "")
    home = "/root" if user == "root" else ("/home/" + user if user else "")
    plugins = scan.get("plugins", [])

    jsfx = [p for p in plugins if p["format"] == "jsfx"]
    reaper = [p for p in plugins if p["source"] == "reaper"]
    lmms = [p for p in plugins if p["source"] == "lmms"]
    carla = [p for p in plugins if is_carla(p) and p not in reaper]
    rest = [p for p in plugins if p["format"] != "jsfx"
            and p["source"] not in ("reaper", "lmms") and not is_carla(p)]
    home_pl = [p for p in rest if is_home(p, home)]
    system_pl = [p for p in rest if not is_home(p, home)]

    counts = {}
    for p in plugins:
        counts[p["format"]] = counts.get(p["format"], 0) + 1

    out = ["# Audio plugins on %s" % host, ""]
    out.append("- OS: %s" % scan.get("os", "?"))
    out.append("- User: %s" % (user or "?"))
    out.append("- Scanned: %s" % scan.get("generated", "?"))
    out.append("- Plugin files/entries: %d (%s)" % (
        len(plugins), ", ".join("%s %d" % (f, counts[f])
                                for f in sorted(counts))))

    counted(out, "System plugins", plugin_lines(system_pl))
    counted(out, "Home plugins in `%s`" % (home or "~"),
            plugin_lines(home_pl))

    if carla:
        lines, uniq = [], set()
        for fmt in sorted(set(p["format"] for p in carla)):
            names = sorted(set(stem(p) if fmt != "lv2" else p["name"]
                               for p in carla if p["format"] == fmt
                               and not p["name"].lower().startswith(
                                   ("libcarla", "carla-bridge", "carlastyle"))))
            uniq.update(key(n) for n in names)
            if names:
                lines.append("- %s: %s" % (fmt, ", ".join(names)))
        tools = [p for p in carla if p["name"].lower().startswith(
            ("libcarla", "carla-bridge", "carlastyle"))]
        if tools:
            lines.append("- plus %d Carla helper libraries" % len(tools))
        section(out, "Carla (%d)" % len(uniq), lines)

    if reaper or jsfx or "reaper" in scan:
        out.extend(["", "## REAPER"])
        if "reaper" in scan:
            r = scan["reaper"]
            lines = ["- reaper.ini: `%s`" % r.get("ini", "?")]
            for fmt, info in sorted(r.get("paths", {}).items()):
                # Backticks: a bare "~/.vst; ~/.vst3" renders as strikethrough.
                lines.append("- %s paths: %s" % (
                    fmt, "; ".join("`%s`" % d for d in info.get("dirs", []))))
            hidden = plugin_lines([p for p in rest + carla
                                   if p.get("reaper") is False])
            if hidden:
                lines.append("")
                lines.append("Installed, but outside REAPER's plugin paths "
                             "(%d):" % len(hidden))
                lines.append("")
                lines.extend(hidden)
            section(out, "Plugin paths", lines, 3)
        fx = [p for p in reaper if p["file"].endswith(".vst.so")]
        other = [p for p in reaper if p not in fx]
        counted(out, "FX, bundled", plugin_lines(fx), 3)
        counted(out, "Other components, bundled", plugin_lines(other), 3)
        if jsfx:
            lines, n = jsfx_lines(jsfx)
            section(out, "JSFX (%d)" % n, lines, 3)

    if lmms:
        out.extend(["", "## LMMS"])
        for fmt in sorted(set(p["format"] for p in lmms)):
            names = sorted(set(stem(p) for p in lmms if p["format"] == fmt),
                           key=str.lower)
            section(out, "Bundled %s (%d)" % (fmt.upper(), len(names)),
                    [", ".join(names)], 3)
    return "\n".join(out) + "\n"


def vst_names(host):
    """(format, normalized name) of every plugin inside VST shell libraries
    on host, from REAPER's cache at scan time."""
    return {(r["format"], norm_name(n)) for r in host.data["plugins"]
            for n in r.get("vst_ids", {}).values()}


def present(rec, host, shell_names):
    """True if host has the plugin of rec (same format): by file / LV2 URI /
    JSFX path, by name, or by VST id or name inside a VST shell library
    (LSP's single lsp-plugins.so vs one .so per plugin)."""
    fmt = rec["format"]
    wants = [{"format": fmt, "key": plugin_key(rec), "name": rec["name"]}]
    wants += [{"format": fmt, "key": vst_id_key(vid, vname), "name": vname,
               "vst_id": vid} for vid, vname in rec.get("vst_ids", {}).items()]
    return any(host.match(w) in ("yes", "name")
               or (fmt, norm_name(w["name"])) in shell_names for w in wants)


def name_match(rec, names):
    """True if a name in names is part of the plugin's name, file name or
    the name of a plugin inside it (VST shell), case and punctuation
    ignored: 'dexed' matches Dexed.vst3 and libDexed.so."""
    cands = [rec["name"], stem(rec)] + list(rec.get("vst_ids", {}).values())
    return any(norm_name(n) in norm_name(c) for n in names for c in cands)


def only(host, names):
    """host with just the plugins matching names."""
    data = dict(host.data, plugins=[r for r in host.data["plugins"]
                                    if name_match(r, names)])
    return Host(data, host.label)


def compare(a, b, names=None):
    """Markdown: what each of two hosts has that the other one lacks.
    With names, only plugins whose name contains one of them, plus what
    each host has of them."""
    out = ["# Audio plugins: %s vs %s" % (a.label, b.label), ""]
    for h in (a, b):
        out.append("- %s: %s, %d plugin files/entries, scanned %s" % (
            h.label, h.data.get("os", "?"), len(h.data["plugins"]),
            h.data.get("generated", "?")))
    if names:
        out.append("- Only plugins matching: %s" % ", ".join(names))
        a, b = only(a, names), only(b, names)
        for h in (a, b):
            lines = plugin_lines([r for r in h.data["plugins"]
                                  if r["format"] != "jsfx"])
            lines += jsfx_lines([r for r in h.data["plugins"]
                                 if r["format"] == "jsfx"])[0]
            section(out, "On %s (%d)" % (h.label, len(lines)),
                    lines or ["- none"])
        if not a.data["plugins"] and not b.data["plugins"]:
            return "\n".join(out) + "\n"
    for x, y in ((a, b), (b, a)):
        shell_names = vst_names(y)
        missing = [r for r in x.data["plugins"]
                   if not present(r, y, shell_names)]
        jsfx = [r for r in missing if r["format"] == "jsfx"]
        rest = [r for r in missing if r["format"] != "jsfx"]
        # Formats y has under each name, to tell "missing" from "only in
        # other formats, or other plugins of an LV2 bundle".
        y_formats = {}
        for r in y.data["plugins"]:
            if r["format"] != "jsfx":
                for n in [stem(r)] + list(r.get("vst_ids", {}).values()):
                    y_formats.setdefault(key(n), set()).add(r["format"])
        gone, other = [], []
        for name, formats, n_lv2 in group(rest):
            line = "- %s: %s" % (name, formats_text(formats, n_lv2))
            have = y_formats.get(key(name))
            if not have:
                gone.append(line)
                continue
            if "lv2" in formats and "lv2" in have:
                lv2 = sorted(set(r["name"] for r in rest if r["format"] == "lv2"
                                 and key(stem(r)) == key(name)), key=str.lower)
                line += " [%s]" % ", ".join(lv2)
            other.append("%s (%s has %s)" % (line, y.label,
                                             ", ".join(sorted(have))))
        title = "On %s, missing on %s" % (x.label, y.label)
        counted(out, title, gone)
        counted(out, "On %s, other formats or plugins on %s"
                % (x.label, y.label), other)
        if jsfx:
            lines, n = jsfx_lines(jsfx)
            section(out, "%s: JSFX (%d)" % (title, n), lines)
        if not missing:
            out.extend(["", "Everything on %s is also on %s." % (x.label,
                                                                y.label)])
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Write a Markdown summary of plugscan host files.")
    ap.add_argument("files", nargs="*", metavar="SCAN.json",
                    help="host files (default: %s/*.json)" % RESULTS_DIR)
    ap.add_argument("-o", "--out", metavar="DIR",
                    help="output dir (default: next to each .json); "
                         "'-' prints to stdout")
    ap.add_argument("-c", "--compare", nargs="+", metavar="HOST",
                    help="compare two hosts (host file or host name from "
                         "scan-results/; with one host, compare it with "
                         "this machine, scanned now): what each one lacks; "
                         "prints to stdout, or writes DIR/A-vs-B.md with "
                         "-o DIR")
    ap.add_argument("-p", "--plugin", action="append", metavar="NAME",
                    help="with -c: only plugins whose name contains NAME, "
                         "case and punctuation ignored (can be repeated)")
    args = ap.parse_args(argv)
    if args.plugin and not args.compare:
        ap.error("-p works with -c")

    if args.compare:
        if args.files:
            ap.error("use either SCAN.json files or -c HOST [HOST]")
        if len(args.compare) > 2:
            ap.error("-c takes one or two hosts")
        try:
            a = Host.load(args.compare[0])
            b = (Host.load(args.compare[1]) if len(args.compare) == 2
                 else live_host())
        except (OSError, ValueError) as e:
            sys.exit(str(e))
        text = compare(a, b, args.plugin)
        if not args.out or args.out == "-":
            sys.stdout.write(text)
            return
        os.makedirs(args.out, exist_ok=True)
        dest = os.path.join(args.out, "%s-vs-%s.md" % (a.data.get("host", a.label),
                                                b.data.get("host", b.label)))
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s" % dest)
        return

    files = args.files or all_result_files()
    if not files:
        sys.exit("no scan files found (run plugscan scan first)")
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                scan = json.load(fh)
        except (OSError, ValueError) as e:
            sys.exit("%s: %s" % (f, e))
        text = summary(scan)
        if args.out == "-":
            sys.stdout.write(text)
            continue
        out_dir = args.out or os.path.dirname(os.path.abspath(f))
        os.makedirs(out_dir, exist_ok=True)
        dest = os.path.join(out_dir,
                            "%s.md" % os.path.splitext(os.path.basename(f))[0])
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s" % dest)
