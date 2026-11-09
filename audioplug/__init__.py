"""audioplug - shared code for the Linux audio plugin tools in bin/.

Modules:
    common    paths, downloads with a cache, small helpers
    formats   plugin formats, their search folders, -f / -x filters
    lv2       LV2 bundle reader (a tiny Turtle parser)
    scanner   scan this machine for installed plugins
    hosts     host files (scan results) and plugin matching
    reaper    REAPER install, reaper.ini plugin paths
    rpp       REAPER .RPP project reader (tree, plugins, tracks)
    carla     plugins saved inside a Carla rack / patchbay
    lmms      LMMS .mmp / .mmpz project reader
    projects  find and read projects of any supported type
    cli/      one module per command, run through the bin/ wrappers

Only the Python 3 standard library is used.
"""
