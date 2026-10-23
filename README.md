# dustyMenu package hosting

Production host: https://dustymenu-packages.pages.dev/

The legacy schema-2 GBARunner3 catalog remains at `/v2/catalog.bin`. The current
client targets the signed schema-3 catalog at `/v3/catalog.bin`, which can carry
all supported emulator packages in one bounded manifest. All seven CI jobs passed
in [build run 39825858870](https://github.com/cpkelley94/dustymenu-packages/actions/runs/39825858870).
Catalog sequence 2 is live following
[publication run 40015396016](https://github.com/cpkelley94/dustymenu-packages/actions/runs/40015396016)
and is retained in release `catalog-v3-2`. The revision-3 GameYob correction below
is prepared locally and has not yet been published.

| Package | System | Entry point | Launch |
| --- | --- | --- | --- |
| GBARunner3 | GBA | `/GBARunner3.nds` | argv |
| GBARunner2 | GBA | `/emulators/gbarunner2.nds` | argv |
| GameYob | GB/GBC | `/emulators/gameyob.nds` | argv |
| nesDS | NES | `/emulators/nesds.nds` | argv |
| SNEmulDS 0.6a | SNES | `/emulators/snemulds-06a.nds` | argv |
| SNEmulDS 0.6d | SNES | `/emulators/snemulds-06d/ToolchainGenericDS-multiboot.nds` | manual |
| PicoDriveTWL | Genesis | `/emulators/picodrivetwl.nds` | argv |

jEnesisDS is intentionally local-only and is never published. Every package is a
qualification build: physical DS Lite launch, save, and redistribution checks are
still pending. No ROMs or proprietary BIOS files are hosted.

## Pinned builds

Specs live in `packages/v3/`. Each spec pins a full upstream commit and a Linux
container image by digest. `tools/emulators.py` validates the client descriptor,
extensions, destinations, file roles, size limits, and provenance; it rejects
floating pins, mismatched client metadata, symlinks, malformed NDS headers, and
incomplete glob inventories.

- GBARunner3 also pins its `libtwl` submodule and all 301 compatibility configs.
- GameYob and PicoDriveTWL build in a pinned BlocksDS image.
- GameYob revision 3 includes checked battery-save initialization as well as
  the earlier long-ROM-path/empty-browser patch.
  Package revisions add a `-rN` suffix to the installed version, so the device
  can offer an update while the upstream source commit remains pinned.
- GBARunner2, nesDS, and SNEmulDS 0.6a build in pinned devkitARM images.
- Checkout, input preparation, and Python packaging run on the Ubuntu host;
  only shell compilation runs inside the pinned images. Historical Debian
  Stretch images need no package installs or GitHub Actions runtime.
- SNEmulDS 0.6a stages two MPL-2.0 crt0 sources from `devkitarm-crtls` because
  its 2015 linker scripts predate the 2017 startup refactor; temporary
  Windows-path include aliases are removed before the source archive is made.
- SNEmulDS 0.6d uses the upstream TGDS 1.65 release files because TGDS requires a
  custom newlib rebuild that upstream does not provide as a pinned container. The
  spec records this as `upstream-release` provenance rather than claiming a CI
  source build.

## Build all packages

After these files are committed and pushed to `main`:

1. Open **Actions → Build pinned emulator packages → Run workflow**.
2. Run it on `main`. The build jobs receive no Cloudflare token or signing key.
3. Download each `emulator-<id>-<commit>` artifact from the successful run.

Each artifact contains a deterministic ZIP, `manifest.json`, `SHA256SUMS`, and a
deterministic `source.tar.gz` for corresponding-source distribution. The build
workflow does not publish or deploy anything.

For one package locally, with an `upstream/` checkout at the pinned commit:

```sh
python3 tools/build_package.py \
  --spec packages/v3/gameyob.json \
  --workspace work \
  --output dist/gameyob \
  --container
```

## Publish the signed catalog

Run **Actions → Publish signed emulator catalog** on `main`, selecting a successful
build run and a strictly increasing schema-3 sequence (initially 1). The workflow:

1. Downloads every `emulator-*` artifact and verifies each bundle against its spec.
2. Restores the most recent signed Pages snapshot so earlier v2/v3 assets survive.
3. Builds one authenticated manifest and one concatenated streaming payload per
   package under `/v3/releases/<id>/<commit>/`, plus corresponding source and
   notices.
4. Signs `/v3/catalog.bin` with the repository's Ed25519 key and deploys the complete
   Pages snapshot.
5. Retains `pages-snapshot.tar.gz` in a `catalog-v3-<sequence>` prerelease for the
   next publication.

`packages/publisher.json` pins the public key, also compiled into dustyMenu. Keep
the private key outside Git; the local copy is in ignored
`.private/catalog-signing.pem`, and publication uses the `CATALOG_SIGNING_KEY`
Actions secret.

## Deployment setup

Create a Cloudflare API token with **Account → Cloudflare Pages → Edit**, limited
to the account containing `dustymenu-packages`.

In this repository's **Settings → Secrets and variables → Actions**, add:

| Type | Name | Value |
| --- | --- | --- |
| Repository secret | `CATALOG_SIGNING_KEY` | Ed25519 private key in PEM form |
| Repository secret | `CLOUDFLARE_API_TOKEN` | The Cloudflare token |
| Repository variable | `CLOUDFLARE_ACCOUNT_ID` | Your Cloudflare account ID |
| Repository variable | `CLOUDFLARE_PAGES_PROJECT` | `dustymenu-packages` |

The bootstrap **Deploy static package site** workflow is for an empty site. It
refuses production deployment when either signed catalog is live, so it cannot
replace published package assets. Use a publish workflow for production updates.

## Local checks

Host tests require Python, OpenSSL, and a C++17 compiler (`g++`).

### GameYob battery-backed cartridge startup (revision 3)

The user clarified that no-save Kirby's Dream Land boots, while save-backed GB
and GBC titles fail. A short-named battery diagnostic reproduced an ARM9 data
abort in `fclose(NULL)`: the old save initializer closed a failed `fopen` before
creating a missing save. Revision 3 safely creates/loads saves, zero-extends
short files while preserving existing bytes/RTC data, checks storage failures,
and propagates initialization errors instead of running with invalid state.

An original battery test now boots in GB and GBC modes, persists a SRAM marker,
and reads it on a second boot through dustyMenu/Pico in melonDS. RTC and 4 MiB
banked battery cases also start. The host regression test compiles the exact
helper used by the package and covers new, short, full, oversized, and RTC saves,
plus open/read/write/sync failure injection.

Build and publish a fresh run to offer `c4d8672806b4-dev-r3` in Install Emulators.
Old GameYob revision-1/2 artifacts are rejected for the revision-3 spec. After
publication (next sequence 3), refresh the device catalog and update GameYob.
The corrected local bundle is generated under `dist/gameyob/`. Existing saves
should be retained for the update, not deleted as a troubleshooting step.

### Earlier long-path correction (revision 2)

The pinned GameYob source has 100-byte ROM, save-name, and basename buffers.
Passing a full path longer than those buffers can corrupt emulator state. The
same original GBC test ROM booted under a short name and black-screened with a
117-byte full path. Revision 2 expands path and sidecar buffers, validates input
length, handles failed ROM loads, and guards the empty file browser's A action.
Both GBC header modes (`0x80` and `0xC0`) and a regular GB test ROM ran through
dustyMenu/Pico with long filenames in the local runtime checks.

Revision 2 was published in catalog sequence 2. It fixes a separate real path
overflow, but did not cover the battery-save startup failure described above.

The larger buffers address the reproduced overflow; this remains a qualification
build. A separate 255-byte full-path stress case did not complete startup and
requires further investigation. Physical DS Lite testing and the user's affected
commercial titles remain unverified. GB/GBC remain one system because mode
selection follows the cartridge header, independently of this path defect.

A local cross-repository check bundled the real GBARunner2, GameYob, nesDS,
SNEmulDS 0.6a, SNEmulDS 0.6d upstream release, and PicoDriveTWL binaries, published
an isolated signed schema-3 catalog with a temporary test key, and installed all
six through the shared client over localhost HTTP. All 16 installed file hashes,
receipts, and one-touch defaults matched. This did not deploy public assets or
qualify emulator execution/saves on hardware.

The deployed catalog has also passed signature verification against the pinned
publisher key and a complete host-client HTTPS installation of all seven CI
packages. All 319 installed file hashes, receipts/statuses, and defaults matched;
all five legacy v2 assets remained byte-identical on the live service. Physical
DS Lite download/install and emulator launch/save qualification remain pending.

```sh
python3 -m unittest discover -s tests -v
python3 tools/emulators.py matrix --directory packages/v3
python3 tools/emulators.py settings --spec packages/v3/gameyob.json
python3 tools/packages.py check-site --site public
```

The legacy v2 tools (`tools/packages.py`, `tools/publish.py`) and their workflows
remain available so `/v2/catalog.bin` and its immutable assets stay byte-identical.
New package work should use `packages/v3/` and the schema-3 publisher.

On the device, open **Settings → Install Emulators**, choose a system, and press
**A** to install/update/repair. **Settings → Default Emulators** selects the system
default; **Y → Game Specific Options** overrides one game. Manual-launch emulators
require confirmation before handing over a ROM.
