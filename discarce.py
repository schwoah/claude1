#!/usr/bin/env python3
"""discarce — find scarce vinyl on Discogs (high want/have ratio)"""

import json, sys, time, csv, os
import urllib.request, urllib.error, urllib.parse
from datetime import datetime

API = "https://api.discogs.com"
UA = "discarce/1.0 +https://github.com/schwoah/claude1"
DELAY = {True: 1.0, False: 2.5}  # with/without token

GENRES = [
    "Electronic", "Rock", "Pop", "Hip Hop", "Jazz", "Funk / Soul",
    "Classical", "Latin", "Reggae", "Blues", "Folk, World, & Country",
    "Stage & Screen", "Brass & Military", "Children's", "Non-Music",
]


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


def search_query(params, token, min_wants, label=""):
    """Run a single search query, paginating until wants drop below threshold."""
    results = []
    for page in range(1, 101):
        p = {**params, "per_page": "100", "page": str(page)}
        pfx = f"  {label} p.{page}..." if label else f"  p.{page}..."
        print(pfx, end="", flush=True, file=sys.stderr)

        data = fetch("/database/search", p, token)
        if not data or not data.get("results"):
            print("", file=sys.stderr)
            break

        batch = data["results"]
        results.extend(batch)
        total = data.get("pagination", {}).get("items", "?")

        if page == 1:
            print(f" ({total} total)", end="", file=sys.stderr)

        if batch[-1].get("community", {}).get("want", 0) < min_wants:
            print(f" stopped (below {min_wants} wants)", file=sys.stderr)
            break
        if page >= data.get("pagination", {}).get("pages", 0):
            print(" (last page)", file=sys.stderr)
            break
        print("", file=sys.stderr)

    return results


def check_total(year, token, genres=None):
    """Quick probe to see how many total results a year/genre combo has."""
    params = {"type": "release", "year": str(year), "format": "Vinyl",
              "sort": "want", "sort_order": "desc", "per_page": "1", "page": "1"}
    if genres and len(genres) == 1:
        params["genre"] = genres[0]
    data = fetch("/database/search", params, token)
    if data:
        return data.get("pagination", {}).get("items", 0)
    return 0


def search_year(year, token, min_wants, genres=None):
    """Search a year, auto-splitting by genre if results exceed 10k."""
    base = {"type": "release", "year": str(year), "format": "Vinyl",
            "sort": "want", "sort_order": "desc"}

    # If specific genres requested, search each directly
    if genres:
        all_results = []
        seen_ids = set()
        for genre in genres:
            params = {**base, "genre": genre}
            total = check_total(year, token, [genre])
            print(f"\n  [{year}/{genre}] {total:,} releases", file=sys.stderr)
            results = search_query(params, token, min_wants, label=f"{year}/{genre}")
            for r in results:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    all_results.append(r)
        return all_results

    # No genre filter — check if we need to auto-split
    total = check_total(year, token)
    print(f"\n  [{year}] {total:,} vinyl releases", file=sys.stderr)

    if total <= 10000:
        return search_query(base, token, min_wants, label=str(year))

    print(f"  Exceeds 10k limit — splitting by genre...", file=sys.stderr)
    all_results = []
    seen_ids = set()
    for genre in GENRES:
        params = {**base, "genre": genre}
        results = search_query(params, token, min_wants, label=f"{year}/{genre}")
        for r in results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                all_results.append(r)

    print(f"  [{year}] {len(all_results)} unique results across genres", file=sys.stderr)
    return all_results


def ask(prompt, default):
    r = input(f"  {prompt} [{default}]: ").strip()
    return r if r else str(default)


