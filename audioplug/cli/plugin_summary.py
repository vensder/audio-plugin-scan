"""plugin-summary - human-readable Markdown summary of plugscan results.

Usage:
    plugin-summary [SCAN.json ...] [-o DIR | -o -]

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
"""

import argparse
import json
import os
import re
import sys

from ..common import RESULTS_DIR
from ..hosts import all_result_files

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
    k = re.sub(r"([-_ ]vst|-swh|_\d+)$", "", k)
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


def plugin_lines(plugins):
    lines = []
    for name, formats, n_lv2 in group(plugins):
        fmts = ", ".join(formats)
        if n_lv2 > 1:
            fmts = fmts.replace("lv2", "lv2 (%d plugins)" % n_lv2)
        lines.append("- %s: %s" % (name, fmts))
    return lines


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
            folders = {}
            for p in jsfx:
                top, _, name = p["name"].partition("/")
                if not name:
                    top, name = "(top level)", top
                folders.setdefault(top, set()).add(name)
            lines = ["- %s (%d): %s" % (f, len(n), ", ".join(sorted(n)))
                     for f, n in sorted(folders.items(),
                                        key=lambda x: x[0].lower())]
            section(out, "JSFX (%d)" % sum(len(n) for n in folders.values()),
                    lines, 3)

    if lmms:
        out.extend(["", "## LMMS"])
        for fmt in sorted(set(p["format"] for p in lmms)):
            names = sorted(set(stem(p) for p in lmms if p["format"] == fmt),
                           key=str.lower)
            section(out, "Bundled %s (%d)" % (fmt.upper(), len(names)),
                    [", ".join(names)], 3)
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Write a Markdown summary of plugscan host files.")
    ap.add_argument("files", nargs="*", metavar="SCAN.json",
                    help="host files (default: %s/*.json)" % RESULTS_DIR)
    ap.add_argument("-o", "--out", metavar="DIR",
                    help="output dir (default: next to each .json); "
                         "'-' prints to stdout")
    args = ap.parse_args(argv)

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
