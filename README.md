# audio-plugin-scan

Inventory of installed Linux audio plugins, compare hosts, and check Reaper /
LMMS projects for missing plugins. Python 3 standard library only, nothing
to install.

## Layout

    bin/              the commands (run them from the checkout)
      plugscan          scan / compare / check            (section 1-3)
      reapack-helper    missing JSFX via ReaPack          (section 4)
      plugin-helper     missing VST / CLAP / LV2          (section 5)
      plugin-summary    Markdown summary per host         (section 6)
      reaper-update     update REAPER                     (section 7)
      rpp-info          tracks and FX chains of a project (section 8)
    audioplug/        shared code (Python package)
      common.py         paths, downloads with a cache, prompts
      formats.py        formats, search folders, -f / -x filters
      lv2.py            LV2 bundle (Turtle) reader
      scanner.py        scan this machine
      hosts.py          host files and plugin matching
      reaper.py         REAPER install and reaper.ini plugin paths
      rpp.py            .RPP reader: block tree, plugins, tracks, FX chains
      carla.py          plugins inside Carla racks
      lmms.py           .mmp / .mmpz reader
      projects.py       find and read projects
      cli/              one module per command in bin/
    tests/            python3 -m unittest discover -s tests
    scan-results/     host files (<hostname>.json) and summaries (.md)

