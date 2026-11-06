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

## 3. Check projects

    ./plugscan.py check Song.RPP                       # against this machine, scanned now
    ./plugscan.py check ~/Projects/Reaper --missing    # every .RPP/.mmp/.mmpz under a dir
    ./plugscan.py check Song.RPP --host ubuntu --host slackbox   # saved hosts
    ./plugscan.py check Song.RPP -a                # every host in scan-results/

Exit code is 1 when anything is missing, so it can be used in scripts.
"Backups" folders are skipped when a directory is given.

Cells: yes = installed, name = only a plugin with the same name (different
file or URI), alt = same name but only in another format, - = missing.

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
