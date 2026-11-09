"""REAPER .RPP project reader.

An .RPP file is a tree of blocks:

    <REAPER_PROJECT 0.1 "7.28/linux-x86_64" 1731100000
      <TRACK {GUID}
        NAME Kick
        <FXCHAIN
          BYPASS 0 0 0
          <VST "VST: ReaEQ (Cockos)" reaeq.vst.so 0 "" 1919247729<...> ""
            base64 state
          >
        >
      >
    >

read() returns that tree, plugins() the flat list of plugins used (for
the missing-plugin checks), tracks() the tracks with their FX chains.
"""

import re

from . import carla
from .formats import file_key

_TOKEN = re.compile(r'"[^"]*"|\'[^\']*\'|`[^`]*`|\S+')

# FX block tags and the format each display prefix ("VST3i: ...") means.
FX_TAGS = ("VST", "LV2", "CLAP", "JS", "LADSPA", "DSSI")
_PREFIX = {"VST": "vst2", "VSTI": "vst2", "VST3": "vst3", "VST3I": "vst3",
           "LV2": "lv2", "LV2I": "lv2", "CLAP": "clap", "CLAPI": "clap",
           "LADSPA": "ladspa", "DSSI": "dssi", "DSSII": "dssi"}
# Blocks that hold an FX chain.
CHAIN_TAGS = ("FXCHAIN", "FXCHAIN_REC", "TAKEFX", "MASTERFXLIST",
              "CONTAINER")


def _unq(tok):
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'`":
        return tok[1:-1]
    return tok


def tokens(line):
    """'NAME "Snare top"' -> ['NAME', 'Snare top']"""
    return [_unq(t) for t in _TOKEN.findall(line)]


class Node:
    """One <TAG args ...> block. items holds, in file order, the plain
    lines (str, stripped) and the child blocks (Node)."""

    __slots__ = ("tag", "args", "items")

    def __init__(self, tag, args):
        self.tag, self.args, self.items = tag, args, []

    def nodes(self, tag=None):
        return [n for n in self.items
                if isinstance(n, Node) and (tag is None or n.tag == tag)]

    def lines(self):
        return [s for s in self.items if isinstance(s, str)]

    def value(self, key):
        """Tokens after KEY on the first 'KEY ...' line, or None."""
        for s in self.items:
            if isinstance(s, str) and (s == key or s.startswith(key + " ")):
                return tokens(s)[1:]
        return None

    def walk(self):
        """This block and every block inside it, in file order."""
        yield self
        for n in self.nodes():
            yield from n.walk()


def read(path):
    """Parse an .RPP file; returns the REAPER_PROJECT block."""
    top = Node("", [])
    stack = [top]
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            if s.startswith("<"):
                toks = tokens(s)
                node = Node(toks[0][1:], toks[1:])
                stack[-1].items.append(node)
                stack.append(node)
            elif s == ">":
                if len(stack) > 1:
                    stack.pop()
            else:
                stack[-1].items.append(s)
    projects = top.nodes("REAPER_PROJECT")
    return projects[0] if projects else top


def _display_name(disp):
    """'VST3i: Surge XT (Surge Synth Team) (2->6ch)' -> 'Surge XT'."""
    name = disp.split(": ", 1)[1] if ": " in disp else disp
    while True:
        new = re.sub(r"\s*\([^()]*\)\s*$", "", name)
        if new == name or not new:
            break
        name = new
    return name.strip()


def plugin(node):
    """Wanted-plugin dict for an FX block (VST, LV2, CLAP, JS, ...), or None.

    Keys: format, key, name, display; "custom" is the name given to the
    FX in REAPER (empty if not renamed).
    """
    toks = [node.tag] + node.args
    if node.tag == "JS":
        if len(toks) < 2:
            return None
        return {"format": "jsfx", "key": toks[1].lower(), "name": toks[1],
                "display": "JS: " + toks[1],
                "custom": toks[2] if len(toks) > 2 else ""}
    if node.tag not in FX_TAGS or len(toks) < 3:
        return None
    disp, ident = toks[1], toks[2]
    prefix = disp.split(":", 1)[0].upper() if ":" in disp else node.tag
    fmt = _PREFIX.get(prefix, _PREFIX.get(node.tag, node.tag.lower()))
    if fmt == "lv2":
        key = ident
    elif fmt == "clap":
        # RPP stores the CLAP plugin id, not the file; match by name.
        key = "clap-id:" + ident
    else:
        key = file_key(ident)
    # The FX name set with "Rename FX instance": VST <disp> <file> 0 <name>,
    # CLAP <disp> <id> <name>.
    custom = ""
    if node.tag == "VST" and len(toks) > 4:
        custom = toks[4]
    elif node.tag == "CLAP" and len(toks) > 3:
        custom = toks[3]
    return {"format": fmt, "key": key, "name": _display_name(disp),
            "display": disp, "custom": custom}