def save_results(releases, fmt, outdir="results"):
    """Save results to a timestamped file."""
    os.makedirs(outdir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = fmt if fmt in ("json", "csv") else "csv"
    path = os.path.join(outdir, f"discarce_{ts}.{ext}")

    if fmt == "json":
        out = []
        for r in releases:
            e = dict(r)
            if e["ratio"] == float("inf"):
                e["ratio"] = "inf"
            out.append(e)
        with open(path, "w") as f:
            json.dump(out, f, indent=2)
    else:
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Title", "Genre", "Want", "Have", "Ratio", "Rating", "Votes", "Price", "For Sale", "YouTube", "URL"])
            for r in releases:
                w.writerow([r["title"], r["genre"], r["want"], r["have"],
                            r["ratio"] if r["ratio"] != float("inf") else "inf",
                            r.get("rating", "") or "", r.get("votes", "") or "",
                            f"${r['price']:.2f}" if r["price"] else "", r["for_sale"] or "",
                            r.get("youtube", ""), r["url"]])
    return path


def main():
    print("\n  discarce — scarce vinyl finder\n")

    # Config
    years = ask("Years (comma-separated)", "2025,2026")
    years = [int(y.strip()) for y in years.split(",")]

    print(f"\n  Available genres: {', '.join(GENRES)}")
    genre_input = ask("Genres (comma-separated, or 'all')", "all")
    if genre_input.lower() == "all":
        genres = None
    else:
        genres = [g.strip() for g in genre_input.split(",")]

    min_wants = int(ask("Min wants", "30"))

    marketplace = ask("Include marketplace prices? (y/n)", "y").lower() == "y"

    fmt = ask("Output format (table/csv/json)", "table")

    token = ask("Discogs token (enter to skip)", "")
    token = token if token else None

    has_token = bool(token)
    delay = DELAY[has_token]
    num_genres = len(genres) if genres else 1
    search_req = len(years) * num_genres * 10
    detail_req = len(years) * num_genres * 50 if marketplace else 0
    est_min = (search_req + detail_req) * delay / 60

    print(f"\n  {'─' * 40}")
    print(f"  Years:       {', '.join(str(y) for y in years)}")
    print(f"  Genres:      {', '.join(genres) if genres else 'all'}")
    print(f"  Min wants:   {min_wants}")
    print(f"  Min ratio:   >1.0 (more wanted than owned)")
    print(f"  Prices:      {'yes' if marketplace else 'no'}")
    print(f"  Format:      {fmt}")
    print(f"  Rate:        {'60' if has_token else '25'} req/min")
    print(f"  Est. time:   ~{est_min:.0f} min")
    ext = fmt if fmt in ("json", "csv") else "csv"
    print(f"  Output:      results/discarce_<timestamp>.{ext}")
    print(f"  {'─' * 40}\n")

    if ask("Go? (y/n)", "y").lower() != "y":
        print("  Cancelled.")
        return

    t0 = time.time()

    # Search
    all_results = []
    for year in years:
        all_results.extend(search_year(year, token, min_wants, genres))

    # Dedupe, filter by min_wants, and drop ratio < 1
    seen = set()
    filtered = []
    for r in all_results:
        c = r.get("community", {})
        want, have = c.get("want", 0), c.get("have", 0)
        if r["id"] not in seen and want >= min_wants and (have == 0 or want / have > 1.0):
            seen.add(r["id"])
            filtered.append(r)

    print(f"\n  {len(filtered)} releases match (ratio > 1.0)\n", file=sys.stderr)

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
            "rating": None, "votes": None,
            "price": None, "for_sale": None,
            "youtube": None, "videos": 0,
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
                # Re-check ratio after detail fetch
                if h > 0 and entry["want"] / h <= 1.0:
                    continue
                g = d.get("genres", []) + d.get("styles", [])
                if g:
                    entry["genre"] = ", ".join(g)
                ri = dc.get("rating", {})
                entry["rating"] = round(ri.get("average", 0), 2) or None
                entry["votes"] = ri.get("count", 0) or None
                vids = d.get("videos", [])
                yt = [v["uri"] for v in vids if "youtube" in v.get("uri", "").lower()]
                entry["youtube"] = yt[0] if yt else None
                entry["videos"] = len(vids)

        releases.append(entry)

    releases.sort(key=lambda x: x["ratio"] if x["ratio"] != float("inf") else 999999, reverse=True)

    elapsed = time.time() - t0

    # Save
    outpath = save_results(releases, fmt)
    print(f"\n  Done in {elapsed/60:.1f} min — saved to {outpath}\n", file=sys.stderr)

    # Print
    if fmt == "json":
        out = []
        for r in releases:
            e = dict(r)
            if e["ratio"] == float("inf"):
                e["ratio"] = "inf"
            out.append(e)
        print(json.dumps(out, indent=2))

    elif fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(["Title", "Genre", "Want", "Have", "Ratio", "Rating", "Votes", "Price", "For Sale", "YouTube", "URL"])
        for r in releases:
            w.writerow([r["title"], r["genre"], r["want"], r["have"],
                        r["ratio"] if r["ratio"] != float("inf") else "inf",
                        r.get("rating", "") or "", r.get("votes", "") or "",
                        f"${r['price']:.2f}" if r["price"] else "", r["for_sale"] or "",
                        r.get("youtube", ""), r["url"]])

    else:
        pfx = lambda v: f"${v:.2f}" if v else "—"
        print(f"\n{'Title':<45} {'Genre':<20} {'Want':>5} {'Have':>5} {'Ratio':>6} {'Rate':>5} {'Price':>8} {'#':>4} {'YT':>3}  URL")
        print("─" * 135)
        for r in releases:
            t = r['title'][:43] + ".." if len(r['title']) > 45 else r['title']
            g = r['genre'][:18] + ".." if len(r['genre']) > 20 else r['genre']
            rat = f"{r['ratio']}" if r['ratio'] != float('inf') else "inf"
            fs = str(r['for_sale']) if r['for_sale'] is not None else "—"
            rt = f"{r.get('rating')}" if r.get('rating') else "—"
            yt = f"{r.get('videos', 0)}" if r.get("youtube") else "—"
            print(f"{t:<45} {g:<20} {r['want']:>5} {r['have']:>5} {rat:>6} {rt:>5} {pfx(r['price']):>8} {fs:>4} {yt:>3}  {r['url']}")
        print("─" * 130)
        print(f"{len(releases)} releases")


if __name__ == "__main__":
    main()
