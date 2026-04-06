#!/usr/bin/env python3
"""
Scrape Discogs for vinyl releases with high want/own ratio.
Interactive mode prompts for settings and shows time estimate before running.

Usage:
    python3 discogs_scraper.py                              # interactive mode
    python3 discogs_scraper.py --no-interactive              # use defaults, skip prompts
    python3 discogs_scraper.py --token YOUR_DISCOGS_TOKEN    # with auth token
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


def search_releases(year, token=None, max_pages=10, min_wants=30):
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

        # Stop early if community.want falls below threshold
        last = results[-1]
        if last.get("community", {}).get("want", 0) < min_wants:
            break

        pagination = data.get("pagination", {})
        if page >= pagination.get("pages", 0):
            break

    return all_results


def format_price(price):
    """Format price value."""
    if price is None:
        return "N/A"
    return f"${price:.2f}"


def estimate_time(num_years, max_pages, include_details, has_token):
    """Estimate total run time in minutes."""
    delay = RATE_LIMIT_DELAY_AUTH if has_token else RATE_LIMIT_DELAY_UNAUTH

    # Search phase: up to max_pages per year
    search_requests = num_years * max_pages
    search_time = search_requests * delay

    # Detail phase: estimate ~100-300 qualifying releases per year
    # (conservative estimate — actual count depends on min_wants filter)
    if include_details:
        est_releases_per_year = 150
        detail_requests = num_years * est_releases_per_year
        detail_time = detail_requests * delay
    else:
        detail_requests = 0
        detail_time = 0

    total_seconds = search_time + detail_time
    total_requests = search_requests + detail_requests

    return total_seconds, total_requests


def prompt_input(prompt_text, default, cast=str):
    """Prompt user for input with a default value."""
    raw = input(f"{prompt_text} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        print(f"  Invalid input, using default: {default}")
        return default


def interactive_setup(token=None):
    """Interactively configure scraper settings."""
    print("\n" + "=" * 50)
    print("  DISCOGS VINYL RELEASE SCRAPER")
    print("=" * 50)
    print("\nSearches for vinyl releases sorted by want/have")
    print("ratio to find high-demand, hard-to-find records.\n")

    # Years
    years_input = input("Years to search [2025,2026]: ").strip()
    if years_input:
        try:
            years = [int(y.strip()) for y in years_input.replace(" ", ",").split(",") if y.strip()]
        except ValueError:
            print("  Invalid input, using default: 2025, 2026")
            years = [2025, 2026]
    else:
        years = [2025, 2026]

    # Min wants
    min_wants = prompt_input("Minimum wants threshold", 30, int)

    # Max pages
    max_pages = prompt_input("Max search pages per year (100 results/page)", 10, int)

    # Include marketplace/price data
    details_input = input("Include marketplace data (price, # for sale)? [Y/n]: ").strip().lower()
    include_details = details_input != "n"

    # Output format
    fmt = prompt_input("Output format (table/csv/json)", "table")
    if fmt not in ("table", "csv", "json"):
        print(f"  Unknown format '{fmt}', using table")
        fmt = "table"

    # Token
    if not token:
        token_input = input("Discogs token (optional, press Enter to skip): ").strip()
        if token_input:
            token = token_input

    # Time estimate
    has_token = bool(token)
    est_seconds, est_requests = estimate_time(len(years), max_pages, include_details, has_token)
    est_min = est_seconds / 60

    print("\n" + "-" * 50)
    print("  SUMMARY")
    print("-" * 50)
    print(f"  Years:            {', '.join(str(y) for y in years)}")
    print(f"  Min wants:        {min_wants}")
    print(f"  Max pages/year:   {max_pages}")
    print(f"  Marketplace data: {'Yes' if include_details else 'No (faster)'}")
    print(f"  Output format:    {fmt}")
    print(f"  Auth token:       {'Yes (60 req/min)' if has_token else 'No (25 req/min)'}")
    print(f"  Est. requests:    ~{est_requests}")
    print(f"  Est. time:        ~{est_min:.0f} min")
    if not has_token and include_details:
        print(f"\n  Tip: A free token from discogs.com/settings/developers")
        print(f"       would cut this to ~{est_seconds * 0.4 / 60:.0f} min")
    print("-" * 50)

    confirm = input("\nProceed? [Y/n]: ").strip().lower()
    if confirm == "n":
        print("Cancelled.")
        sys.exit(0)

    return {
        "years": years,
        "min_wants": min_wants,
        "max_pages": max_pages,
        "include_details": include_details,
        "format": fmt,
        "token": token,
    }


def run_scraper(years, min_wants, max_pages, include_details, fmt, token):
    """Run the scraper with the given settings."""
    start_time = time.time()

    print(f"\nSearching Discogs for {years} vinyl releases with >= {min_wants} wants...\n",
          file=sys.stderr)

    # Phase 1: Search for releases
    candidates = []
    for year in years:
        print(f"[{year}]", file=sys.stderr)
        results = search_releases(year, token=token, max_pages=max_pages, min_wants=min_wants)
        print(f"  Found {len(results)} results", file=sys.stderr)
        candidates.extend(results)

    # Filter by minimum wants
    filtered = []
    for r in candidates:
        community = r.get("community", {})
        want = community.get("want", 0)
        if want >= min_wants:
            filtered.append(r)

    print(f"\n{len(filtered)} releases with >= {min_wants} wants", file=sys.stderr)

    if include_details:
        # Refine time estimate now that we know actual count
        delay = RATE_LIMIT_DELAY_AUTH if token else RATE_LIMIT_DELAY_UNAUTH
        remaining_sec = len(filtered) * delay
        print(f"Fetching details for {len(filtered)} releases (~{remaining_sec / 60:.0f} min remaining)...\n",
              file=sys.stderr)

    # Phase 2: Build release entries
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

        if include_details:
            print(f"  [{i+1}/{len(filtered)}] {title[:60]}...", file=sys.stderr)
            details = api_request(f"/releases/{release_id}", token=token)
            if details:
                entry["lowest_price"] = details.get("lowest_price")
                entry["num_for_sale"] = details.get("num_for_sale", 0)
                dc = details.get("community", {})
                entry["want"] = dc.get("want", want)
                entry["have"] = dc.get("have", have)
                h = entry["have"]
                entry["ratio"] = entry["want"] / h if h > 0 else float("inf")
                genres = details.get("genres", [])
                styles = details.get("styles", [])
                if genres or styles:
                    entry["genre"] = ", ".join(genres + styles)

        releases.append(entry)

    # Sort by want/have ratio descending
    releases.sort(key=lambda x: x["ratio"], reverse=True)

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed / 60:.1f} min\n", file=sys.stderr)

    # Output
    if fmt == "json":
        for r in releases:
            if r["ratio"] == float("inf"):
                r["ratio"] = "inf"
        print(json.dumps(releases, indent=2))

    elif fmt == "csv":
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
        print(f"\n{'=' * 130}")
        print(f"{'Title':<45} {'Genre':<25} {'Want':>5} {'Have':>5} {'Ratio':>7} {'Price':>8} {'Sale':>5}  URL")
        print(f"{'=' * 130}")
        for r in releases:
            ratio_str = f"{r['ratio']:.1f}" if r['ratio'] != float('inf') else "inf"
            title = r['title'][:43] + ".." if len(r['title']) > 45 else r['title']
            genre = r['genre'][:23] + ".." if len(r['genre']) > 25 else r['genre']
            print(f"{title:<45} {genre:<25} {r['want']:>5} {r['have']:>5} {ratio_str:>7} "
                  f"{format_price(r['lowest_price']):>8} {r['num_for_sale'] or 'N/A':>5}  {r['url']}")
        print(f"{'=' * 130}")
        print(f"Total: {len(releases)} releases")


def main():
    parser = argparse.ArgumentParser(description="Scrape Discogs for high-demand vinyl releases")
    parser.add_argument("--token", help="Discogs personal access token")
    parser.add_argument("--no-interactive", action="store_true", help="Skip interactive prompts, use defaults")
    # CLI overrides (used with --no-interactive)
    parser.add_argument("--min-wants", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--format", choices=["table", "csv", "json"], default="table")
    parser.add_argument("--years", nargs="+", type=int, default=[2025, 2026])
    parser.add_argument("--skip-details", action="store_true")
    args = parser.parse_args()

    if args.no_interactive:
        run_scraper(
            years=args.years,
            min_wants=args.min_wants,
            max_pages=args.max_pages,
            include_details=not args.skip_details,
            fmt=args.format,
            token=args.token,
        )
    else:
        settings = interactive_setup(token=args.token)
        run_scraper(**settings)


if __name__ == "__main__":
    main()