def carla_inside(node, w):
    """Plugins inside a Carla-Rack / Carla-Patchbay FX block, else []."""
    if node.tag == "JS" or "carla" not in (
            w["name"] + " " + " ".join(node.args[1:2])).lower():
        return []
    return carla.plugins(carla.b64_lines(node.lines()), w["name"])


def plugins(path):
    """Return the list of wanted plugin dicts used in a .RPP file.

    Plugins loaded inside a Carla rack/patchbay are listed too, from the
    Carla state stored in the project.
    """
    out = []
    for node in read(path).walk():
        if node.tag in FX_TAGS:
            w = plugin(node)
            if w:
                out.append(w)
                out.extend(carla_inside(node, w))
    return out


# ---------------------------------------------------------------- tracks --

def fx_chain(node):
    """FX of a chain block (FXCHAIN, TAKEFX, CONTAINER, ...), in order.

    Each FX is a plugin() dict plus "bypass" and "offline" (bools, from the
    BYPASS line before it) and "carla" (plugins in a Carla rack). A
    container is {"container": True, "name": ..., "chain": [...]}.
    """
    out = []
    bypass = offline = False
    for it in node.items:
        if isinstance(it, str):
            if it.startswith("BYPASS "):
                t = it.split()
                bypass = t[1:2] == ["1"]
                offline = t[2:3] == ["1"]
            continue
        if it.tag == "CONTAINER":
            fx = {"container": True,
                  "name": (it.args[1] if len(it.args) > 1 else "")
                  or "Container", "chain": fx_chain(it)}
        elif it.tag in FX_TAGS:
            fx = plugin(it)
            if not fx:
                continue
            fx["carla"] = carla_inside(it, fx)
        else:
            continue
        fx["bypass"], fx["offline"] = bypass, offline
        out.append(fx)
        bypass = offline = False
    return out


def _chain(node, tag):
    blocks = node.nodes(tag)
    return fx_chain(blocks[0]) if blocks else []


def _ints(vals, n):
    out = []
    for v in (vals or [])[:n]:
        try:
            out.append(int(float(v)))
        except ValueError:
            out.append(0)
    return out + [0] * (n - len(out))


def tracks(project):
    """Tracks of a project (a read() result), in order.

    Each is a dict: number, name, depth (folder level), folder, muted,
    fx_on (the track's FX button), fx, input_fx, and items: a list of
    (take name, FX chain) for takes with take FX.
    """
    out, depth = [], 0
    for i, t in enumerate(project.nodes("TRACK"), 1):
        name = (t.value("NAME") or [""])[0]
        bus, change = _ints(t.value("ISBUS"), 2)
        items = []
        for item in t.nodes("ITEM"):
            take = ""
            for it in item.items:
                if isinstance(it, str):
                    if it.startswith("NAME"):
                        take = (tokens(it)[1:] or [""])[0]
                elif it.tag == "TAKEFX":
                    chain = fx_chain(it)
                    if chain:
                        items.append((take, chain))
        out.append({
            "number": i, "name": name, "depth": depth, "folder": bus == 1,
            "muted": _ints(t.value("MUTESOLO"), 1)[0] == 1,
            "fx_on": (t.value("FX") or ["1"])[0] != "0",
            "fx": _chain(t, "FXCHAIN"),
            "input_fx": _chain(t, "FXCHAIN_REC"),
            "items": items,
        })
        # ISBUS 1 1 opens a folder, ISBUS 2 -N closes N levels.
        depth = max(0, depth + change)
    return out


def master_fx(project):
    return _chain(project, "MASTERFXLIST")
