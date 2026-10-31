# SNEmulDS 0.6a compatibility and runtime fixes (revision 2)

SNEmulDS 0.6a ships ARM7/ARM9 linker scripts from 2015 that expect the
pre-2017 devkitARM startup objects. The pinned `devkitpro/devkitarm:20180522`
image no longer provides those symbols.

These two startup files are copied from
[`devkitPro/devkitarm-crtls`](https://github.com/devkitPro/devkitarm-crtls)
at commit `892bd9fd308b85522f37dd2f97ad6a221945ed86` (the parent of the
ARM7/ARM9 crt0 refactor `8df10cb`). Upstream explicitly recorded MPL-2.0 licensing
in commit `eac1e8c74f4fc4791c69322d3b93ba51b2eb21a7`; the same notice has been
prepended to these historical files. Their assembly content is unchanged.
The build compiles them with the pinned image and
installs them into the temporary container toolchain.

The recipe also creates case/path aliases for the historical Windows-style
include names in the upstream source, then removes all aliases before the
corresponding-source archive is created. Revision 2 additionally applies the
GPL-2.0 downstream patch described below; startup assembly remains unchanged.

The host-side build driver extracts the four expected linker files from the
pinned upstream `linker_files.zip` into `.dusty-build/linker-files` before
compilation. Python, GitHub Actions, and archive packaging run on the host;
the Debian Stretch toolchain container needs no added packages.

## Direct launch and large-ROM paging

`startup-paging.patch` applies to the pinned upstream commit
`a92689abeb1ded315c7111557867bfbc3b418388`:

- Frontend/argv autoload bypasses `GUI_getROM`, but startup unconditionally called
  `GUI_deleteROMSelector`. That dereferenced a nonexistent selector. Only delete
  an existing screen and clear its pointer afterward. An original small LoROM
  diagnostic reproduced the old ARM9 abort in `GUI_deleteSelector` through Pico.
- Large-ROM paging added a hard-coded `0x400000` to the page buffer for both
  cached mappings and the returned address. `SNES_ROM_ADDRESS` already uses
  `memUncached`; with the pinned SDK, the addition can leave main RAM entirely.
  Use the SDK's idempotent alias conversion instead. An original 4 MiB HiROM
  diagnostic reproduced an abort when jumping outside the static first bank;
  the corrected mapping executes the paged code successfully.

The lower-left percentage comes from the emulated-frame/DS-frame ratio in
`engine.c`. It reports emulation speed, not file-load progress, and values above
100% do not by themselves diagnose a loader failure. The user's changing ~332%
with Chrono Trigger USA's blank screen prompted the large-HiROM checks.

Qualification uses original SNES diagnostics through dustyMenu and Pico, with
small LoROM, 4 MiB HiROM code paging, cache eviction/data reads, optional copier
headers, and SPC700 readiness/upload/execution. Existing `snemul.cfg` and SRAM
files are preserved on package upgrade. The actual Chrono Trigger ROM and its
DS Lite execution still require the user's retest; passing diagnostics does not
establish compatibility of that title.

The recipe copies this notice and the exact patch into `upstream/.dusty-build`
before applying it, so the corresponding-source archive includes the changes
and their inputs.
