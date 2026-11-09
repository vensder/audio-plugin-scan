"""Paths, downloads with a cache, and small helpers used by several tools."""

import hashlib
import os
import re
import shutil
import time
import urllib.request

HOME = os.path.expanduser("~")

# The repository root (the folder holding audioplug/ and bin/).
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# Host files live in the checkout, so git collects them.
RESULTS_DIR = os.path.join(ROOT, "scan-results")

CACHE_AGE = 24 * 3600
USER_AGENT = "audio-plugin-scan/1.0"


def cache_dir(tool):
    """~/.cache/<tool> (or under $XDG_CACHE_HOME), created if needed."""
    d = os.path.join(os.environ.get("XDG_CACHE_HOME")
                     or os.path.join(HOME, ".cache"), tool)
    os.makedirs(d, exist_ok=True)
    return d


def raw_url(url):
    """github.com/U/R/raw/BRANCH/x -> raw.githubusercontent.com/U/R/BRANCH/x"""
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/raw/(.+)$", url)
    if m:
        return "https://raw.githubusercontent.com/%s/%s/%s" % m.groups()
    return url


def fetch(url, timeout=60, accept=None):
    """Return the body of url. GITHUB_TOKEN is sent to api.github.com."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    if "api.github.com" in url and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(raw_url(url), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def write_atomic(path, data):
    with open(path + ".tmp", "wb") as fh:
        fh.write(data)
    os.replace(path + ".tmp", path)


def cache_file(directory, name):
    return os.path.join(directory, re.sub(r"[^A-Za-z0-9._-]", "_", name))


def fetch_cached(url, directory, name=None, refresh=False):
    """Small documents (index pages, API answers), kept for CACHE_AGE.

    A stale copy is used when the download fails.
    """
    path = cache_file(directory,
                      name or hashlib.sha1(url.encode()).hexdigest())
    fresh = (os.path.exists(path)
             and time.time() - os.path.getmtime(path) < CACHE_AGE)
    if not fresh or refresh:
        try:
            write_atomic(path, fetch(url))
        except Exception:
            if not os.path.exists(path):
                raise
    with open(path, "rb") as fh:
        return fh.read()


def ask(question, yes=False):
    """y/N question; yes=True answers it without asking."""
    if yes:
        return True
    try:
        return input(question + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def has(cmd):
    return shutil.which(cmd) is not None


def read_text(path):
    """File contents as text, "" when it cannot be read."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""
