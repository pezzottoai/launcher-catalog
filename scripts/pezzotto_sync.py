#!/usr/bin/env python3
"""Copy the pezzotto.ai verdict on each knock-off into its launcher manifest.

The stall (https://pezzotto.ai, catalog/clones.json in pezzottoai/pezzottoai.github.io) is
where clones get graded. This script matches those entries to the apps here by source
repository and writes a `pezzotto` block into the manifest:

  "pezzotto": { "entry": "rustgis", "of": "ArcGIS Pro (Esri)", "original": "https://...",
                "grade": "B", "verified": "desk", "status": "alive", "checked": "2026-10-30",
                "coverage": [...], "missing": [...] }

The launcher shows it: what the app is a knock-off of, the grade, what is missing. The
block is never edited by hand; rerun this script when the stall changes its mind.

Usage:
  scripts/pezzotto_sync.py                     # from https://pezzotto.ai/catalog/clones.json
  scripts/pezzotto_sync.py --from clones.json  # from a local checkout of the site
  scripts/pezzotto_sync.py --check             # report drift, change nothing; exit 1 on drift
"""
import argparse
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE_CATALOG = "https://pezzotto.ai/catalog/clones.json"
FIELDS = ["entry", "of", "original", "grade", "verified", "status", "checked", "coverage", "missing"]


def ordered(d, order):
    return {**{k: d[k] for k in order if k in d}, **{k: v for k, v in d.items() if k not in order}}


def repo_key(url):
    """'https://github.com/Org/Repo.git/' -> 'github.com/org/repo'"""
    u = (url or "").strip().lower()
    for prefix in ("https://", "http://", "www."):
        if u.startswith(prefix):
            u = u[len(prefix):]
    u = u.rstrip("/")
    return u[:-4] if u.endswith(".git") else u


def load_clones(source):
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"User-Agent": "pezzotto-launcher-catalog"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    return json.loads(pathlib.Path(source).read_text(encoding="utf-8"))


def block_for(entry):
    pz = {
        "entry": entry["id"],
        "of": entry["target"]["name"],
        "original": entry["target"].get("url"),
        "grade": entry["grade"],
        "verified": entry.get("verified", "desk"),
        "status": entry.get("status"),
        "checked": entry.get("checked"),
        "coverage": entry.get("coverage") or None,
        "missing": entry.get("missing") or None,
    }
    return {k: v for k, v in pz.items() if v is not None}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="source", default=SITE_CATALOG, help="clones.json URL or path")
    ap.add_argument("--check", action="store_true", help="report manifests out of step with the stall, change nothing")
    args = ap.parse_args()

    clones = load_clones(args.source)
    by_repo = {repo_key(c["clone"]["repo"]): c for c in clones if c.get("clone", {}).get("repo")}
    drift, matched = 0, set()
    for path in sorted((ROOT / "apps").glob("*.json")):
        app = json.loads(path.read_text(encoding="utf-8"))
        entry = by_repo.get(repo_key(app.get("source_code")))
        want = block_for(entry) if entry else None
        if entry:
            matched.add(entry["id"])
        if app.get("pezzotto") == want:
            continue
        drift += 1
        if args.check:
            print(f"{path.name}: {'pezzotto block out of date' if want else 'no longer on the stall'}")
            continue
        if want:
            app["pezzotto"] = ordered(want, FIELDS)
        else:
            app.pop("pezzotto", None)
        from pin import APP_ORDER  # noqa: E402  (same directory)
        path.write_text(json.dumps(ordered(app, APP_ORDER), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{path.name}: {'pezzotto of ' + want['of'] + ' (' + want['grade'] + ')' if want else 'pezzotto block removed'}")
    for c in clones:
        if c["id"] not in matched:
            print(f"not in the launcher catalog: {c['id']} ({c['clone'].get('repo')})", file=sys.stderr)
    if args.check:
        print(f"{drift} manifests out of step with the stall" if drift else "all manifests match the stall")
        sys.exit(1 if drift else 0)
    print(f"{len(matched)} knock-offs, {drift} manifests updated")


if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    main()
