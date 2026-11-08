#!/usr/bin/env python3
"""reaper-update - update REAPER on Linux to the latest release.

Usage:
    reaper-update.py [--check] [-n] [-d DIR] [-y] [--force] [--arch ARCH]

Finds the installed REAPER (the folder with the reaper binary, e.g.
/opt/REAPER or ~/opt/REAPER), reads its version from whatsnew.txt, and
looks up the latest Linux release on reaper.fm/download.php. When a newer
one exists, the tarball for this CPU is downloaded and REAPER's own
install-reaper.sh installs it over the existing folder. sudo is used only
when that folder is not writable by you. Desktop integration and the
/usr/local/bin symlink made by the first install are left as they are.

--check     only print the installed and the latest version; exit code 1
            when an update is available, 0 when up to date.
-n          dry run: download and change nothing, print what would be done.
-d DIR      the REAPER folder, if it is not found automatically.
-y          do not ask before installing.
--force     install even if the version is the same (repair).

Your settings in ~/.config/REAPER are not touched. Only the Python 3
standard library is used.
"""

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

DOWNLOAD_PAGE = "https://www.reaper.fm/download.php"
FILES_BASE = "https://www.reaper.fm/"
UA = "reaper-update/1.0"
CANDIDATES = ["~/opt/REAPER", "/opt/REAPER", "/usr/local/REAPER",
              "/usr/lib/REAPER", "/usr/lib64/REAPER"]
ARCHES = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64",
          "arm64": "aarch64", "armv7l": "armv7l", "i686": "i686",
          "i386": "i686"}


# -------------------------------------------------------------- version --

def version_code(v):
    """'7.28' -> 728, '7.1' -> 710, '7.0' -> 700 (REAPER file numbering)."""
    m = re.match(r"v?(\d+)\.(\d+)", v.strip())
    if not m:
        return None
    return int(m.group(1)) * 100 + int(m.group(2).ljust(2, "0")[:2])


def code_version(code):
    """728 -> '7.28', 700 -> '7.0', 710 -> '7.10'."""
    major, minor = divmod(code, 100)
    return "%d.%s" % (major, "0" if minor == 0 else "%02d" % minor)


def installed_version(rdir):
    """First 'vX.YY' in whatsnew.txt of the install folder."""
    path = os.path.join(rdir, "whatsnew.txt")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r"\s*v?(\d+\.\d+)", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def changes_since(rdir, old):
    """Lines at the top of whatsnew.txt, down to the 'vOLD' entry."""
    out = []
    oldc = version_code(old) if old else None
    try:
        with open(os.path.join(rdir, "whatsnew.txt"),
                  encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r"v(\d+\.\d+)", line)
                if m and out and (oldc is None
                                  or version_code(m.group(1)) <= oldc):
                    break
                out.append(line.rstrip())
    except OSError:
        pass
    while out and not out[-1]:
        out.pop()
    return out


# ------------------------------------------------------------- location --

def find_install(explicit=None):
    """Return the REAPER folder (the one holding the reaper binary)."""
    if explicit:
        d = os.path.abspath(os.path.expanduser(explicit))
        return d if os.path.isfile(os.path.join(d, "reaper")) else None
    exe = shutil.which("reaper")
    if exe:
        d = os.path.dirname(os.path.realpath(exe))
        if os.path.isfile(os.path.join(d, "whatsnew.txt")):
            return d
    for c in CANDIDATES:
        d = os.path.expanduser(c)
        if os.path.isfile(os.path.join(d, "reaper")):
            return d
    return None


def reaper_running():
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open("/proc/%s/comm" % pid) as fh:
                    if fh.read().strip() == "reaper":
                        return True
            except OSError:
                pass
    return False


# ------------------------------------------------------------- download --

def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_release(arch, page=None):
    """Return (version, url) of the newest Linux tarball for arch."""
    if page is None:
        page = fetch(DOWNLOAD_PAGE).decode("utf-8", "replace")
    pat = (r"""["']([^"']*reaper(\d{3,4})_linux_%s\.tar\.xz)["']"""
           % re.escape(arch))
    best = None
    for href, num in re.findall(pat, page):
        code = int(num)
        if best is None or code > best[0]:
            best = (code, href)
    if best is None:
        return None, None
    href = best[1]
    if not re.match(r"https?://", href):
        href = FILES_BASE + href.lstrip("/")
    return code_version(best[0]), href


