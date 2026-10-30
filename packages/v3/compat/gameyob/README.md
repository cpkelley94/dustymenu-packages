# GameYob downstream fixes (dustyMenu revision 5)

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

## Revision 4: scaling transitions and options console

`display-restore.patch` restores VRAM C, text mode, BG0, and blending state before
reloading the console after bitmap scaling. Its map uses block 22, separate from
the font at tile base 0 and consistent with the menu's highlight operations.
The old block-2 map overlapped the font allocation. Highlight code now uses the
actual console map pointer.

Deferred callbacks are serviced once per DS frame in the foreground, after IRQ
notification. The VBlank IRQ no longer copies/allocates a vector or invokes
callbacks that can initialize stdio, print menus, or load border files. Chained
screen/backlight stages remain separated by frame boundaries, including tasks
queued after the current frame's IRQ. Leaving scaling drains a full frame before
reassigning VRAM C so an in-flight ARM7 capture/DMA can finish. Stale transition
stages check the current mode, and the menu redraw follows console restoration.
The actual helper is in `framequeue.h`, with portable ordering/reentrancy tests;
`consolelayout.h` is checked for font/map overlap.

Menu setup now initializes defaults, parses configuration/palettes/controls,
then applies the resulting callbacks, preserving saved display choices without
using palette data before it exists. Parsed selections are bounded. The config
reader handles EOF explicitly; saving creates `/_nds` if needed and checks
flush/sync/close results. A missing border filename falls back to `/border.bmp`.

The options menu is opened with R or touch. A blank/off lower screen during
normal play with Console Output off is intentional; it should show the menu
when requested. Native 1x/Aspect/Full transitions were checked locally. The user
subsequently reported the revision-4 build works
well apart from Suspend's ROM-browser failure, addressed below.

## Revision 5: Suspend/Exit ROM browser

Suspend deliberately saves a `.yss` state and opens the ROM browser; it is not
lid sleep. argv autoload bypassed browser state initialization, leaving the old
`/lameboy` default. When that directory was absent, its unchecked `chdir` left
the browser in the emulator's directory, often showing only `..` and no games.
The old parent-navigation code removed the final path component, then assumed
another slash remained. A top-level directory such as `fat:/emulators` therefore
passed address 1 to `std::string`, an invalid-pointer data-abort path. Nested
directories also selected the wrong parent entry.

`browser-resume.patch` records the argv ROM's directory and filename without
changing cwd or save paths during play. Suspend/Exit can then show and preselect
that ROM. `browserpath.h` handles parent selection for device-prefixed paths,
top-level folders, roots, and relative argv directories. Directory navigation
checks open/chdir before replacing the live handle; a missing configured folder
falls back to root. Extensionless files no longer create a null-plus-one pointer,
and unknown directory types are resolved with `stat`. Empty lists show a message
and retain the existing guarded A action.

The actual path helpers have portable regression tests. The clean package ran
through dustyMenu/Pico in melonDS: Suspend opened the correct folder, A resumed
the saved state (matching the pre-suspend image rather than a fresh boot), and
the consumed `.yss` was removed. A double-speed GBC/MBC3 RTC case navigated up to
root, pressed B at root, and returned to resume with an extensionless file
present. SRAM/RTC sizes and markers remained correct. Scaling and R/touch options
also passed after resume. Physical DS Lite retesting remains pending.

The build copies this notice, all patches, and the helpers into
`upstream/.dusty-build` before applying them, so modified source and exact build
inputs ship in `source.tar.gz`.
