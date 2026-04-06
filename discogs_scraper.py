#!/usr/bin/env python3
"""
Scrape Discogs for 2025-2026 vinyl releases with high want/own ratio.
Filters: at least 30 wants. Sorted by want/have ratio descending.

Usage:
    python discogs_scraper.py
    python discogs_scraper.py --token YOUR_DISCOGS_TOKEN   # optional, for higher rate limits
    python discogs_scraper.py --min-wants 50               # override minimum wants threshold
    python discogs_scraper.py --format CSV                 # output as CSV
"""

import argparse
import csv
import io
import json
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

BASE_URL = "https://api.discogs.com"
USER_AGENT = "DiscogsWantScraper/1.0 +https://github.com/schwoah/claude1"

# Discogs rate limit: 25/min unauthenticated, 60/min with token
RATE_LIMIT_DELAY_UNAUTH = 2.5  # ~24 req/min
RATE_LIMIT_DELAY_AUTH = 1.0    # ~60 req/min


def api_request(path, params=None, token=None, delay=None):
    """Make a Discogs API request with rate limiting and retries."""
    if params:
        query = urllib.parse.urlencode(params)
        url = f"{BASE_URL}{path}?{query}"
    else:
        url = f"{BASE_URL}{path}"

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Discogs token={token}"

    if delay is None:
        delay = RATE_LIMIT_DELAY_AUTH if token else RATE_LIMIT_DELAY_UNAUTH

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            time.sleep(delay)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** (attempt + 2)
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  HTTP {e.code} for {url}", file=sys.stderr)
                return None
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(2)
    return None


def search_releases(year, token=None, max_pages=10):
    """Search for vinyl releases in a given year, sorted by most wanted."""
    all_results = []
    for page in range(1, max_pages + 1):
        print(f"  Fetching {year} page {page}/{max_pages}...", file=sys.stderr)
        data = api_request("/database/search", {
            "type": "release",
            "year": str(year),
            "format": "Vinyl",
            "sort": "want",
            "sort_order": "desc",
            "per_page": "100",
            "page": str(page),
        }, token=token)

        if not data or "results" not in data:
            break

        results = data["results"]
        if not results:
            break

        all_results.extend(results)

        # Stop early if community.want falls below threshold (search is sorted by want desc)
        last = results[-1]
        if last.get("community", {}).get("want", 0) < 30:
            break

        pagination = data.get("pagination", {})
        if page >= pagination.get("pages", 0):
            break

    return all_results


def get_release_details(release_id, token=None):
    """Fetch full release details including community stats and lowest price."""
    return api_request(f"/releases/{release_id}", token=token)


def format_price(price):
    """Format price value."""
    if price is None:
        return "N/A"
    return f"${price:.2f}"


def main():
    parser = argparse.ArgumentParser(description="Scrape Discogs for high-demand vinyl releases")
    parser.add_argument("--token", help="Discogs personal access token (optional, for higher rate limits)")
    parser.add_argument("--min-wants", type=int, default=30, help="Minimum number of wants (default: 30)")
    parser.add_argument("--max-pages", type=int, default=10, help="Max search pages per year (default: 10)")
    parser.add_argument("--format", choices=["table", "csv", "json"], default="table", help="Output format")
    parser.add_argument("--years", nargs="+", type=int, default=[2025, 2026], help="Years to search")
    parser.add_argument("--skip-details", action="store_true",
                        help="Skip fetching individual release details (faster but no price data)")
    args = parser.parse_args()

    print(f"Searching Discogs for {args.years} vinyl releases with >= {args.min_wants} wants...\n",
          file=sys.stderr)

    # Phase 1: Search for releases
    candidates = []
    for year in args.years:
        print(f"[{year}]", file=sys.stderr)
        results = search_releases(year, token=args.token, max_pages=args.max_pages)
        print(f"  Found {len(results)} results", file=sys.stderr)
        candidates.extend(results)

    # Filter by minimum wants from search results
    filtered = []
    for r in candidates:
        community = r.get("community", {})
        want = community.get("want", 0)
        have = community.get("have", 0)
        if want >= args.min_wants:
            filtered.append(r)

    print(f"\n{len(filtered)} releases with >= {args.min_wants} wants", file=sys.stderr)

    # Phase 2: Fetch details for price data and accurate stats
    releases = []
    for i, r in enumerate(filtered):
        release_id = r.get("id")
        title = r.get("title", "Unknown")
        genre = ", ".join(r.get("genre", r.get("style", ["Unknown"])))

        community = r.get("community", {})
        want = community.get("want", 0)
        have = community.get("have", 0)
        ratio = want / have if have > 0 else float("inf")

        entry = {
            "id": release_id,
            "title": title,
            "genre": genre,
            "want": want,
            "have": have,
            "ratio": ratio,
            "lowest_price": None,
            "num_for_sale": None,
            "url": f"https://www.discogs.com/release/{release_id}",
        }

        if not args.skip_details:
            print(f"  Fetching details {i+1}/{len(filtered)}: {title[:50]}...", file=sys.stderr)
            details = get_release_details(release_id, token=args.token)
            if details:
                entry["lowest_price"] = details.get("lowest_price")
                entry["num_for_sale"] = details.get("num_for_sale", 0)
                # Update with more accurate community stats
                dc = details.get("community", {})
                entry["want"] = dc.get("want", want)
                entry["have"] = dc.get("have", have)
                h = entry["have"]
                entry["ratio"] = entry["want"] / h if h > 0 else float("inf")
                # Get genres from details
                genres = details.get("genres", [])
                styles = details.get("styles", [])
                if genres or styles:
                    entry["genre"] = ", ".join(genres + styles)

        releases.append(entry)

    # Sort by want/have ratio descending
    releases.sort(key=lambda x: x["ratio"], reverse=True)

    # Output
    if args.format == "json":
        for r in releases:
            if r["ratio"] == float("inf"):
                r["ratio"] = "inf"
        print(json.dumps(releases, indent=2))

    elif args.format == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["Title", "Genre", "Want", "Have", "Ratio", "Lowest Price", "For Sale", "URL"])
        for r in releases:
            writer.writerow([
                r["title"], r["genre"], r["want"], r["have"],
                f"{r['ratio']:.1f}" if r["ratio"] != float("inf") else "inf",
                format_price(r["lowest_price"]), r["num_for_sale"] or "N/A", r["url"],
            ])
        print(out.getvalue())

    else:  # table
        print(f"\n{'='*120}")
        print(f"{'Title':<45} {'Genre':<25} {'Want':>5} {'Have':>5} {'Ratio':>7} {'Price':>8} {'Sale':>5}  URL")
        print(f"{'='*120}")
        for r in releases:
            ratio_str = f"{r['ratio']:.1f}" if r['ratio'] != float('inf') else "inf"
            title = r['title'][:43] + ".." if len(r['title']) > 45 else r['title']
            genre = r['genre'][:23] + ".." if len(r['genre']) > 25 else r['genre']
            print(f"{title:<45} {genre:<25} {r['want']:>5} {r['have']:>5} {ratio_str:>7} "
                  f"{format_price(r['lowest_price']):>8} {r['num_for_sale'] or 'N/A':>5}  {r['url']}")
        print(f"{'='*120}")
        print(f"Total: {len(releases)} releases")


if __name__ == "__main__":
    main()
