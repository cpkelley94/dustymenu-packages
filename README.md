# dustyMenu package hosting

Production host: https://dustymenu-packages.pages.dev/

The legacy schema-2 GBARunner3 catalog remains at `/v2/catalog.bin`. The current
client targets the signed schema-3 catalog at `/v3/catalog.bin`, which can carry
all supported emulator packages in one bounded manifest. The expanded catalog
has passed local publishing/install interoperability checks; CI reproduction
and public deployment are pending.

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

A local cross-repository check bundled the real GBARunner2, GameYob, nesDS,
SNEmulDS 0.6a, SNEmulDS 0.6d upstream release, and PicoDriveTWL binaries, published
an isolated signed schema-3 catalog with a temporary test key, and installed all
six through the shared client over localhost HTTP. All 16 installed file hashes,
receipts, and one-touch defaults matched. This did not deploy public assets or
qualify emulator execution/saves on hardware.

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
