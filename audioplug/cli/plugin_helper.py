"""plugin-helper - find and install missing VST2 / VST3 / CLAP / LV2 plugins.

Usage:
    plugin-helper find ITEM [...] [--install] [--yes] [--refresh]
    plugin-helper list

ITEM is a .RPP / .mmp / .mmpz project, a directory with projects, or a
plugin name such as "TyrellN6". Projects are checked against this machine
(a live scan, like "plugscan check"); every plugin that is missing is
looked up in a small built-in catalog of install sources:

  u-he     the latest Linux build listed on u-he.com/products, unpacked and
           its own install.sh run (installs to your home, no sudo)
  github   the latest GitHub release: an .rpm / .deb is installed with
           dnf / apt (sudo, asked first); a .tar / .zip / .deb archive is
           unpacked and its plugin bundles copied to ~/.vst3, ~/.clap,
           ~/.lv2 and ~/.vst
  pkg      a distro package, installed with dnf or apt (sudo, asked first)
  page     no automatic download; the download page is printed

Without --install it only prints what it would do. After installing, the
plugins are scanned again and the result is shown.

Downloads are cached in ~/.cache/plugin-helper. Set GITHUB_TOKEN to raise
the GitHub API rate limit. Missing JSFX are left to reapack-helper.
"""

import argparse
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import unicodedata
import urllib.error
import zipfile

from .. import common
from ..common import ask, fetch, has, write_atomic
from ..formats import norm_name
from ..hosts import live_host
from ..projects import find_projects, parse_project

UHE_INDEX = "https://u-he.com/products/"
UHE_PAGE = "https://u-he.com/products/"

# Where bundles from archives are copied (user-local, no sudo).
DEST = {".vst3": "~/.vst3", ".clap": "~/.clap", ".lv2": "~/.lv2",
        ".vst": "~/.vst"}

# --------------------------------------------------------------- catalog --
# match: regex tried against the plugin name (case-insensitive);
# vendor: optional regex tried against the vendor in the project, e.g.
# "LSP VST" in "VSTi: Multi-Sampler x12 Stereo (LSP VST)".
# Methods are tried in order; the first one usable on this system wins.
# Package names are checked with dnf / apt before anything is installed.

