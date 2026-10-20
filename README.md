# dustyMenu package hosting

Production host: https://dustymenu-packages.pages.dev/

The static site is live. The first emulator build recipe is **GBARunner3**, pinned
to commit `ecaa817815d9761745606592f04affe5ee9c3731`, its libtwl submodule, and the
Linux/amd64 digest of upstream's `devkitpro/devkitarm:20241104` build image.
This is a qualification build, not a declaration of DS Lite/Pico compatibility
or a stable package release.

## First run: build the emulator

After these files are committed and pushed to `main`:

1. Open **Actions → Build GBARunner3 qualification bundle → Run workflow**.
2. Run it on `main`. No Cloudflare token or signing key is needed for this build.
3. Download the `gbarunner3-<commit>` artifact from the completed run.
4. Extract the artifact, check `SHA256SUMS`, and inspect `manifest.json`.
5. The inner `GBARunner3-<commit>.zip` has the upstream SD layout:

   ```text
   GBARunner3.nds
   _gba/configs/*.json
   ```

All **301** compatibility configuration files are required by this pinned build's
inventory. The tool rejects incomplete bundles, mismatched source/submodule pins,
symlinks, malformed configuration, and structurally truncated NDS files. It
records per-file SHA-512 hashes and emits deterministic ZIP metadata. This does
not prove the upstream compiler produces reproducible or hardware-compatible code.

Use the bundle to qualify startup, Pico handoff, selected-ROM loading, settings,
saves, and required files on the target DS Lite/ACE3DS setup. Record the exact
results and confirm the distribution terms and required notices/sources before
mirroring the build publicly. Test files contain no game ROMs or proprietary BIOS.
The build job has no deployment/signing secrets and does not publish to Pages.

## Pages deployment setup

Create a Cloudflare API token with **Account → Cloudflare Pages → Edit**, limited
to the account containing `dustymenu-packages`.

In this repository's **Settings → Secrets and variables → Actions**, add:

| Type | Name | Value |
| --- | --- | --- |
| Repository secret | `CLOUDFLARE_API_TOKEN` | The Cloudflare token |
| Repository variable | `CLOUDFLARE_ACCOUNT_ID` | Your Cloudflare account ID |
| Repository variable | `CLOUDFLARE_PAGES_PROJECT` | `dustymenu-packages` |

Then run **Actions → Deploy static package site** from `main`, initially with
target **preview**. Wrangler publishes the complete `public/` snapshot to branch
`testing`. Check the deployment URL printed by Wrangler and its `/health.json`.
Choose **production** to deploy to the Pages production branch `main` after that
check. This workflow deploys only the static site; it does not copy build artifacts
into the public directory or publish emulator binaries automatically.

The project was initially connected to Git. Git-connected Pages projects accept
Wrangler deployments too. Once the manual workflow is proven, disable automatic
Git-triggered deployments in the Pages project's build/branch settings before
using generated release snapshots, so a Git push cannot replace a release with
the bootstrap site. Leave automatic Git deployment enabled until the workflow is
working. No paid services or Functions are needed.

`npm ci --ignore-scripts` installs the lockfile-pinned Wrangler tool; its CLI and
platform binaries are provided by npm packages. `public/_headers` retains the
catalog/payload caching rules. Build artifacts remain in GitHub Actions for a
short retention period rather than growing the site's Git history.

## Local checks

```sh
python3 -m unittest discover -s tests -v
python3 tools/packages.py settings --spec packages/gbarunner3.json
python3 tools/packages.py check-site --site public
```

To assemble an already built input tree:

```sh
python3 tools/packages.py bundle \
  --spec packages/gbarunner3.json \
  --input work/gbarunner3 \
  --output dist/gbarunner3
```

The input must have `code/bootstrap/GBARunner3.nds`, `configs/`, and the matching
`source-commit.txt`/`libtwl-commit.txt` provenance files. The workflow produces this
input directly from the pinned source checkout using upstream's `make -C code`.

## Next release milestones

- Run the pinned compiler workflow, qualify its complete output on hardware, and
  resolve the precise launch/BIOS/save and redistribution requirements.
- Add similarly pinned GameYob, SNEmulDS, and Genesis build/package recipes.
- Implement the authenticated schema-2 catalog and package manifests together
  with dustyMenu's multi-file installer. `manifest.json` here is a **build
  inventory**, not a signed installer catalog. A real 302-file GBARunner3 inventory
  exceeds the current 32 KiB catalog limit: keep the signed catalog compact and
  authenticate a separate bounded per-package manifest by size/hash. The ZIP is
  for manual testing; on-device ZIP extraction is not currently implemented.
- Add trusted release signing and immutable published payloads, then enable the
  stable channel after qualification. Keep the private signing key outside
  `public/` and the repository. No signing secret is consumed by these workflows.
- Complete DNS/verified HTTPS support in dustyNetwork before using the public
  `pages.dev` host on-device. The currently released client is numeric-IPv4 HTTP
  only.

The app-side plan uses GBARunner3 by default and a scrollable Settings list with
separate Wi-Fi and Install Emulators entries. Those on-device changes are separate
from these server build/deployment workflows.
