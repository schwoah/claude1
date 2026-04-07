#!/usr/bin/env python3
"""discarce-list — analyze a Discogs list for scarce vinyl"""

import json, sys, time, csv, os, re
import urllib.request, urllib.error, urllib.parse
from datetime import datetime

API = "https://api.discogs.com"
UA = "discarce/1.0 +https://github.com/schwoah/claude1"
DELAY = {True: 1.0, False: 2.5}


def fetch(url_or_path, token=None):
    url = url_or_path if url_or_path.startswith("http") else f"{API}{url_or_path}"
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


def parse_list_url(url):
    """Extract list ID from a Discogs list URL or raw ID."""
    m = re.search(r'/lists/[^/]+/(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'(\d+)', url)
    if m:
        return m.group(1)
    return None


def ask(prompt, default):
    r = input(f"  {prompt} [{default}]: ").strip()
    return r if r else str(default)


def save_results(releases, fmt, list_id, outdir="results"):
    os.makedirs(outdir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = fmt if fmt in ("json", "csv") else "csv"
    path = os.path.join(outdir, f"discarce_list_{list_id}_{ts}.{ext}")

    if fmt == "json":
        out = []
        for r in releases:
            e = dict(r)
            if e.get("ratio") == float("inf"):
                e["ratio"] = "inf"
            out.append(e)
        with open(path, "w") as f:
            json.dump(out, f, indent=2)
    else:
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Title", "Genre", "Want", "Have", "Ratio", "Rating", "Votes", "Price", "For Sale", "URL"])
            for r in releases:
                w.writerow([r["title"], r["genre"], r["want"], r["have"],
                            r["ratio"] if r["ratio"] != float("inf") else "inf",
                            r["rating"] or "", r["votes"] or "",
                            f"${r['price']:.2f}" if r["price"] else "", r["for_sale"] or "", r["url"]])
    return path


def main():
    print("\n  discarce-list — analyze a Discogs list\n")

    url = ask("Discogs list URL or ID", "")
    if not url:
        print("  No URL provided.")
        return

    list_id = parse_list_url(url)
    if not list_id:
        print("  Could not parse list ID.")
        return

    fmt = ask("Output format (table/csv/json)", "table")

    token = ask("Discogs token (enter to skip)", "")
    token = token if token else None

    # Fetch list (all pages)
    print(f"\n  Fetching list {list_id}...", file=sys.stderr)
    list_data = fetch(f"/lists/{list_id}", token)
    if not list_data:
        print("  Failed to fetch list. Check the URL/ID and try again.")
        return

    list_name = list_data.get("name", "Unknown")
    items = list(list_data.get("items", []))

    # Paginate through remaining pages
    pagination = list_data.get("pagination", {})
    total_pages = pagination.get("pages", 1)
    if total_pages > 1:
        print(f"  Page 1/{total_pages}...", file=sys.stderr)
        for page in range(2, total_pages + 1):
            print(f"  Page {page}/{total_pages}...", file=sys.stderr)
            page_data = fetch(f"/lists/{list_id}?page={page}", token)
            if page_data and page_data.get("items"):
                items.extend(page_data["items"])
            else:
                break

    release_items = [i for i in items if i.get("type") == "release"]

    print(f"  List: {list_name}", file=sys.stderr)
    print(f"  {len(items)} items ({len(release_items)} releases)", file=sys.stderr)

    if not release_items:
        print("  No releases found in this list.")
        return

    has_token = bool(token)
    delay = DELAY[has_token]
    est_min = len(release_items) * delay / 60

    print(f"\n  {'─' * 40}")
    print(f"  List:        {list_name}")
    print(f"  Releases:    {len(release_items)}")
    print(f"  Rate:        {'60' if has_token else '25'} req/min")
    print(f"  Est. time:   ~{est_min:.0f} min")
    print(f"  {'─' * 40}\n")

    if ask("Go? (y/n)", "y").lower() != "y":
        print("  Cancelled.")
        return

    t0 = time.time()

    # Fetch each release
    releases = []
    for i, item in enumerate(release_items):
        rid = item.get("id")
        print(f"  [{i+1}/{len(release_items)}] {item.get('display_title', '?')[:55]}", file=sys.stderr)

        d = fetch(f"/releases/{rid}", token)
        if not d:
            continue

        dc = d.get("community", {})
        want = dc.get("want", 0)
        have = dc.get("have", 0)
        rating_info = dc.get("rating", {})
        rating = rating_info.get("average", 0)
        votes = rating_info.get("count", 0)

        ratio = round(want / have, 1) if have else float("inf")

        genres = d.get("genres", []) + d.get("styles", [])
        title = f"{', '.join(a['name'] for a in d.get('artists', []))} - {d.get('title', '?')}"

        releases.append({
            "title": title,
            "genre": ", ".join(genres) if genres else "?",
            "want": want,
            "have": have,
            "ratio": ratio,
            "rating": round(rating, 2) if rating else None,
            "votes": votes if votes else None,
            "price": d.get("lowest_price"),
            "for_sale": d.get("num_for_sale", 0),
            "url": f"https://www.discogs.com/release/{rid}",
        })

    releases.sort(key=lambda x: x["ratio"] if x["ratio"] != float("inf") else 999999, reverse=True)

    elapsed = time.time() - t0

    # Save
    outpath = save_results(releases, fmt, list_id)
    print(f"\n  Done in {elapsed/60:.1f} min — saved to {outpath}\n", file=sys.stderr)

    # Print
    scarce = [r for r in releases if r["ratio"] > 1.0 or r["ratio"] == float("inf")]
    common = [r for r in releases if r["ratio"] <= 1.0]

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
        w.writerow(["Title", "Genre", "Want", "Have", "Ratio", "Rating", "Votes", "Price", "For Sale", "URL"])
        for r in releases:
            w.writerow([r["title"], r["genre"], r["want"], r["have"],
                        r["ratio"] if r["ratio"] != float("inf") else "inf",
                        r["rating"] or "", r["votes"] or "",
                        f"${r['price']:.2f}" if r["price"] else "", r["for_sale"] or "", r["url"]])

    else:
        pfx = lambda v: f"${v:.2f}" if v else "—"
        rat_s = lambda v: f"{v}" if v != float("inf") else "inf"

        if scarce:
            print(f"\n  SCARCE (ratio > 1.0) — {len(scarce)} releases")
            print(f"{'Title':<42} {'Genre':<18} {'Want':>5} {'Have':>5} {'Ratio':>6} {'Rate':>5} {'Price':>8} {'#':>4}  URL")
            print("─" * 130)
            for r in scarce:
                t = r['title'][:40] + ".." if len(r['title']) > 42 else r['title']
                g = r['genre'][:16] + ".." if len(r['genre']) > 18 else r['genre']
                rt = f"{r['rating']}" if r['rating'] else "—"
                fs = str(r['for_sale']) if r['for_sale'] is not None else "—"
                print(f"{t:<42} {g:<18} {r['want']:>5} {r['have']:>5} {rat_s(r['ratio']):>6} {rt:>5} {pfx(r['price']):>8} {fs:>4}  {r['url']}")

        if common:
            print(f"\n  COMMON (ratio <= 1.0) — {len(common)} releases")
            print(f"{'Title':<42} {'Genre':<18} {'Want':>5} {'Have':>5} {'Ratio':>6} {'Rate':>5} {'Price':>8} {'#':>4}  URL")
            print("─" * 130)
            for r in common:
                t = r['title'][:40] + ".." if len(r['title']) > 42 else r['title']
                g = r['genre'][:16] + ".." if len(r['genre']) > 18 else r['genre']
                rt = f"{r['rating']}" if r['rating'] else "—"
                fs = str(r['for_sale']) if r['for_sale'] is not None else "—"
                print(f"{t:<42} {g:<18} {r['want']:>5} {r['have']:>5} {rat_s(r['ratio']):>6} {rt:>5} {pfx(r['price']):>8} {fs:>4}  {r['url']}")

        print("─" * 130)
        print(f"{len(releases)} total — {len(scarce)} scarce, {len(common)} common")


if __name__ == "__main__":
    main()