CATALOG = [
    {"title": "Surge XT", "match": r"^Surge XT",
     "methods": [
         {"type": "github", "repo": "surge-synthesizer/releases-xt",
          "rpm": r"^surge-xt-x86_64-.*\.rpm$",
          "deb": r"^surge-xt-linux-x64-.*\.deb$"},
         {"type": "pkg", "dnf": "surge-xt", "apt": "surge-xt"}]},
    {"title": "Dexed", "match": r"^Dexed$",
     "methods": [{"type": "github", "repo": "asb2m10/dexed",
                  "archive": r"-lnx\.zip$"}]},
    {"title": "Cardinal", "match": r"^Cardinal",
     "methods": [{"type": "github", "repo": "DISTRHO/Cardinal",
                  "archive": r"^Cardinal-linux-x86_64-.*\.tar\.gz$"}]},
    {"title": "Dragonfly Reverb", "match": r"^Dragonfly ",
     "methods": [
         {"type": "pkg", "dnf": "dragonfly-reverb",
          "apt": "dragonfly-reverb"},
         {"type": "github", "repo": "michaelwillis/dragonfly-reverb",
          "archive": r"linux-x86_64\.tar\.xz$"}]},
    {"title": "OB-Xd", "match": r"^OB-?Xd",
     "methods": [{"type": "github", "repo": "reales/OB-Xd",
                  "deb": r"\.deb$", "archive": r"\.deb$"}]},
    {"title": "DPF-Plugins",
     "match": r"^(Kars|Nekobi|Ping ?Pong ?Pan|3 ?Band ?(EQ|Splitter)|"
              r"Amplitude ?Imposer|Cycle ?Shifter|Soul ?Force|MVerb|Glitch|"
              r"Ma(Bitcrush|Freeverb|Gigaverb))$",
     "methods": [
         {"type": "pkg", "dnf": "dpf-plugins", "apt": "dpf-plugins"},
         {"type": "github", "repo": "DISTRHO/DPF-Plugins",
          "archive": r"linux-x86_64\.tar\.xz$"}]},
    {"title": "Wolf Shaper", "match": r"^Wolf ?Shaper",
     "methods": [
         {"type": "pkg", "dnf": "wolf-shaper", "apt": "wolf-shaper"},
         {"type": "github", "repo": "wolf-plugins/wolf-shaper",
          "archive": r"linux-x64\.zip$"}]},
    {"title": "Monique", "match": r"^Monique",
     "methods": [{"type": "github",
                  "repo": "surge-synthesizer/monique-monosynth",
                  "archive": r"Linux\.zip$"}]},
    {"title": "JS80P", "match": r"^JS80P",
     # The VST3 bundle (js80p.vst3 folder, copied to ~/.vst3). AVX build;
     # on old CPUs use the sse2 zip from the release page instead.
     "methods": [{"type": "github", "repo": "attilammagyar/js80p",
                  "archive": r"^js80p-[\d_]+-avx-vst3_bundle\.zip$"}]},
    {"title": "Geonkick", "match": r"^Geonkick",
     "methods": [{"type": "pkg", "dnf": "geonkick", "apt": "geonkick"}]},
    {"title": "LSP Plugins", "match": r"^LSP ", "vendor": r"^LSP\b",
     # One .7z with every format; needs 7z or bsdtar to unpack.
     "methods": [{"type": "pkg", "dnf": "lsp-plugins",
                  "apt": "lsp-plugins"},
                 {"type": "github", "repo": "lsp-plugins/lsp-plugins",
                  "archive": r"-Linux-x86_64\.7z$"}]},
    {"title": "Speedrum Lite", "match": r"^Speedrum",
     "methods": [{"type": "page",
                  "url": "https://www.apisonic-audio.com/freeware.html"}]},
    {"title": "MT-PowerDrumKit", "match": r"^MT-?Power ?Drum",
     "methods": [{"type": "page",
                  "url": "https://www.powerdrumkit.com/download76187.php"}]},
    {"title": "x42 Plugins", "match": r"^x42",
     "methods": [{"type": "pkg", "dnf": "x42-plugins",
                  "apt": "x42-plugins"}]},
    {"title": "Calf", "match": r"^Calf ",
     "methods": [{"type": "pkg", "dnf": "calf", "apt": "calf-plugins"}]},
    {"title": "ZynAddSubFX", "match": r"^Zyn",
     "methods": [{"type": "pkg", "dnf": "zynaddsubfx",
                  "apt": "zynaddsubfx"}]},
    {"title": "ZAM Plugins", "match": r"^Zam",
     "methods": [{"type": "pkg", "dnf": "zam-plugins",
                  "apt": "zam-plugins"}]},
    {"title": "Vital", "match": r"^Vital",
     "methods": [{"type": "page", "url": "https://vital.audio/"}]},
    {"title": "TAL", "match": r"^TAL-",
     "methods": [{"type": "page",
                  "url": "https://tal-software.com/products"}]},
    {"title": "Airwindows", "match": r"^Airwin",
     "methods": [{"type": "page",
                  "url": "https://www.airwindows.com/"}]},
]


# ------------------------------------------------------------- download --

def cache_path(name):
    return common.cache_file(common.cache_dir("plugin-helper"), name)


def fetch_cached(url, name, refresh=False):
    """Small text documents (index pages, API answers), kept for a day."""
    return common.fetch_cached(url, common.cache_dir("plugin-helper"), name,
                               refresh)


def download(url):
    """Download a release file into the cache (once) and return its path."""
    path = cache_path(url.rsplit("/", 1)[-1])
    if not os.path.exists(path):
        print("  downloading %s" % url)
        write_atomic(path, fetch(url, timeout=600))
    else:
        print("  using cached %s" % path)
    return path


# ------------------------------------------------------------- sources --

def norm(name):
    s = unicodedata.normalize("NFKD", name)
    return re.sub(r"[^a-z0-9]+", "", s.encode("ascii", "ignore")
                  .decode().lower())


_UHE = None
_UHE_LINK = re.compile(r"https://dl\.u-he\.com/releases/"
                       r"[^\"'\s<>]+?_Linux\.(?:tar\.xz|zip)")


def uhe_version(url):
    """'.../TyrellN6_300_public_beta_16976_Linux.tar.xz' -> '3.0.0'"""
    parts = url.rsplit("/", 1)[-1].split("_")
    return ".".join(parts[1]) if parts[1:] and parts[1].isdigit() else "?"


