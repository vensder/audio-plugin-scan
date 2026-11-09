"""LV2 bundle reader: a tiny Turtle parser, just enough to find
"<uri> a lv2:Plugin" and "doap:name" / "lv2:minorVersion" etc. at the top
level of LV2 .ttl files."""

import os
import re

from .common import read_text


_TOKEN_RE = re.compile(r'''
      (?P<ws>\s+|\#[^\n]*)
    | (?P<iri><[^>]*>)
    | (?P<str3>"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\')
    | (?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
    | (?P<lang>@[A-Za-z][A-Za-z0-9-]*)
    | (?P<dtype>\^\^)
    | (?P<punct>[;,.\[\]()])
    | (?P<word>[^\s;,\[\]()<>"']+)
''', re.X)


def _tokens(text):
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            pos += 1
            continue
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        val = m.group()
        if kind == "word" and val.endswith(".") and len(val) > 1 \
                and not re.match(r"^[+-]?\d", val):
            # "foo:bar." -> "foo:bar" "."
            yield ("word", val[:-1])
            yield ("punct", ".")
            continue
        yield (kind, val)


def _unquote(tok):
    kind, val = tok
    if kind == "str3":
        return val[3:-3]
    if kind == "str":
        return val[1:-1].encode("utf-8").decode("unicode_escape", "ignore") \
            if "\\" in val else val[1:-1]
    return val


def parse_turtle(text, base=""):
    """Yield (subject, predicate, object) triples at nesting depth 0.

    IRIs are expanded with @prefix declarations; literals are returned as
    plain strings. Blank-node contents are skipped.
    """
    prefixes = {}
    toks = list(_tokens(text))
    i, n = 0, len(toks)

    def expand(tok):
        kind, val = tok
        if kind == "iri":
            iri = val[1:-1]
            if base and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", iri):
                iri = base + iri
            return iri
        if kind == "word":
            if val == "a":
                return "rdf:type"
            if ":" in val:
                p, local = val.split(":", 1)
                if p in prefixes:
                    return prefixes[p] + local
            return val
        return _unquote(tok)

    while i < n:
        kind, val = toks[i]
        if kind in ("word", "lang") and val.lower() in ("@prefix", "prefix"):
            if i + 2 < n:
                name = toks[i + 1][1].rstrip(":")
                prefixes[name] = toks[i + 2][1][1:-1]
            i += 3
            if i < n and toks[i] == ("punct", "."):
                i += 1
            continue
        if kind in ("word", "lang") and val.lower() in ("@base", "base"):
            if i + 1 < n:
                base = toks[i + 1][1][1:-1]
            i += 2
            if i < n and toks[i] == ("punct", "."):
                i += 1
            continue

        # Statement: subject predicate object (, object)* (; predicate ...)* .
        if toks[i] == ("punct", "["):
            subj = None
            depth = 0
            while i < n:
                if toks[i] == ("punct", "["):
                    depth += 1
                elif toks[i] == ("punct", "]"):
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
        else:
            subj = expand(toks[i])
            i += 1
        pred = None
        expect_pred = True
        while i < n:
            tok = toks[i]
            if tok == ("punct", "."):
                i += 1
                break
            if tok == ("punct", ";"):
                expect_pred = True
                i += 1
                continue
            if tok == ("punct", ","):
                i += 1
                continue
            if tok[0] == "punct" and tok[1] in "[(":
                # skip nested blank node / collection
                opener, closer = tok[1], "]" if tok[1] == "[" else ")"
                depth = 0
                while i < n:
                    if toks[i] == ("punct", opener):
                        depth += 1
                    elif toks[i] == ("punct", closer):
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                i += 1
                expect_pred = False
                continue
            if tok[0] in ("lang",):
                i += 1
                continue
            if tok[0] == "dtype":
                i += 2
                continue
            if expect_pred:
                pred = expand(tok)
                expect_pred = False
            else:
                if subj is not None and pred is not None:
                    yield (subj, pred, expand(tok))
            i += 1


RDF_TYPE = "rdf:type"
LV2 = "http://lv2plug.in/ns/lv2core#"
DOAP = "http://usefulinc.com/ns/doap#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"


def scan_lv2_bundle(bundle):
    """Return a list of plugin dicts for one .lv2 bundle directory."""
    manifest = os.path.join(bundle, "manifest.ttl")
    if not os.path.isfile(manifest):
        return []
    base = "file://" + os.path.abspath(bundle) + "/"
    triples = list(parse_turtle(read_text(manifest), base))

    plugins = [s for s, p, o in triples
               if p == RDF_TYPE and o == LV2 + "Plugin"]
    if not plugins:
        return []

    # Follow rdfs:seeAlso to pick up names / versions.
    see_also = {o for s, p, o in triples if p == RDFS + "seeAlso"}
    for ref in sorted(see_also):
        if ref.startswith(base):
            path = os.path.join(bundle, ref[len(base):])
            if os.path.isfile(path):
                triples.extend(parse_turtle(read_text(path), base))

    info = {}
    for s, p, o in triples:
        if s in plugins:
            d = info.setdefault(s, {})
            if p == DOAP + "name" and "name" not in d:
                d["name"] = o
            elif p == LV2 + "minorVersion":
                d["minor"] = o
            elif p == LV2 + "microVersion":
                d["micro"] = o

    out = []
    for uri in plugins:
        d = info.get(uri, {})
        rec = {
            "format": "lv2",
            "name": d.get("name") or uri.rstrip("/").rsplit("/", 1)[-1],
            "id": uri,
            "file": os.path.basename(bundle.rstrip("/")),
            "path": bundle,
        }
        if "minor" in d:
            rec["version"] = "%s.%s" % (d["minor"], d.get("micro", "0"))
        out.append(rec)
    return out
