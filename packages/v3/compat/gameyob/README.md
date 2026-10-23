# GameYob path handling (dustyMenu revision 2)

This MIT-licensed downstream patch applies to DS-Homebrew/GameYob commit
`c4d8672806b4a1cff8012fd40de4acf69b0094c2`.

The pinned upstream copies the complete argv ROM path into 100-byte global
filename, basename, and save-name buffers. Cheat and state filename buffers have
similar limits. A long filename/path can overwrite adjacent emulator state and
black-screen even though the same ROM boots under a shorter name. This was
reproduced with an original GBC-only test ROM through dustyMenu and Pico Loader.

The patch expands ROM and sidecar buffers to 512 bytes, rejects paths without
room for derived suffixes, handles failed argv loads before initializing the
emulator, and guards the file chooser's empty-list A action. The printer path
uses bounded formatting. This covers Pico's 255-byte ROM argument plus sidecar
suffixes; the ROM's existing directory/base name and save naming stay intact.

The build copies this notice and the patch into `upstream/.dusty-build` before
applying it, so both the modified source and exact patch ship in `source.tar.gz`.