def uhe_products(refresh=False):
    """Return {product: (version, url)} from the u-he products page."""
    global _UHE
    if _UHE is None:
        _UHE = {}
        try:
            html = fetch_cached(UHE_INDEX, "u-he-products.html",
                                refresh).decode("utf-8", "replace")
        except Exception as exc:
            print("warning: cannot read %s: %s" % (UHE_INDEX, exc),
                  file=sys.stderr)
            return _UHE
        for url in _UHE_LINK.findall(html):
            prod = norm(url.rsplit("/", 1)[-1].split("_")[0])
            _UHE.setdefault(prod, (uhe_version(url), url))
    return _UHE


def uhe_urls(prod, refresh=False):
    """Linux download links for a u-he product, best first.

    The products index links do not always exist (e.g. tyrelln6_300_...
    is 404 while the product page has TyrellN6_300_public_beta_...), so the
    product page is read first and the index link is the last resort.
    """
    out = []
    for i, page in enumerate(("https://u-he.com/products/plug-ins/%s/",
                              "https://u-he.com/products/%s/")):
        page %= prod
        try:
            html = fetch_cached(page, "u-he-%s-%d.html" % (prod, i),
                                refresh).decode("utf-8", "replace")
        except Exception:
            continue
        links = _UHE_LINK.findall(html)
        own = [u for u in links
               if norm(u.rsplit("/", 1)[-1].split("_")[0]) == prod]
        for u in own or links[:1]:
            if u not in out:
                out.append(u)
        if out:
            break
    idx = uhe_products(refresh).get(prod)
    if idx and idx[1] not in out:
        out.append(idx[1])
    return out


def uhe_lookup(name, refresh=False):
    """Match a plugin name such as 'TyrellN6', 'Hive' or 'Uhbik-A'."""
    prods = uhe_products(refresh)
    n = norm(name)
    if not n:
        return None
    if n in prods:
        return n
    for p in prods:  # 'Hive' -> hive2
        if p.startswith(n) and p[len(n):].isdigit():
            return p
    best = [p for p in prods if n.startswith(p) and len(p) >= 4]
    return max(best, key=len) if best else None  # 'Uhbik-A' -> uhbik


def pkg_manager():
    if has("dnf"):
        return "dnf"
    if has("apt-get"):
        return "apt"
    return None