To run the commands from anywhere, link them into a folder on your PATH
(the links keep working, the scripts find audioplug/ through them):

    ln -s "$PWD"/bin/* ~/.local/bin/

Moved from the old flat layout: `./plugscan.py` is now `bin/plugscan`,
`./plugin-helper.py` is `bin/plugin-helper`, and so on (same names
without `.py`). Arguments and output are unchanged.

## 1. Scan each host

    bin/plugscan scan                 # writes scan-results/<hostname>.json
    bin/plugscan scan -o laptop.json  # or any other path

scan-results/ is in the checkout, so you can scan,
then commit and push the new host file:

    bin/plugscan scan && git add scan-results && git commit -m "scan: $(hostname)"
    bin/plugscan scan --extra-path vst3:/mnt/data/plugins

Formats: VST2, VST3, LV2, CLAP, LADSPA, DSSI, Reaper JSFX.

Searched locations:
- env vars: VST_PATH, LXVST_PATH, VST3_PATH, LV2_PATH, CLAP_PATH, LADSPA_PATH, DSSI_PATH
- home: ~/.vst ~/.lxvst ~/.vst3 ~/.lv2 ~/.clap ~/.ladspa ~/.dssi
- system: /usr/lib, /usr/lib64, /usr/local/lib, /usr/local/lib64, /opt/lib*,
  /usr/lib/<arch>-linux-gnu (Debian/Ubuntu), each with vst, lxvst, vst3, lv2, clap, ladspa, dssi
- Reaper stock plugins: ~/opt/REAPER/Plugins, /opt/REAPER/Plugins
- Reaper JSFX: ~/.config/REAPER/Effects, <reaper>/InstallData/Effects
- LMMS bundled LADSPA: <libdir>/lmms/ladspa

Symlinked duplicates (e.g. lib -> lib64) are counted once.

## 2. Compare hosts

    bin/plugscan compare                          # every host in scan-results/
    bin/plugscan compare fedora-shift ubuntu      # host names or JSON paths
    bin/plugscan compare --all                    # every plugin, not only differences
    bin/plugscan compare -f lv2                   # only LV2
    bin/plugscan compare -f vst,clap              # vst = vst2 + vst3
    bin/plugscan compare -x jsfx,ladspa           # everything except these

-f/--only and -x/--exclude also work with check.

## 3. Check projects

    bin/plugscan check Song.RPP                       # against this machine, scanned now
    bin/plugscan check ~/Projects/Reaper --missing    # every .RPP/.mmp/.mmpz under a dir
    bin/plugscan check Song.RPP --host ubuntu --host slackbox   # saved hosts
    bin/plugscan check Song.RPP -a                # every host in scan-results/

Exit code is 1 when anything is missing, so it can be used in scripts.
"Backups" folders are skipped when a directory is given.

REAPER only loads plugins from its own path lists (Preferences > Plug-ins,
stored in `~/.config/REAPER/reaper.ini`). scan records those lists and marks
every VST2/VST3/CLAP/LV2 plugin REAPER can reach (symlinks count); check on
an .RPP shows "path" for a plugin that is installed but outside them, e.g. a
Fedora VST2 in `/usr/lib64/vst`, and says which folder to add. If `reaper.ini`
has no VST path yet, REAPER's default list is assumed (`~/.vst`, `~/.vst3`,
`/usr/lib/vst`, `/usr/lib/vst3`, `/usr/local/lib/vst`, `/usr/local/lib/vst3`),
and for CLAP `/usr/local/lib/clap`, `/usr/lib/clap`, `~/.clap `and
`%CLAP_PATH%` (REAPER 7 key: `clap_path_linux-x86_64`; VST key: `vstpath`).
Set `REAPER_INI` for a portable install. Host files scanned before this have
no REAPER info and are not checked for it.

Cells: yes = installed, name = only a plugin with the same name (different
file or URI), alt = same name but only in another format, - = missing,
path = installed but outside REAPER's plugin paths.

## 4. Missing Reaper JSFX: ReaPack helper

reapack-helper installs ReaPack and finds
which ReaPack repository provides each missing JSFX in a project.

    bin/reapack-helper install-reapack            # ReaPack .so into ~/.config/REAPER/UserPlugins
    bin/reapack-helper find Song.RPP              # which repo/package has each missing JSFX
    bin/reapack-helper find Song.RPP --add        # add those repos to reapack.ini (REAPER closed)
    bin/reapack-helper find Song.RPP --download   # or fetch the files into Effects right away
    bin/reapack-helper find "Saike Tools/Basics/Saike_Pitch_Shift.jsfx"
    bin/reapack-helper repos                      # repositories in reapack.ini

ReaPack installs an effect to Effects/<repository name>/<category>/<file>, and
the .RPP stores that path, so "Saike Tools/..." points to the "Saike Tools"
repository. The script reads the repository list from reapack.com, plus the
remotes already in reapack.ini and any --repo URL, and caches the indexes in
~/.cache/reapack-helper for a day (--refresh to reload). Use -r DIR for a
non-default REAPER resource folder (e.g. a portable install).

After --add: start REAPER, Extensions > ReaPack > Synchronize packages, then
Browse packages and install the listed packages, so ReaPack keeps them
updated. --download needs no ReaPack, but the files are not tracked by it.

## 5. Missing VST / VST3 / CLAP / LV2: plugin helper

plugin-helper checks projects against this
machine and finds an install source for each missing plugin, the latest
version where possible.

    bin/plugin-helper find Song.RPP               # what is missing and where to get it
    bin/plugin-helper find Song.RPP --install     # download and install it
    bin/plugin-helper find ~/Projects/Reaper --install
    bin/plugin-helper find TyrellN6 Diva --install   # by plugin name
    bin/plugin-helper list                        # the built-in catalog

Sources, in the order they are tried for a plugin:
- u-he (any product, e.g. TyrellN6, Diva, Hive): the Linux build linked on
  u-he.com/products, unpacked; then u-he's own install.sh runs (it installs
  to ~/.u-he, ~/.vst3/u-he, ... and may ask questions). No sudo.
- Distro package with the exact file (VST2 .so or VST3 bundle the project
  names): looked up with `dnf provides` or `apt-file search`, so e.g. a
  VST2 Carla-Rack on Fedora gives "sudo dnf install Carla-vst". Plugins
  installed only in another format are marked "(installed here only as lv2)".
- GitHub releases (Surge XT, Dexed, Cardinal, OB-Xd, Dragonfly, ...): the
  latest release. An .rpm (with dnf) or .deb (with apt) is installed with
  sudo after asking; a .tar/.zip/.deb archive is unpacked and its .vst3,
  .clap, .lv2 and VST2 .so files are copied to ~/.vst3, ~/.clap, ~/.lv2,
  ~/.vst.
- Distro packages (LSP, x42, Calf, ZynAddSubFX, ...): dnf or apt, with sudo,
  only if the package exists in your repositories, and after asking.
- Plugins that need a login or a form (Vital, TAL, Speedrum Lite,
  MT-PowerDrumKit, ...): the download page is printed.

LSP plugins are found by name ("LSP ...") or by the vendor in the project
("(LSP VST)"). Without dnf / apt, the LSP GitHub release (one .7z with
every format) is used; unpacking it needs `7z` (p7zip) or `bsdtar`
(libarchive).

After --install the machine is scanned again and each plugin is shown as ok
or -. -y skips the sudo questions. Downloads and release info are cached in
~/.cache/plugin-helper (release info for a day, --refresh to reload). Set
GITHUB_TOKEN if you hit the GitHub API rate limit. To add a plugin, add an
entry to CATALOG in audioplug/cli/plugin_helper.py. JSFX are left to
reapack-helper.

## 6. Readable summary per host

plugin-summary turns the host files into one Markdown file per host,
with each plugin listed once with the formats it is installed in:

    bin/plugin-summary                            # scan-results/<host>.md for every host file
    bin/plugin-summary scan-results/ubuntu.json   # just one host
    bin/plugin-summary scan-results/ubuntu.json -o -   # print instead
    bin/plugin-summary -o ~/plugin-notes          # write somewhere else

Sections: System plugins, Home plugins (~/.vst, ~/.lv2, ...), Carla,
REAPER (its plugin paths, plugins installed outside them, bundled FX such
as ReaComp / ReaEQ, other bundled components, JSFX by folder) and LMMS
(bundled LADSPA), as far as they are in the scan. Each heading shows how
many plugins it lists ("System plugins (236)"), counting a plugin once
whatever formats it has, so the numbers can be tracked between scans.
Example lines:

    - Surge XT: clap, lv2, vst3
    - calf: ladspa, lv2 (52 plugins)
    - reacomp: vst2

An LV2 bundle is one line, with the number of plugins inside. Names are
matched ignoring case and punctuation, a "lib" prefix and a "_vst"
suffix, so libTAL-NoiseMaker.so and TAL-NoiseMaker.vst3 share a line;
SWH LADSPA files (alias_1407.so) share a line with their LV2 port
(alias-swh.lv2).

## 7. Update REAPER

reaper-update checks reaper.fm for a newer REAPER and installs it over
the one you have, in the same folder:

    bin/reaper-update --check      # installed vs latest; exit 1 if an update exists
    bin/reaper-update -n           # dry run: what would be downloaded and run
    bin/reaper-update              # download and install (asks first)
    bin/reaper-update -y           # same, without asking
    bin/reaper-update -d ~/opt/REAPER   # if the folder is not found

The install folder is the one the `reaper` command points to, else
~/opt/REAPER or /opt/REAPER; the installed version is read from its
whatsnew.txt. The latest version and tarball (x86_64, aarch64, armv7l or
i686, from `uname -m` or --arch) come from reaper.fm/download.php. The
tarball is unpacked in a temp folder and its own install-reaper.sh runs with
`--install <parent of the folder>`, through sudo only when the folder is not
writable by you (e.g. /opt/REAPER). REAPER must be closed. Settings in
~/.config/REAPER, desktop entries and the /usr/local/bin symlink are left as
they are. --force reinstalls the same version. After installing, the new
entries of whatsnew.txt (everything newer than the old version) are printed.

## 8. REAPER project: tracks and FX chains

rpp-info lists every track of an .RPP with its FX in chain order and the
state of each FX (plugscan check stays the place for the per-plugin
summary across hosts):

    bin/rpp-info Song.RPP
    bin/rpp-info Song.RPP -c                   # also mark plugins missing here
    bin/rpp-info Song.RPP --host ubuntu        # ... or on saved hosts (-a: all)
    bin/rpp-info ~/Music/REAPER/Production     # every .RPP under a dir

Example:

    == Song.RPP
    Master: masterLimiter (v)
    1 Drums
    2   Kick: ReaEQ (v) -> "Kick comp" ReaComp (-)
    3   Snare top [muted, FX off]: gfxanalyzer (x)
          take "snare.wav": SaikeMultiSpectralAnalyzer (v)
    4 Synth: Surge XT (v) -> Bus FX [Dragonfly Hall Reverb (v, missing) -> SpectrumAnalyzer (-)] (v)
        input FX: ReaTune (v)
    5 Pads: Carla-Rack [Yoshimi (path)] (v) -> Calf Reverb (v)

- (v) active, (-) bypassed, (x) offline.
- Tracks inside a folder are indented. [muted] and [FX off] (the track's
  FX button) follow the name.
- A renamed FX shows its name in quotes, then the plugin.
- A container lists its FX in [ ], a Carla rack the plugins inside it.
- Input FX (record FX), take FX and the master chain have their own lines.
- With -c / --host / -a: "missing", "name", "alt" or "path" after the
  state, as in plugscan check (with several hosts: "ubuntu: missing").
  Exit code 1 when anything is missing.

## How plugins are matched

- LV2: by plugin URI (what Reaper stores in .RPP).
- VST2 / VST3 / LADSPA / DSSI: by file name (e.g. Dexed.vst3, reaeq.vst.so),
  case-insensitive, ".so" ignored. Falls back to the plugin name.
- VST2 / VST3 inside a shell library (one file with many plugins, e.g.
  LSP 1.2's lsp-plugins.so): scan reads REAPER's plugin cache
  (reaper-vstplugins64.ini) and records the plugin ids in each file, so a
  project that names an old per-plugin file (multisampler-x12.so) still
  matches by the id it stores, as in REAPER. Id and name must both match.
  Needs a new scan on each host.
- CLAP: by plugin name (Reaper stores the CLAP id, which a file scan cannot see).
- JSFX: by path relative to the Effects folder.
- LMMS: VeSTige / VST effect file, LADSPA library file, LV2 URI. Built-in
  LMMS instruments and effects are listed but not checked.
- Carla in Reaper and LMMS: the plugins inside a Carla-Rack / Carla-Patchbay (VST2
  or LV2) are read from the Carla state saved in the .RPP (base64) or the
  .mmpz (plain XML) and listed as "Carla-Rack > LV2: Yoshimi" or
  "Carla Rack > LV2: Surge XT". A plugin used many times is listed once. Carla's internal plugins and SF2/SFZ files
  are skipped. Carla also saves its own search paths (LV2_PATH, VST2_PATH,
  ...) in that state and uses them when the project loads; a plugin found
  only outside them is shown as "path" (e.g. Yoshimi in /usr/lib64/lv2 on
  Fedora when the project was made on Ubuntu).

## Not covered yet

Flatpak plugin extensions, Windows plugins under Wine/yabridge, plugin
versions.
