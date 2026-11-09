"""Plugin formats, the folders searched for each, and -f / -x filters."""

import os
import re
import sys

# Directory names used under the lib dirs, per format.
FORMAT_DIRS = {
    "vst2": ["vst", "lxvst", "linux_vst"],
    "vst3": ["vst3"],
    "lv2": ["lv2"],
    "clap": ["clap"],
    "ladspa": ["ladspa"],
    "dssi": ["dssi"],
    "jsfx": [],
}

HOME_DIRS = {
    "vst2": ["~/.vst", "~/.lxvst"],
    "vst3": ["~/.vst3"],
    "lv2": ["~/.lv2"],
    "clap": ["~/.clap"],
    "ladspa": ["~/.ladspa"],
    "dssi": ["~/.dssi"],
    "jsfx": ["~/.config/REAPER/Effects", "~/opt/REAPER/InstallData/Effects",
             "/opt/REAPER/InstallData/Effects"],
}

ENV_VARS = {
    "vst2": ["VST_PATH", "LXVST_PATH"],
    "vst3": ["VST3_PATH"],
    "lv2": ["LV2_PATH"],
    "clap": ["CLAP_PATH"],
    "ladspa": ["LADSPA_PATH"],
    "dssi": ["DSSI_PATH"],
    "jsfx": [],
}

LIB_ROOTS = [
    "/usr/lib", "/usr/lib64", "/usr/local/lib", "/usr/local/lib64",
    "/opt/lib", "/opt/lib64",
]

FORMAT_ALIASES = {"vst": ["vst2", "vst3"]}


def parse_formats(values):
    """['lv2,vst', 'clap'] -> {'lv2', 'vst2', 'vst3', 'clap'}; None if empty."""
    out = set()
    for v in values or []:
        for f in v.lower().split(","):
            f = f.strip()
            if not f:
                continue
            fmts = FORMAT_ALIASES.get(f, [f])
            for x in fmts:
                if x not in FORMAT_DIRS:
                    sys.exit("unknown format %r (use: %s, or vst for vst2+vst3)"
                             % (f, ", ".join(FORMAT_DIRS)))
            out.update(fmts)
    return out or None


def format_filter(args):
    """Return a function format -> bool from --only / --exclude."""
    only = parse_formats(args.only)
    excl = parse_formats(args.exclude) or set()
    return lambda f: (only is None or f in only) and f not in excl


def add_format_args(parser):
    """-f/--only and -x/--exclude, as used by compare and check."""
    parser.add_argument("-f", "--only", action="append", metavar="FORMATS",
                        help="only these formats, comma-separated, e.g. "
                             "lv2,vst (vst = vst2+vst3; can be repeated)")
    parser.add_argument("-x", "--exclude", action="append", metavar="FORMATS",
                        help="skip these formats, e.g. jsfx,ladspa")


def file_stem(fname):
    """'reaeq.vst.so' -> 'reaeq', 'Surge XT.vst3' -> 'Surge XT'."""
    for ext in (".vst.so", ".vst3", ".clap", ".so"):
        if fname.lower().endswith(ext):
            return fname[: -len(ext)]
    return fname


def file_key(fname):
    """Match key for a plugin file: basename, lowercase, ".so" dropped."""
    k = os.path.basename(fname.rstrip("/")).lower()
    return k[:-3] if k.endswith(".so") else k


def norm_name(name):
    """Plugin name for loose matching: lowercase letters and digits only."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def short_name(disp):
    """'VST3i: Surge XT (Surge Synth Team) (2->6ch)' -> 'Surge XT'."""
    name = disp.split(": ", 1)[1] if ": " in disp else disp
    while True:
        new = re.sub(r"\s*\([^()]*\)\s*$", "", name)
        if new == name or not new:
            break
        name = new
    return name.strip()