def pkg_available(pm, name):
    if pm == "dnf":
        cmd = ["dnf", "-q", "info", name]
    else:
        cmd = ["apt-cache", "show", name]
    return subprocess.run(cmd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def _ci_glob(text):
    return "".join("[%s%s]" % (c.lower(), c.upper()) if c.isalpha() else
                   ("[%s]" % c if c in "*?[]" else c) for c in text)


_RPM_NEVRA = re.compile(r"^(\S+?)-(?:\d+:)?[^-\s]+-[^-\s]+\.(\w+)\s+:")


def pkg_provides(pm, want):
    """Find the distro package that has the plugin file in the wanted format.

    Returns (package, path) or None. Only VST2 (.so) and VST3 (bundle)
    are looked up: their file name is what the project stores.
    """
    fmt, key = want["format"], want["key"]
    if fmt == "vst2":
        fname = key + ".so"
    elif fmt == "vst3":
        fname = key
    else:
        return None
    sub = "/vst3/" if fmt == "vst3" else "/vst"
    if pm == "dnf":
        r = subprocess.run(["dnf", "-q", "provides", "*/" + _ci_glob(fname)],
                           capture_output=True, text=True)
        pkgs, paths = [], []
        for line in r.stdout.splitlines():
            m = _RPM_NEVRA.match(line)
            if m and m.group(2) in ("x86_64", "noarch", platform.machine()):
                pkgs.append(m.group(1))
            elif line.strip().startswith("Filename") and pkgs:
                path = line.split(":", 1)[1].strip()
                if sub in path:
                    return pkgs[-1], path
        return None
    if pm == "apt" and has("apt-file"):
        r = subprocess.run(["apt-file", "search", "-i", "-x",
                            "/" + re.escape(fname) + "(/|$)"],
                           capture_output=True, text=True)
        for line in r.stdout.splitlines():
            pkg, _, path = line.partition(": ")
            if sub in path:
                return pkg, path
    return None


def gh_release(repo, refresh=False):
    url = "https://api.github.com/repos/%s/releases/latest" % repo
    return json.loads(fetch_cached(url, "gh-" + repo.replace("/", "-")
                                   + ".json", refresh))


def gh_asset(rel, pattern):
    if not pattern:
        return None
    for a in rel.get("assets", []):
        if re.search(pattern, a["name"]):
            return a
    return None


def resolve(want, refresh=False):
    """Return a plan dict for a missing plugin, or None if unknown."""
    name = want["name"]
    vendor = want.get("vendor", "")
    if vendor.lower() == "u-he" or uhe_lookup(name, refresh):
        p = uhe_lookup(name, refresh)
        if p:
            urls = uhe_urls(p, refresh)
            return {"title": "u-he " + name, "how": "u-he",
                    "version": uhe_version(urls[0]), "url": urls[0],
                    "urls": urls}
        if vendor.lower() == "u-he":
            return {"title": name, "how": "page", "version": "",
                    "url": UHE_PAGE}
    pm = pkg_manager()
    if pm:
        hit = pkg_provides(pm, want)
        if hit:
            return {"title": hit[0], "how": pm, "version": "",
                    "package": hit[0], "path": hit[1]}
    for entry in CATALOG:
        if not (re.search(entry["match"], name, re.I)
                or (vendor and entry.get("vendor")
                    and re.search(entry["vendor"], vendor, re.I))):
            continue
        notes = []
        for m in entry["methods"]:
            t = m["type"]
            if t == "page":
                return {"title": entry["title"], "how": "page",
                        "version": "", "url": m["url"]}
            if t == "pkg":
                pkg = m.get(pm) if pm else None
                if pkg and pkg_available(pm, pkg):
                    return {"title": entry["title"], "how": pm,
                            "version": "", "package": pkg}
                if pkg:
                    notes.append("%s has no package %s" % (pm, pkg))
            if t == "github":
                try:
                    rel = gh_release(m["repo"], refresh)
                except Exception as exc:
                    notes.append("%s: %s" % (m["repo"], exc))
                    continue
                tag = rel.get("tag_name", "")
                for kind in ("rpm", "deb", "archive"):
                    if kind == "rpm" and pm != "dnf":
                        continue
                    if kind == "deb" and pm != "apt":
                        continue
                    a = gh_asset(rel, m.get(kind))
                    if a:
                        return {"title": entry["title"],
                                "how": kind if kind != "archive" else "copy",
                                "version": tag,
                                "url": a["browser_download_url"]}
                notes.append("%s %s: no Linux file" % (m["repo"], tag))
        return {"title": entry["title"], "how": "-", "version": "",
                "note": "; ".join(notes)}
    return None


# -------------------------------------------------------------- install --

def safe_extract(archive, dest):
    """Unpack a .tar.* / .zip / .deb / .7z into dest, refusing paths
    outside it."""
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    low = archive.lower()
    root = os.path.realpath(dest)
    if low.endswith(".7z"):
        # No 7z in the standard library: use 7z / 7za or bsdtar (both
        # refuse paths outside dest).
        for cmd in (["7z", "x", "-y", "-o" + dest, archive],
                    ["7za", "x", "-y", "-o" + dest, archive],
                    ["bsdtar", "-xf", archive, "-C", dest]):
            if has(cmd[0]):
                if subprocess.run(cmd, stdout=subprocess.DEVNULL).returncode:
                    raise ValueError("%s failed on %s" % (cmd[0], archive))
                return
        raise ValueError("need 7z (p7zip) or bsdtar (libarchive) to unpack "
                         + archive)

    def check(name):
        p = os.path.realpath(os.path.join(dest, name))
        if p != root and not p.startswith(root + os.sep):
            raise ValueError("unsafe path in archive: " + name)

    if low.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                check(n)
            z.extractall(dest)
            # zip keeps unix modes in external_attr; restore exec bits
            for info in z.infolist():
                mode = info.external_attr >> 16
                if mode & 0o111:
                    os.chmod(os.path.join(dest, info.filename), mode & 0o777)
        return
    if low.endswith(".deb"):
        data = deb_data(archive)
        tf = tarfile.open(fileobj=io.BytesIO(data[1]), mode="r:" + data[0])
    else:
        tf = tarfile.open(archive)
    with tf:
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, filter="data")
        else:
            for m in tf.getmembers():
                check(m.name)
            tf.extractall(dest)


