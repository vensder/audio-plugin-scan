"""reapack-helper - install ReaPack / SWS and find missing Reaper JSFX.

Usage:
    reapack-helper install-reapack [-r DIR] [--force]
    reapack-helper install-sws [-r DIR] [--force]
    reapack-helper find  ITEM [...] [-r DIR] [--repo URL ...] [--refresh]
                         [--add] [--download]
    reapack-helper repos [-r DIR]

ITEM is a .RPP project, a directory with projects, or a JSFX path as Reaper
stores it, e.g. "Saike Tools/Basics/Saike_Pitch_Shift.jsfx".

ReaPack installs an effect to Effects/<repository name>/<category>/<file>,
and Reaper stores that same path in the .RPP. So the first part of a missing
JSFX path names the ReaPack repository it came from. This script downloads
the repository indexes listed on reapack.com (plus the ones already in your
reapack.ini and any --repo URL), and looks the path up in them.

--add      adds the repositories found to reapack.ini (REAPER must be closed);
           then install the packages in Extensions > ReaPack > Browse packages.
--download fetches the package files straight into the Effects folder, at
           the path the project expects. Works without ReaPack.
"""

import argparse
import configparser
import json
import os
import platform
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from .. import common, reaper, rpp
from ..common import fetch, write_atomic
from ..formats import HOME_DIRS
from ..projects import find_projects, is_rpp

REPO_LIST = ("https://raw.githubusercontent.com/cfillion/reapack.com/"
             "master/config/repos.yml")


def fetch_cached(url, refresh=False):
    return common.fetch_cached(url, common.cache_dir("reapack-helper"),
                               refresh=refresh)


# --------------------------------------------------------------- reaper --

def effects_dirs(res):
    out = [os.path.join(res, "Effects")]
    for d in HOME_DIRS["jsfx"]:
        d = os.path.expanduser(d)
        if d not in out:
            out.append(d)
    return out


def jsfx_installed(path, res):
    return any(os.path.isfile(os.path.join(d, path))
               for d in effects_dirs(res))


def load_ini(res):
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    ini.optionxform = str
    ini.read(os.path.join(res, "reapack.ini"), encoding="utf-8")
    return ini


def ini_remotes(ini):
    """Return [(name, url, enabled, autoinstall)] from reapack.ini."""
    out = []
    if ini.has_section("remotes"):
        n = ini.getint("remotes", "size", fallback=0)
        for i in range(n):
            v = ini.get("remotes", "remote%d" % i, fallback="")
            parts = v.split("|")
            if len(parts) >= 2 and parts[0]:
                parts += ["1", "2"][len(parts) - 2:]
                out.append(tuple(parts[:4]))
    return out


# ------------------------------------------------------- install-reapack --

def _arch():
    arch = platform.machine().lower()
    return {"amd64": "x86_64", "arm64": "aarch64", "armv7": "armv7l"}.get(
        arch, arch)


def install_extension(res, title, repo, files, force, hint):
    """Download REAPER extension files from the latest GitHub release.

    files: [(asset name, folder in the resource dir)]; the first one is
    the extension library (must be an ELF file), checked for --force.
    """
    api = "https://api.github.com/repos/%s/releases/latest" % repo
    urls = {f: "https://github.com/%s/releases/latest/download/%s" % (repo, f)
            for f, _ in files}
    tag = "latest"
    try:
        rel = json.loads(fetch(api))
        tag = rel.get("tag_name", tag)
        assets = {a["name"]: a["browser_download_url"]
                  for a in rel.get("assets", [])}
        if files[0][0] not in assets:
            sys.exit("no %s build for %s in release %s"
                     % (title, _arch(), tag))
        urls.update((f, assets[f]) for f, _ in files if f in assets)
    except SystemExit:
        raise
    except Exception as exc:
        print("cannot read release info (%s), using %s"
              % (exc, urls[files[0][0]]))

    main = os.path.join(res, files[0][1], files[0][0])
    if os.path.exists(main) and not force:
        print("%s already exists (use --force to replace it with %s)"
              % (main, tag))
        return 0
    print("downloading %s %s for %s" % (title, tag, _arch()))
    for i, (fname, folder) in enumerate(files):
        data = fetch(urls[fname], timeout=120)
        if i == 0 and not data.startswith(b"\x7fELF"):
            sys.exit("download is not a Linux library: " + urls[fname])
        dest = os.path.join(res, folder, fname)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        write_atomic(dest, data)
        print("installed %s" % dest)
    if reaper.running():
        print("REAPER is running: restart it to load %s." % title)
    else:
        print("Start REAPER; %s" % hint)
    return 0


def cmd_install_reapack(args):
    return install_extension(
        args.resource_dir, "ReaPack", "cfillion/reapack",
        [("reaper_reapack-%s.so" % _arch(), "UserPlugins")], args.force,
        "ReaPack appears under Extensions > ReaPack.")


