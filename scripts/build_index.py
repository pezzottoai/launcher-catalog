#!/usr/bin/env python3
"""Validate the catalog and write index.json.

Usage:
  scripts/build_index.py                 # validate + write index.json
  scripts/build_index.py --check         # validate only
  scripts/build_index.py --check-remote  # also verify flatpak/winget/homebrew ids and GitHub release assets online
  scripts/build_index.py --enrich        # fill missing icon/description in index.json from Flathub AppStream data

Full JSON Schema validation runs when the `jsonschema` package is installed
(pip install jsonschema); otherwise only the built-in checks below run.
"""
import argparse
import datetime
import html.parser
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLATFORMS = {"linux", "windows", "macos"}
KINDS = {"flatpak", "winget", "homebrew", "download"}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def builtin_checks(app, fname, topic_ids):
    errs = []
    if app.get("id") + ".json" != fname:
        errs.append(f"file name must be {app.get('id')}.json")
    for t in app.get("topics", []):
        if t not in topic_ids:
            errs.append(f"unknown topic '{t}'")
    for i, inst in enumerate(app.get("installers", [])):
        where = f"installers[{i}]"
        if inst.get("platform") not in PLATFORMS:
            errs.append(f"{where}: bad platform")
        kind = inst.get("kind")
        if kind not in KINDS:
            errs.append(f"{where}: bad kind")
        if kind == "download":
            if ("url" in inst) == ("github" in inst):
                errs.append(f"{where}: needs exactly one of url / github")
            if "url" in inst and not re.fullmatch(r"[0-9a-f]{64}", inst.get("sha256", "")):
                errs.append(f"{where}: pinned url needs sha256")
            if "github" in inst:
                try:
                    re.compile(inst["github"]["asset"])
                except re.error as e:
                    errs.append(f"{where}: bad asset regex: {e}")
            if inst.get("format") == "archive" and "exec" not in inst:
                errs.append(f"{where}: archive needs exec")
    return errs


def http_ok(url):
    headers = {"User-Agent": "fosslauncher-catalog"}
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200, r.read()
    except urllib.error.HTTPError as e:
        return False, str(e).encode()
    except urllib.error.URLError as e:
        return False, str(e).encode()


def remote_checks(app):
    errs = []
    for i, inst in enumerate(app["installers"]):
        where = f"installers[{i}]"
        kind = inst["kind"]
        if kind == "flatpak" and inst.get("remote", "flathub") == "flathub":
            ok, _ = http_ok(f"https://flathub.org/api/v2/appstream/{inst['ref']}")
            if not ok:
                errs.append(f"{where}: flatpak ref {inst['ref']} not on Flathub")
        elif kind == "winget":
            pkg = inst["package"]
            path = "/".join([pkg[0].lower(), *pkg.split(".")])
            ok, _ = http_ok(f"https://api.github.com/repos/microsoft/winget-pkgs/contents/manifests/{path}")
            if not ok:
                errs.append(f"{where}: winget package {pkg} not in winget-pkgs")
        elif kind == "homebrew":
            what = "cask" if inst.get("cask", True) else "formula"
            parts = inst["package"].split("/")
            if len(parts) == 3:  # third-party tap: user/tap/name -> github.com/user/homebrew-tap
                user, tap, name = parts
                folder = "Casks" if what == "cask" else "Formula"
                ok, _ = http_ok(f"https://api.github.com/repos/{user}/homebrew-{tap}/contents/{folder}/{name}.rb")
            else:
                ok, _ = http_ok(f"https://formulae.brew.sh/api/{what}/{inst['package']}.json")
            if not ok:
                errs.append(f"{where}: homebrew {what} {inst['package']} not found")
        elif kind == "download" and "github" in inst:
            gh = inst["github"]
            ok, body = http_ok(f"https://api.github.com/repos/{gh['repo']}/releases/latest")
            if not ok:
                errs.append(f"{where}: no latest release for {gh['repo']}")
                continue
            names = [a["name"] for a in json.loads(body).get("assets", [])]
            if not any(re.search(gh["asset"], n) for n in names):
                errs.append(f"{where}: no asset of {gh['repo']} matches {gh['asset']}")
    return errs


class _HtmlText(html.parser.HTMLParser):
    """AppStream descriptions are a small HTML subset: <p>, <ul>/<ol>, <li>, <em>, <code>."""

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self.parts.append("\n\n")
        elif tag == "li":
            self.parts.append("\n• ")

    def handle_data(self, data):
        self.parts.append(" ".join(data.split()) if data.strip() else "")

    def text(self):
        paras = "".join(self.parts).split("\n\n")
        return "\n\n".join(p.strip() for p in paras if p.strip())


def enrich(app):
    """Fill icon/description from Flathub when the manifest has none (index.json only)."""
    if app.get("icon") and app.get("description"):
        return
    ref = next((i["ref"] for i in app["installers"]
                if i["kind"] == "flatpak" and i.get("remote", "flathub") == "flathub"), None)
    if not ref:
        return
    ok, body = http_ok(f"https://flathub.org/api/v2/appstream/{ref}")
    if not ok:
        return
    meta = json.loads(body)
    if not app.get("icon") and meta.get("icon"):
        app["icon"] = meta["icon"]
    if not app.get("description") and meta.get("description"):
        p = _HtmlText()
        p.feed(meta["description"])
        app["description"] = p.text()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only, do not write index.json")
    ap.add_argument("--check-remote", action="store_true", help="verify package ids and release assets online")
    ap.add_argument("--enrich", action="store_true", help="fill missing icon/description from Flathub")
    args = ap.parse_args()

    topics = load(ROOT / "topics.json")
    topic_ids = {t["id"] for t in topics["topics"]}
    try:
        import jsonschema
        validator = jsonschema.Draft202012Validator(load(ROOT / "schema" / "app.schema.json"))
    except ImportError:
        validator = None
        print("note: jsonschema not installed, running built-in checks only", file=sys.stderr)

    apps, failed = [], False
    for path in sorted((ROOT / "apps").glob("*.json")):
        app = load(path)
        errs = builtin_checks(app, path.name, topic_ids)
        if validator:
            errs += [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validator.iter_errors(app)]
        if args.check_remote and not errs:
            errs += remote_checks(app)
        for e in errs:
            print(f"{path.relative_to(ROOT)}: {e}", file=sys.stderr)
        failed |= bool(errs)
        app.pop("$schema", None)
        if args.enrich and not errs:
            enrich(app)
        apps.append(app)

    if failed:
        sys.exit(1)
    apps.sort(key=lambda a: a["name"].lower())
    print(f"{len(apps)} apps OK")
    if not args.check:
        out = ROOT / "index.json"
        try:
            old = load(out)
        except (OSError, ValueError):
            old = {}
        if old.get("topics") == topics["topics"] and old.get("apps") == apps:
            print("index.json unchanged")
            return
        index = {
            "schema_version": 1,
            "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "topics": topics["topics"],
            "apps": apps,
        }
        out.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote index.json")


if __name__ == "__main__":
    main()