def deb_data(path):
    """Return (tar mode, bytes) of data.tar.* inside a .deb (ar archive)."""
    with open(path, "rb") as fh:
        if fh.read(8) != b"!<arch>\n":
            raise ValueError("not a .deb file: " + path)
        while True:
            hdr = fh.read(60)
            if len(hdr) < 60:
                break
            name = hdr[:16].decode().strip().rstrip("/")
            size = int(hdr[48:58].decode().strip())
            body = fh.read(size)
            if size % 2:
                fh.read(1)
            if name.startswith("data.tar"):
                ext = name.rsplit(".", 1)[-1]
                mode = {"gz": "gz", "xz": "xz", "bz2": "bz2",
                        "tar": ""}.get(ext)
                if mode is None:
                    raise ValueError("unsupported %s in %s (try: sudo apt "
                                     "install ./%s)" % (name, path,
                                                        os.path.basename(path)))
                return mode, body
    raise ValueError("no data.tar in " + path)


def find_bundles(top):
    """Yield (path, kind) for plugin bundles; does not descend into them."""
    for root, dirs, files in os.walk(top):
        keep = []
        for d in sorted(dirs):
            ext = os.path.splitext(d)[1].lower()
            if ext in DEST:
                yield os.path.join(root, d), ext
            else:
                keep.append(d)
        dirs[:] = keep
        parts = root.lower().split(os.sep)
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext == ".clap":
                yield os.path.join(root, f), ".clap"
            elif ext == ".so" and any(
                    p in ("vst", "vst2", "lxvst", "linux_vst") for p in parts):
                yield os.path.join(root, f), ".vst"


def copy_bundles(top):
    n = 0
    for src, kind in find_bundles(top):
        dest_dir = os.path.expanduser(DEST[kind])
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(src))
        if os.path.isdir(dest) and not os.path.islink(dest):
            shutil.rmtree(dest)
        elif os.path.lexists(dest):
            os.remove(dest)
        if os.path.isdir(src):
            shutil.copytree(src, dest, symlinks=True)
        else:
            shutil.copy2(src, dest)
        print("  installed %s" % dest)
        n += 1
    if not n:
        print("  no .vst3 / .clap / .lv2 / vst .so found in the archive")
    return n > 0