def cmd_install_sws(args):
    py = "sws_python64.py" if "64" in _arch() else "sws_python32.py"
    return install_extension(
        args.resource_dir, "SWS", "reaper-oss/sws",
        [("reaper_sws-%s.so" % _arch(), "UserPlugins"), (py, "Scripts")],
        args.force, "SWS actions are under Extensions and in the Actions "
        "list (SWS: ..., S&M: ...).")


# ---------------------------------------------------------------- index --

def version_key(v):
    return [int(x) for x in re.findall(r"\d+", v)]


def is_prerelease(v):
    return bool(re.search(r"[a-z]", v.lower()))


def platform_ok(src):
    p = src.get("platform", "all")
    return p == "all" or p.startswith("linux")


def parse_index(data, url):
    """Return (index name, {lower jsfx path: package dict})."""
    root = ET.fromstring(data)
    name = root.get("name") or ""
    files = {}
    for cat in root.iter("category"):
        cname = cat.get("name", "")
        for pkg in cat.findall("reapack"):
            if pkg.get("type") != "effect":
                continue
            vers = pkg.findall("version")
            if not vers:
                continue
            stable = [v for v in vers if not is_prerelease(v.get("name", ""))]
            ver = max(stable or vers,
                      key=lambda v: version_key(v.get("name", "")))
            sources = []
            for s in ver.findall("source"):
                if not (s.text and platform_ok(s)):
                    continue
                stype = s.get("type", "effect")
                f = s.get("file") or pkg.get("name")
                if stype == "effect":
                    target = os.path.normpath(os.path.join(cname, f))
                    if target.startswith(".."):
                        continue
                    target = os.path.join("Effects", name, target)
                elif stype == "data":
                    target = os.path.join("Data", f)
                else:
                    continue
                sources.append((target, s.text.strip()))
            entry = {"repo": name, "url": url, "package": pkg.get("name"),
                     "category": cname, "version": ver.get("name"),
                     "desc": pkg.get("desc") or "", "sources": sources}
            for target, _ in sources:
                if target.startswith("Effects" + os.sep) \
                        and target.lower().endswith(".jsfx"):
                    rel = target[len("Effects" + os.sep):]
                    files[rel.lower()] = entry
    return name, files


def repo_urls(res, extra, refresh):
    urls = list(extra or [])
    for r in ini_remotes(load_ini(res)):
        urls.append(r[1])
    try:
        text = fetch_cached(REPO_LIST, refresh).decode("utf-8", "replace")
        urls += re.findall(r"^\s*index:\s*'?([^'\s]+)'?", text, re.M)
    except Exception as exc:
        print("warning: cannot read repository list %s: %s"
              % (REPO_LIST, exc), file=sys.stderr)
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def load_indexes(urls, refresh):
    def one(url):
        try:
            return parse_index(fetch_cached(url, refresh), url)
        except Exception as exc:
            return exc

    print("reading %d ReaPack repositories..." % len(urls), file=sys.stderr)
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(one, urls))
    indexes, failed = [], 0
    for url, r in zip(urls, results):
        if isinstance(r, Exception):
            failed += 1
            if os.environ.get("REAPACK_HELPER_DEBUG"):
                print("  failed %s: %s" % (url, r), file=sys.stderr)
        else:
            indexes.append(r)
    if failed:
        print("(%d repositories could not be read)" % failed,
              file=sys.stderr)
    return indexes


def lookup(path, indexes):
    """Return (entry, how) for a JSFX path; how is 'exact' or 'name'."""
    low = path.replace("\\", "/").lower()
    for _, files in indexes:
        if low in files:
            return files[low], "exact"
    base = low.rsplit("/", 1)[-1]
    for _, files in indexes:
        for k, e in files.items():
            if k.rsplit("/", 1)[-1] == base:
                return e, "name"
    return None, "-"


# ----------------------------------------------------------------- find --

def wanted_jsfx(items, res):
    """Return (missing paths, number already installed)."""
    out, installed = [], 0
    for item in items:
        if os.path.isdir(item) or os.path.isfile(item):
            for proj in find_projects([item]):
                if not is_rpp(proj):
                    continue
                for w in rpp.plugins(proj):
                    if w["format"] != "jsfx":
                        continue
                    if jsfx_installed(w["name"], res):
                        installed += 1
                    elif w["name"] not in out:
                        out.append(w["name"])
        else:
            p = item[4:] if item.startswith("JS: ") else item
            if p not in out:
                out.append(p)
    return out, installed


