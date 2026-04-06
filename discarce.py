#!/usr/bin/env python3
"""discarce — find scarce vinyl on Discogs (high want/have ratio)"""

import json, sys, time, csv, io
import urllib.request, urllib.error, urllib.parse

API = "https://api.discogs.com"
UA = "discarce/1.0 +https://github.com/schwoah/claude1"
DELAY = {True: 1.0, False: 2.5}  # with/without token


def fetch(path, params=None, token=None):
    url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Discogs token={token}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode())
            time.sleep(DELAY[bool(token)])
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** (attempt + 2))
            else:
                print(f"  HTTP {e.code}: {url}", file=sys.stderr)
                return None
        except Exception:
            if attempt < 2:
                time.sleep(2)
    return None


def search(year, token, min_wants):
    results = []
    for page in range(1, 101):  # Discogs caps at page 100
        print(f"  {year} p.{page}...", end="", flush=True, file=sys.stderr)
        data = fetch("/database/search", {
            "type": "release", "year": str(year), "format": "Vinyl",
            "sort": "want", "sort_order": "desc", "per_page": "100", "page": str(page),
        }, token)
        if not data or not data.get("results"):
            break
        results.extend(data["results"])
        if data["results"][-1].get("community", {}).get("want", 0) < min_wants:
            break
        if page >= data.get("pagination", {}).get("pages", 0):
            break
    print(f" {len(results)} found", file=sys.stderr)
    return results


def ask(prompt, default):
    r = input(f"  {prompt} [{default}]: ").strip()
    return r if r else str(default)


def main():
    print("\n  discarce — scarce vinyl finder\n")

    # Config
    years = ask("Years (comma-separated)", "2025,2026")
    years = [int(y.strip()) for y in years.split(",")]

    min_wants = int(ask("Min wants", "30"))

    marketplace = ask("Include marketplace prices? (y/n)", "y").lower() == "y"

    fmt = ask("Output format (table/csv/json)", "table")

    token = ask("Discogs token (enter to skip)", "")
    token = token if token else None

    has_token = bool(token)
    delay = DELAY[has_token]
    search_req = len(years) * 10  # estimate ~10 pages per year
    detail_req = len(years) * 150 if marketplace else 0
    est_min = (search_req + detail_req) * delay / 60

    print(f"\n  {'─' * 40}")
    print(f"  Years:       {', '.join(str(y) for y in years)}")
    print(f"  Min wants:   {min_wants}")
    print(f"  Prices:      {'yes' if marketplace else 'no'}")
    print(f"  Format:      {fmt}")
    print(f"  Rate:        {'60' if has_token else '25'} req/min")
    print(f"  Est. time:   ~{est_min:.0f} min")
    print(f"  {'─' * 40}\n")

    if ask("Go? (y/n)", "y").lower() != "y":
        print("  Cancelled.")
        return

    t0 = time.time()

    # Search
    all_results = []
    for year in years:
        all_results.extend(search(year, token, min_wants))

    # Filter
    filtered = [r for r in all_results if r.get("community", {}).get("want", 0) >= min_wants]
    print(f"\n  {len(filtered)} releases match\n", file=sys.stderr)

    # Build entries
    releases = []
    for i, r in enumerate(filtered):
        rid = r["id"]
        c = r.get("community", {})
        want, have = c.get("want", 0), c.get("have", 0)
        entry = {
            "title": r.get("title", "?"),
            "genre": ", ".join(r.get("genre", r.get("style", ["?"]))),
            "want": want, "have": have,
            "ratio": round(want / have, 1) if have else float("inf"),
            "price": None, "for_sale": None,
            "url": f"https://www.discogs.com/release/{rid}",
        }

        if marketplace:
            print(f"  [{i+1}/{len(filtered)}] {entry['title'][:55]}", file=sys.stderr)
            d = fetch(f"/releases/{rid}", token=token)
            if d:
                entry["price"] = d.get("lowest_price")
                entry["for_sale"] = d.get("num_for_sale", 0)
                dc = d.get("community", {})
                entry["want"] = dc.get("want", want)
                entry["have"] = dc.get("have", have)
                h = entry["have"]
                entry["ratio"] = round(entry["want"] / h, 1) if h else float("inf")
                g = d.get("genres", []) + d.get("styles", [])
                if g:
                    entry["genre"] = ", ".join(g)

        releases.append(entry)

    releases.sort(key=lambda x: x["ratio"] if x["ratio"] != float("inf") else 999999, reverse=True)

    elapsed = time.time() - t0
    print(f"\n  Done in {elapsed/60:.1f} min\n", file=sys.stderr)

    # Output
    if fmt == "json":
        for r in releases:
            if r["ratio"] == float("inf"):
                r["ratio"] = "inf"
        print(json.dumps(releases, indent=2))

    elif fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(["Title", "Genre", "Want", "Have", "Ratio", "Price", "For Sale", "URL"])
        for r in releases:
            w.writerow([r["title"], r["genre"], r["want"], r["have"],
                        r["ratio"] if r["ratio"] != float("inf") else "inf",
                        f"${r['price']:.2f}" if r["price"] else "", r["for_sale"] or "", r["url"]])

    else:
        pfx = lambda v: f"${v:.2f}" if v else "—"
        print(f"\n{'Title':<45} {'Genre':<22} {'Want':>5} {'Have':>5} {'Ratio':>6} {'Price':>8} {'#':>4}  URL")
        print("─" * 130)
        for r in releases:
            t = r['title'][:43] + ".." if len(r['title']) > 45 else r['title']
            g = r['genre'][:20] + ".." if len(r['genre']) > 22 else r['genre']
            rat = f"{r['ratio']}" if r['ratio'] != float('inf') else "inf"
            fs = str(r['for_sale']) if r['for_sale'] is not None else "—"
            print(f"{t:<45} {g:<22} {r['want']:>5} {r['have']:>5} {rat:>6} {pfx(r['price']):>8} {fs:>4}  {r['url']}")
        print("─" * 130)
        print(f"{len(releases)} releases")


if __name__ == "__main__":
    main()
