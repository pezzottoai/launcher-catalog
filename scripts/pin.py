#!/usr/bin/env python3
"""Pin download installers to one specific release.

For every `download` installer that has a `github` block, look up the latest release and
write `url`, `sha256` and `version` for the matching asset. The launcher then installs that
exact file and checks its hash against the (signed) catalog; `github` stays in the manifest
as the pointer to where newer releases come from. An app whose downloads are all pinned gets

  "certified": { "level": "pinned", "date": "YYYY-MM-DD" }

Usage:
  scripts/pin.py                 # pin every app (writes apps/*.json)
  scripts/pin.py <id> [<id>...]  # pin only these apps
  scripts/pin.py --check         # list apps whose pins are behind the latest release; exit 1 if any

The hash comes from the digest GitHub publishes for each release asset; assets without one
are downloaded and hashed. Set GITHUB_TOKEN to avoid API rate limits.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALLER_ORDER = ["platform", "arch", "kind", "format", "url", "sha256", "version", "github", "exec", "strip_root", "run"]
APP_ORDER = ["$schema", "schema_version", "id", "name", "summary", "description", "developer", "license",
             "homepage", "source_code", "icon", "screenshots", "topics", "tags", "certified", "installers"]
_releases = {}


def ordered(d, order):
    return {**{k: d[k] for k in order if k in d}, **{k: v for k, v in d.items() if k not in order}}


def request(url, accept="application/vnd.github+json"):
    headers = {"User-Agent": "pezzotto-launcher-catalog", "Accept": accept}
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)


def latest_release(repo):
    if repo not in _releases:
        with request(f"https://api.github.com/repos/{repo}/releases/latest") as r:
            _releases[repo] = json.load(r)
    return _releases[repo]


def sha256_of(url):
    h = hashlib.sha256()
    with request(url, accept="application/octet-stream") as r:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def resolve(inst):
    """(url, sha256, version) of the latest asset matching the installer's github block."""
    gh = inst["github"]
    rel = latest_release(gh["repo"])
    asset = next((a for a in rel.get("assets", []) if re.search(gh["asset"], a["name"])), None)
    if not asset:
        raise LookupError(f"{gh['repo']} {rel.get('tag_name')}: no asset matches {gh['asset']}")
    digest = asset.get("digest") or ""
    sha = digest[len("sha256:"):] if digest.startswith("sha256:") else None
    if not sha:
        print(f"  no digest for {asset['name']}, downloading to hash it", file=sys.stderr)
        sha = sha256_of(asset["browser_download_url"])
    return asset["browser_download_url"], sha, rel["tag_name"]


def pin_app(path, check_only):
    app = json.loads(path.read_text(encoding="utf-8"))
    changed, behind = False, []
    for inst in app["installers"]:
        if inst.get("kind") != "download" or "github" not in inst:
            continue
        try:
            url, sha, version = resolve(inst)
        except LookupError as e:
            print(f"{path.name}: {e}", file=sys.stderr)
            continue
        if check_only:
            if inst.get("version") != version:
                behind.append(f"{inst['platform']}/{','.join(inst.get('arch', ['any']))}: {inst.get('version') or 'unpinned'} -> {version}")
            continue
        if (inst.get("url"), inst.get("sha256"), inst.get("version")) != (url, sha, version):
            inst.update(url=url, sha256=sha, version=version)
            changed = True
    if check_only:
        return behind
    downloads = [i for i in app["installers"] if i.get("kind") == "download"]
    if downloads and all("url" in i and "sha256" in i for i in downloads):
        if changed or "certified" not in app:
            app["certified"] = {"level": "pinned", "date": datetime.date.today().isoformat()}
            changed = True
    if changed:
        app["installers"] = [ordered(i, INSTALLER_ORDER) for i in app["installers"]]
        path.write_text(json.dumps(ordered(app, APP_ORDER), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{path.name}: pinned")
    else:
        print(f"{path.name}: up to date")
    return []


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="report pins behind the latest release, change nothing")
    ap.add_argument("ids", nargs="*", help="app ids (default: all)")
    args = ap.parse_args()
    paths = [ROOT / "apps" / f"{i}.json" for i in args.ids] or sorted((ROOT / "apps").glob("*.json"))
    outdated = 0
    for path in paths:
        if not path.exists():
            sys.exit(f"{path} does not exist")
        for line in pin_app(path, args.check):
            print(f"{path.stem}: {line}")
            outdated += 1
    if args.check:
        print(f"{outdated} pins behind the latest release" if outdated else "all pins current")
        sys.exit(1 if outdated else 0)


if __name__ == "__main__":
    main()
