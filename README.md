# pezzotto.ai launcher catalog

The catalog of open-source applications installed by the
[pezzotto.ai launcher](https://github.com/pezzottoai/launcher), including the open-source
knock-offs of closed-source apps curated at [pezzotto.ai](https://pezzotto.ai). Each application is one JSON file in
`apps/`; topics live in `topics.json`. CI validates every file and publishes the merged
`index.json` together with its minisign signature, which is what the launcher downloads:

```
https://raw.githubusercontent.com/pezzottoai/launcher-catalog/main/index.json
https://raw.githubusercontent.com/pezzottoai/launcher-catalog/main/index.json.minisig
```

## Inclusion rules

- The application is free/open source: an OSI- or FSF-approved license (SPDX id in `license`)
  and a public source repository (`source_code`).
- It installs from an official source: Flathub, winget-pkgs, Homebrew, or the project's own
  releases. No repackaged binaries.
- It runs on at least one of Linux, Windows, macOS.

## Manifest format (schema_version 1)

Full definition: [`schema/app.schema.json`](schema/app.schema.json) (JSON Schema 2020-12).

```json
{
  "$schema": "../schema/app.schema.json",
  "schema_version": 1,
  "id": "org.keepassxc.KeePassXC",
  "name": "KeePassXC",
  "summary": "Cross-platform password manager",
  "description": "Optional longer text. Blank lines separate paragraphs.",
  "developer": "KeePassXC team",
  "license": "GPL-3.0-or-later",
  "homepage": "https://keepassxc.org",
  "source_code": "https://github.com/keepassxreboot/keepassxc",
  "icon": "https://example.org/icon.png",
  "topics": ["security"],
  "tags": ["passwords", "kdbx"],
  "installers": [
    { "platform": "linux", "arch": ["x86_64"], "kind": "download", "format": "appimage",
      "github": { "repo": "keepassxreboot/keepassxc", "asset": "^KeePassXC-[0-9.]+-x86_64\\.AppImage$" } },
    { "platform": "linux",   "kind": "flatpak",  "ref": "org.keepassxc.KeePassXC" },
    { "platform": "windows", "kind": "winget",   "package": "KeePassXCTeam.KeePassXC" },
    { "platform": "macos",   "kind": "homebrew", "package": "keepassxc", "cask": true }
  ]
}
```

- `id`: reverse-DNS. Reuse the AppStream/Flathub id when there is one. The file is `apps/<id>.json`.
- `topics`: ids from `topics.json`; the first is the primary topic.
- `installers`: in order of preference. The launcher uses the first entry matching the user's
  platform and architecture whose tool (flatpak, winget, brew) is present.

### Installer kinds

| kind | fields | notes |
|---|---|---|
| `flatpak` | `ref`, `remote` (default `flathub`) | Linux only, installed per-user |
| `winget` | `package` | Windows only |
| `homebrew` | `package`, `cask` (default `true`) | macOS (and Linux for formulae) |
| `download` | `format`, `url` + `sha256` (pinned file) and/or `github` {`repo`, `asset` regex} | handled by the launcher itself; `scripts/pin.py` fills `url`, `sha256`, `version` |

`download` formats: `appimage` and `binary` (single executable), `archive` (`.zip`/`.tar.gz`,
needs `exec` = path of the executable inside; `strip_root` drops a single top-level folder,
default `true`), `installer` (`.msi`/`.exe`/`.dmg`/`.pkg`/`.deb`, opened with the OS).

Any installer may set `run`: the argv used by the Launch button. `{dir}` expands to the install
directory of a `download` installer.

### Pinned releases and `certified`

A `download` installer with only `github` makes the launcher fetch whatever the latest release
is at install time: trust rests on the upstream GitHub account alone. `scripts/pin.py` resolves
each such installer to one exact release file and records `url`, `sha256` and `version` next to
the `github` block, which stays as the pointer to newer releases. Once every download of an app
is pinned, the script adds

```json
"certified": { "level": "pinned", "date": "2026-10-30" }
```

and CI refuses a certified app that loses a pin. The launcher shows the pin in the app details,
and in strict mode (`--strict` or `PEZZOTTO_LAUNCHER_STRICT=1`) it installs only pinned
downloads. The weekly CI run reports pins that fell behind upstream; refresh them with
`scripts/pin.py` (one app: `scripts/pin.py <id>`) and open a pull request.

## Signed index

CI signs `index.json` with the catalog key and publishes `index.json.minisig` beside it. The
launcher embeds the public key and refuses an index whose signature is missing or does not
verify, so a mirror, a proxy or a hijacked DNS entry cannot feed it a different catalog. The
signature is standard [minisign](https://jedisct1.github.io/minisign/):

```sh
minisign -Vm index.json -p keys/pezzotto-launcher-catalog.pub
# or, with no tools beyond Python:
python scripts/sign_index.py verify --pub keys/pezzotto-launcher-catalog.pub index.json
```

Public key: [`keys/pezzotto-launcher-catalog.pub`](keys/pezzotto-launcher-catalog.pub). The
private key is an Ed25519 key in PEM form (`openssl genpkey -algorithm ed25519`), stored only in
the `CATALOG_SIGNING_KEY` repository secret. To rotate it: generate a new key, run
`scripts/sign_index.py pubkey --key new.pem > keys/pezzotto-launcher-catalog.pub`, update the
secret, and ship a launcher release with the new `CATALOG_PUBLIC_KEY`.

## Adding an application

1. Copy an existing file in `apps/` to `apps/<id>.json` and edit it.
2. Pin its downloads, then check it:
   ```sh
   pip install jsonschema
   python scripts/pin.py <id>
   python scripts/build_index.py --check-remote --enrich
   ```
3. Open a pull request. Don't commit `index.json` or `index.json.minisig`; CI rebuilds and signs them.
