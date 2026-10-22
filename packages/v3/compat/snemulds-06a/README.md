# SNEmulDS 0.6a build compatibility

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
corresponding-source archive is created. No upstream source file is modified.

The host-side build driver extracts the four expected linker files from the
pinned upstream `linker_files.zip` into `.dusty-build/linker-files` before
compilation. Python, GitHub Actions, and archive packaging run on the host;
the Debian Stretch toolchain container needs no added packages.
