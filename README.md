# FOSS Launcher catalog

The catalog of open-source applications installed by
[FOSS Launcher](https://github.com/sirmmo/fosslauncher). Each application is one JSON file in
`apps/`; topics live in `topics.json`. CI validates every file and publishes the merged
`index.json`, which is what the launcher downloads:

```
https://raw.githubusercontent.com/sirmmo/fosslauncher-catalog/main/index.json
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
| `download` | `format`, and either `url` + `sha256` or `github` {`repo`, `asset` regex} | handled by the launcher itself |

`download` formats: `appimage` and `binary` (single executable), `archive` (`.zip`/`.tar.gz`,
needs `exec` = path of the executable inside; `strip_root` drops a single top-level folder,
default `true`), `installer` (`.msi`/`.exe`/`.dmg`/`.pkg`/`.deb`, opened with the OS).

Any installer may set `run`: the argv used by the Launch button. `{dir}` expands to the install
directory of a `download` installer.

## Adding an application

1. Copy an existing file in `apps/` to `apps/<id>.json` and edit it.
2. Check it locally:
   ```sh
   pip install jsonschema
   python scripts/build_index.py --check-remote --enrich
   ```
3. Open a pull request. Don't commit `index.json`; CI rebuilds it.