def add_remotes(res, entries):
    ini_path = os.path.join(res, "reapack.ini")
    if reaper.running():
        sys.exit("REAPER is running and would overwrite reapack.ini on exit. "
                 "Close it and run again with --add.")
    ini = load_ini(res)
    remotes = ini_remotes(ini)
    names = {r[0] for r in remotes}
    added = []
    for e in entries:
        if e["repo"] not in names:
            names.add(e["repo"])
            remotes.append((e["repo"], e["url"], "1", "2"))
            added.append(e["repo"])
    if not added:
        print("reapack.ini: all repositories are already there")
        return
    if not ini.has_section("remotes"):
        ini.add_section("remotes")
    for i, r in enumerate(remotes):
        ini.set("remotes", "remote%d" % i, "|".join(r))
    ini.set("remotes", "size", str(len(remotes)))
    os.makedirs(res, exist_ok=True)
    if os.path.exists(ini_path):
        with open(ini_path, "rb") as src, open(ini_path + ".bak", "wb") as dst:
            dst.write(src.read())
    with open(ini_path, "w", encoding="utf-8") as fh:
        ini.write(fh, space_around_delimiters=False)
    print("reapack.ini: added %s" % ", ".join(added))
    print("Next: start REAPER, Extensions > ReaPack > Synchronize packages,")
    print("then Extensions > ReaPack > Browse packages and install:")
    for e in entries:
        if e["repo"] in added:
            print("  %s: %s" % (e["repo"], e["package"]))


def download(res, entry):
    for target, url in entry["sources"]:
        dest = os.path.join(res, target)
        data = fetch(url)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        write_atomic(dest, data)
        print("  wrote %s" % dest)


def cmd_find(args):
    res = args.resource_dir
    paths, installed = wanted_jsfx(args.items, res)
    if not paths:
        print("No missing JSFX (%d installed)." % installed)
        return 0

    indexes = load_indexes(repo_urls(res, args.repo, args.refresh),
                           args.refresh)
    rows, found = [], []
    for p in paths:
        e, how = lookup(p, indexes)
        rows.append((p, e, how))
        if e and e not in found:
            found.append(e)

    w = max(len(p) for p, _, _ in rows)
    print("%-*s  %s" % (w, "jsfx", "repository / package"))
    print("-" * (w + 40))
    for p, e, how in rows:
        if not e:
            print("%-*s  -  not found" % (w, p))
            continue
        note = "" if how == "exact" else "  (same file name only)"
        print("%-*s  %s / %s %s%s" % (w, p, e["repo"], e["package"],
                                      e["version"], note))
    repos = {}
    for e in found:
        repos.setdefault(e["repo"], e["url"])
    if repos:
        print()
        print("Repositories:")
    for name, url in repos.items():
        print("  %-30s %s" % (name, url))
    if installed:
        print("(%d JSFX from the project are already installed)" % installed)

    if args.download:
        for e in found:
            print("downloading %s / %s" % (e["repo"], e["package"]))
            download(res, e)
    if args.add:
        add_remotes(res, found)
    if not (args.add or args.download) and found:
        print("Use --add to add these repositories to ReaPack, or --download "
              "to fetch the files now.")
    return 1 if any(e is None for _, e, _ in rows) else 0


def cmd_repos(args):
    remotes = ini_remotes(load_ini(args.resource_dir))
    if not remotes:
        print("no repositories in %s"
              % os.path.join(args.resource_dir, "reapack.ini"))
    for name, url, enabled, _ in remotes:
        print("%-3s %-30s %s" % ("on" if enabled == "1" else "off", name, url))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="reapack-helper",
        description="Install ReaPack and find missing Reaper JSFX.")
    ap.add_argument("-r", "--resource-dir", default=reaper.RESOURCE_DIR,
                    help="REAPER resource folder (default: %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("install-reapack",
                        help="download ReaPack into UserPlugins")
    sp.add_argument("--force", action="store_true",
                    help="replace an existing ReaPack library")
    sp.set_defaults(func=cmd_install_reapack)

    sp = sub.add_parser("install-sws",
                        help="download the SWS extension into UserPlugins")
    sp.add_argument("--force", action="store_true",
                    help="replace an existing SWS library (update)")
    sp.set_defaults(func=cmd_install_sws)

    sp = sub.add_parser("find", help="find the ReaPack repository and "
                                     "package for missing JSFX")
    sp.add_argument("items", nargs="+", metavar="ITEM",
                    help=".RPP file, directory, or JSFX path")
    sp.add_argument("--repo", action="append", metavar="URL",
                    help="extra repository index.xml URL (can be repeated)")
    sp.add_argument("--refresh", action="store_true",
                    help="download indexes again (cache: 1 day)")
    sp.add_argument("--add", action="store_true",
                    help="add the repositories found to reapack.ini")
    sp.add_argument("--download", action="store_true",
                    help="download the package files into Effects now")
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser("repos", help="list repositories in reapack.ini")
    sp.set_defaults(func=cmd_repos)

    args = ap.parse_args(argv)
    args.resource_dir = os.path.expanduser(args.resource_dir)
    return args.func(args) or 0
