# GameYob downstream startup fixes (dustyMenu revision 3)

These MIT-licensed downstream patches apply to DS-Homebrew/GameYob commit
`c4d8672806b4a1cff8012fd40de4acf69b0094c2`.

## Revision 2: long paths and empty file chooser

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

## Revision 3: battery-save initialization

`loadSave()` calls `fclose(saveFile)` after a failed `fopen()` when a new `.sav`
does not yet exist. Picolibc dereferences this null stream and aborts, before
GameYob can create the save. ROMs without cartridge RAM bypass this path, which
explains the working no-save GB case alongside failures in save-backed GB/GBC
games. An original short-named battery test reproduced the abort in `fclose`.

`battery-init.patch` uses `batteryfile.h` to create or load the stream safely,
zero-fill only missing bytes, preserve existing data and extra trailers, handle
RTC data, and check open/seek/read/write/sync results. Allocation and save-load
errors propagate to the existing checked ROM-load path. RAM-size code 5 is
handled as 64 KiB. Host tests compile this exact helper and inject I/O failures;
melonDS tests verify GB/GBC battery startup, second-boot SRAM persistence, an RTC
cartridge, and a 4 MiB banked battery cartridge.

The build copies this notice, both patches, and the helper into
`upstream/.dusty-build` before applying them, so modified source and exact build
inputs ship in `source.tar.gz`.