def run(cmd, cwd=None):
    print("  $ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd).returncode == 0


def install(plan, yes):
    how = plan["how"]
    if how == "page":
        print("  download it from %s" % plan["url"])
        return False
    if how in ("dnf", "apt"):
        cmd = ["sudo", how, "install", plan["package"]]
        if not ask("  run: %s ?" % " ".join(cmd), yes):
            return False
        return run(cmd)
    if how in ("rpm", "deb"):
        f = download(plan["url"])
        pm = "dnf" if how == "rpm" else "apt"
        cmd = ["sudo", pm, "install", os.path.abspath(f)]
        if not ask("  run: %s ?" % " ".join(cmd), yes):
            return False
        return run(cmd)
    f = None
    for url in plan.get("urls") or [plan["url"]]:
        try:
            f = download(url)
            break
        except urllib.error.HTTPError as exc:
            print("  %s: %s" % (url, exc))
    if not f:
        return False
    work = cache_path(os.path.basename(f) + ".d")
    safe_extract(f, work)
    if how == "copy":
        return copy_bundles(work)
    if how == "u-he":
        scripts = []
        for root, dirs, files in os.walk(work):
            if "install.sh" in files:
                scripts.append(os.path.join(root, "install.sh"))
        if not scripts:
            print("  no install.sh in %s; copying bundles instead" % work)
            return copy_bundles(work)
        script = min(scripts, key=len)
        print("  running the u-he installer (it may ask questions)")
        return run(["bash", script], cwd=os.path.dirname(script))
    return False


# ----------------------------------------------------------------- find --

_PAREN = re.compile(r"\(([^()]*)\)")


def vendor_of(display):
    """'VST3i: TyrellN6 (u-he)' -> 'u-he' (skips '(2->6ch)' and the like)."""
    for g in reversed(_PAREN.findall(display)):
        if not re.match(r"^\d+(->\d+)?ch$|^mono$|^stereo$", g.strip(), re.I):
            return g.strip()
    return ""


def wanted(items, host):
    out, seen, installed = [], set(), 0
    for item in items:
        if os.path.exists(item):
            for proj in find_projects([item]):
                try:
                    ws = parse_project(proj)
                except Exception as exc:
                    print("cannot read %s: %s" % (proj, exc), file=sys.stderr)
                    continue
                for w in ws:
                    if w.get("unchecked") or w["format"] == "jsfx":
                        continue
                    k = (w["format"], w["key"])
                    if k in seen:
                        continue
                    seen.add(k)
                    if host.match(w) == "yes":
                        installed += 1
                        continue
                    w["vendor"] = vendor_of(w.get("display", ""))
                    w["have"] = sorted(host.any_names.get(
                        norm_name(w["name"]), ()))
                    out.append(w)
        else:
            n = norm_name(item)
            if n in host.any_names:
                installed += 1
                continue
            out.append({"format": "?", "key": item, "name": item,
                        "display": item, "vendor": ""})
    return out, installed


def cmd_find(args):
    host = live_host("live")
    missing, installed = wanted(args.items, host)
    if not missing:
        print("No missing plugins (%d installed)." % installed)
        return 0

    rows, plans = [], []
    for w in missing:
        plan = resolve(w, args.refresh)
        rows.append((w, plan))
        if plan and plan["how"] != "-" and not any(
                (p.get("url"), p.get("package"))
                == (plan.get("url"), plan.get("package")) for p in plans):
            plans.append(plan)

    wd = max(len(w["display"]) for w, _ in rows)
    print("%-6s  %-*s  %s" % ("format", wd, "plugin", "source"))
    print("-" * (wd + 50))
    for w, p in rows:
        if not p:
            src = "-  not in catalog"
        elif p["how"] == "-":
            src = "%s: no install method here (%s)" % (p["title"],
                                                         p.get("note", ""))
        elif p["how"] in ("dnf", "apt"):
            src = "sudo %s install %s" % (p["how"], p["package"])
            if p.get("path"):
                src += "  (has %s)" % p["path"]
        elif p["how"] == "page":
            src = "manual: %s" % p["url"]
        else:
            src = "%s %s [%s] %s" % (p["title"], p["version"], p["how"],
                                     p["url"])
        print("%-6s  %-*s  %s" % (w["format"], wd, w["display"], src))
        if w.get("have"):
            print("%-6s  %-*s  (installed here only as %s)"
                  % ("", wd, "", ", ".join(w["have"])))
    if installed:
        print("(%d plugin(s) from the projects are already installed)"
              % installed)

    if not args.install:
        if any(p["how"] != "page" for p in plans):
            print("Use --install to install them.")
        return 1

    for p in plans:
        print()
        print("== %s %s" % (p["title"], p["version"]))
        try:
            install(p, args.yes)
        except Exception as exc:
            print("  failed: %s" % exc)

    print()
    print("Scanning again...")
    host = live_host("live")
    still = [w for w in missing
             if (host.match(w) if w["format"] != "?"
                 else ("yes" if norm_name(w["name"])
                       in host.any_names else "-")) != "yes"]
    for w in missing:
        print("  %-3s %s" % ("-" if w in still else "ok", w["display"]))
    if still:
        print("%d plugin(s) still missing." % len(still))
    return 1 if still else 0


def cmd_list(args):
    print("u-he: every product with a Linux build on %s" % UHE_INDEX)
    for e in CATALOG:
        how = ", ".join(m.get("repo") or m.get("url") or
                        "dnf:%s apt:%s" % (m.get("dnf"), m.get("apt"))
                        for m in e["methods"])
        print("%-18s %s" % (e["title"], how))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="plugin-helper",
        description="Find and install missing VST2/VST3/CLAP/LV2 plugins.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("find", help="find install sources for missing "
                                     "plugins")
    sp.add_argument("items", nargs="+", metavar="ITEM",
                    help="project file, directory, or plugin name")
    sp.add_argument("--install", action="store_true",
                    help="download and install what was found")
    sp.add_argument("-y", "--yes", action="store_true",
                    help="do not ask before sudo package installs")
    sp.add_argument("--refresh", action="store_true",
                    help="reload u-he / GitHub release info (cache: 1 day)")
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser("list", help="show the built-in catalog")
    sp.set_defaults(func=cmd_list)

    args = ap.parse_args(argv)
    if platform.system() != "Linux":
        print("warning: written for Linux", file=sys.stderr)
    return args.func(args) or 0