def download(url, dest):
    print("Downloading %s" % url)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, \
            open(dest, "wb") as fh:
        shutil.copyfileobj(r, fh)


def unpack(tarball, dest):
    """Extract tarball into dest, return the folder with install-reaper.sh."""
    with tarfile.open(tarball) as tf:
        for m in tf.getmembers():
            p = os.path.normpath(m.name)
            if p.startswith("..") or os.path.isabs(p):
                raise SystemExit("error: unsafe path in tarball: %s" % m.name)
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, filter="tar")
        else:
            tf.extractall(dest)
    for root, _dirs, files in os.walk(dest):
        if "install-reaper.sh" in files:
            return root
    return None


# -------------------------------------------------------------- install --

def install_cmd(src, rdir):
    """install-reaper.sh --install PARENT puts REAPER in PARENT/REAPER."""
    parent = os.path.dirname(rdir.rstrip("/"))
    cmd = ["sh", os.path.join(src, "install-reaper.sh"), "--install", parent]
    try:
        with open(os.path.join(src, "install-reaper.sh"),
                  encoding="utf-8", errors="replace") as fh:
            if "--quiet" in fh.read():
                cmd.append("--quiet")
    except OSError:
        pass
    if not os.access(rdir, os.W_OK):
        cmd = ["sudo"] + cmd
    return cmd


def ask(question):
    try:
        return input(question + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Update REAPER on Linux to the latest release.")
    ap.add_argument("--check", action="store_true",
                    help="only report; exit 1 if an update is available")
    ap.add_argument("-n", "--dry-run", action="store_true",
                    help="print what would be done, change nothing")
    ap.add_argument("-d", "--dir", metavar="DIR",
                    help="REAPER install folder (default: auto-detect)")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="install without asking")
    ap.add_argument("--force", action="store_true",
                    help="install even if already up to date")
    ap.add_argument("--arch", help="CPU arch (default: %s)"
                    % platform.machine())
    args = ap.parse_args(argv)

    arch = ARCHES.get(args.arch or platform.machine())
    if not arch:
        sys.exit("error: unknown arch %s (use --arch x86_64, aarch64, "
                 "armv7l or i686)" % (args.arch or platform.machine()))

    rdir = find_install(args.dir)
    if not rdir:
        sys.exit("error: REAPER not found%s; use -d DIR"
                 % (" in %s" % args.dir if args.dir else ""))
    cur = installed_version(rdir)
    print("Installed: %s in %s" % (cur or "unknown version", rdir))

    try:
        new, url = latest_release(arch)
    except OSError as e:
        sys.exit("error: cannot read %s: %s" % (DOWNLOAD_PAGE, e))
    if not new:
        sys.exit("error: no Linux %s tarball found on %s"
                 % (arch, DOWNLOAD_PAGE))
    print("Latest:    %s (%s)" % (new, url))

    newer = cur is None or version_code(new) > version_code(cur)
    if not newer and not args.force:
        print("REAPER is up to date.")
        return 0
    if args.check:
        print("Update available.")
        return 1

    cmd = install_cmd("<unpacked>", rdir)
    if args.dry_run:
        print("Would download %s" % url)
        print("Would run: %s" % " ".join(cmd))
        return 0

    if reaper_running():
        sys.exit("error: REAPER is running; close it first")
    if not args.yes and not ask("Install REAPER %s into %s?" % (new, rdir)):
        print("Cancelled.")
        return 0

    with tempfile.TemporaryDirectory(prefix="reaper-update-") as tmp:
        tarball = os.path.join(tmp, os.path.basename(url))
        try:
            download(url, tarball)
        except OSError as e:
            sys.exit("error: download failed: %s" % e)
        src = unpack(tarball, os.path.join(tmp, "x"))
        if not src:
            sys.exit("error: install-reaper.sh not found in tarball")
        cmd = install_cmd(src, rdir)
        print("Running: %s" % " ".join(cmd))
        rc = subprocess.call(cmd, cwd=src)
        if rc != 0:
            sys.exit("error: install-reaper.sh failed (exit %d)" % rc)

    after = installed_version(rdir)
    print("Now installed: %s in %s" % (after or "unknown version", rdir))
    lines = changes_since(rdir, cur)
    if lines:
        print("\nWhat is new since %s:\n" % (cur or "the previous version"))
        print("\n".join(lines))
    return 0 if after == new else 1


if __name__ == "__main__":
    sys.exit(main())
