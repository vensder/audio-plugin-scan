# plugscan

Inventory of installed Linux audio plugins, compare hosts, and check Reaper /
LMMS projects for missing plugins. One file, Python 3 standard library only.

## 1. Scan each host

    ./plugscan.py scan                 # writes scan-results/<hostname>.json
    ./plugscan.py scan -o laptop.json  # or any other path

scan-results/ sits next to the script, so in a git checkout you can scan,
then commit and push the new host file:

    ./plugscan.py scan && git add scan-results && git commit -m "scan: $(hostname)"
    ./plugscan.py scan --extra-path vst3:/mnt/data/plugins

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

    ./plugscan.py compare                          # every host in scan-results/
    ./plugscan.py compare fedora-shift ubuntu      # host names or JSON paths
    ./plugscan.py compare --all                    # every plugin, not only differences
    ./plugscan.py compare -f lv2                   # only LV2
    ./plugscan.py compare -f vst,clap              # vst = vst2 + vst3
    ./plugscan.py compare -x jsfx,ladspa           # everything except these

-f/--only and -x/--exclude also work with check.

## 3. Check projects

    ./plugscan.py check Song.RPP                       # against this machine, scanned now
    ./plugscan.py check ~/Projects/Reaper --missing    # every .RPP/.mmp/.mmpz under a dir
    ./plugscan.py check Song.RPP --host ubuntu --host slackbox   # saved hosts
    ./plugscan.py check Song.RPP -a                # every host in scan-results/

Exit code is 1 when anything is missing, so it can be used in scripts.
"Backups" folders are skipped when a directory is given.

Cells: yes = installed, name = only a plugin with the same name (different
file or URI), alt = same name but only in another format, - = missing.

## 4. Missing Reaper JSFX: ReaPack helper

reapack-helper.py (needs plugscan.py next to it) installs ReaPack and finds
which ReaPack repository provides each missing JSFX in a project.

    ./reapack-helper.py install-reapack            # ReaPack .so into ~/.config/REAPER/UserPlugins
    ./reapack-helper.py find Song.RPP              # which repo/package has each missing JSFX
    ./reapack-helper.py find Song.RPP --add        # add those repos to reapack.ini (REAPER closed)
    ./reapack-helper.py find Song.RPP --download   # or fetch the files into Effects right away
    ./reapack-helper.py find "Saike Tools/Basics/Saike_Pitch_Shift.jsfx"
    ./reapack-helper.py repos                      # repositories in reapack.ini

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

plugin-helper.py (needs plugscan.py next to it) checks projects against this
machine and finds an install source for each missing plugin, the latest
version where possible.

    ./plugin-helper.py find Song.RPP               # what is missing and where to get it
    ./plugin-helper.py find Song.RPP --install     # download and install it
    ./plugin-helper.py find ~/Projects/Reaper --install
    ./plugin-helper.py find TyrellN6 Diva --install   # by plugin name
    ./plugin-helper.py list                        # the built-in catalog

Sources, in the order they are tried for a plugin:
- u-he (any product, e.g. TyrellN6, Diva, Hive): the Linux build linked on
  u-he.com/products, unpacked; then u-he's own install.sh runs (it installs
  to ~/.u-he, ~/.vst3/u-he, ... and may ask questions). No sudo.
- GitHub releases (Surge XT, Dexed, Cardinal, OB-Xd, Dragonfly, ...): the
  latest release. An .rpm (with dnf) or .deb (with apt) is installed with
  sudo after asking; a .tar/.zip/.deb archive is unpacked and its .vst3,
  .clap, .lv2 and VST2 .so files are copied to ~/.vst3, ~/.clap, ~/.lv2,
  ~/.vst.
- Distro packages (LSP, x42, Calf, ZynAddSubFX, ...): dnf or apt, with sudo,
  only if the package exists in your repositories, and after asking.
- Plugins that need a login (Vital, TAL, ...): the download page is printed.

After --install the machine is scanned again and each plugin is shown as ok
or -. -y skips the sudo questions. Downloads and release info are cached in
~/.cache/plugin-helper (release info for a day, --refresh to reload). Set
GITHUB_TOKEN if you hit the GitHub API rate limit. To add a plugin, add an
entry to CATALOG at the top of the script. JSFX are left to reapack-helper.py.

## How plugins are matched

- LV2: by plugin URI (what Reaper stores in .RPP).
- VST2 / VST3 / LADSPA / DSSI: by file name (e.g. Dexed.vst3, reaeq.vst.so),
  case-insensitive, ".so" ignored. Falls back to the plugin name.
- CLAP: by plugin name (Reaper stores the CLAP id, which a file scan cannot see).
- JSFX: by path relative to the Effects folder.
- LMMS: VeSTige / VST effect file, LADSPA library file, LV2 URI. Built-in
  LMMS instruments and effects are listed but not checked. Plugins inside a
  Carla rack are not checked.

## Not covered yet

Flatpak plugin extensions, Windows plugins under Wine/yabridge, plugin
versions.
