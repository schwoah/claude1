#!/usr/bin/env python3
"""slskd_dl — search & download music from a CSV list via slskd API"""

import json, sys, time, csv, os, re
import urllib.request, urllib.error, urllib.parse
from datetime import datetime

DEFAULT_URL = "http://localhost:5030"
SEARCH_TIMEOUT = 15
POLL_INTERVAL = 2

# Format scoring for auto-pick (higher = better)
FORMAT_SCORES = {
    "flac": 100, "wav": 95, "alac": 90,
    "mp3-320": 80, "mp3-v0": 70, "mp3-256": 60,
    "mp3-192": 40, "mp3": 30, "ogg": 35, "aac": 35,
}

HEADER_ALIASES = {
    "artist": "artist", "performer": "artist", "band": "artist",
    "title": "title", "track": "title", "song": "title", "name": "title",
    "album": "album", "release": "album",
}


def ask(prompt, default=""):
    r = input(f"  {prompt} [{default}]: ").strip()
    return r if r else str(default)


# ── slskd API helper ──────────────────────────────────────────────────────────

def slskd_api(method, path, base_url, api_key, data=None):
    url = f"{base_url}/api/v0{path}"
    body = json.dumps(data).encode() if data else None
    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                time.sleep(2 ** (attempt + 1))
            else:
                err_body = ""
                try:
                    err_body = e.read().decode()[:200]
                except Exception:
                    pass
                print(f"  HTTP {e.code} {method} {path}: {err_body}", file=sys.stderr)
                return None
        except urllib.error.URLError as e:
            print(f"  Connection error: {e.reason}", file=sys.stderr)
            print(f"  Is slskd running at {base_url}?", file=sys.stderr)
            return None
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"  Error: {e}", file=sys.stderr)
                return None
    return None


# ── CSV parsing with auto-detection ───────────────────────────────────────────

def detect_columns(row):
    """Detect column mapping from header row. Returns dict or None."""
    mapping = {}
    for i, cell in enumerate(row):
        key = cell.strip().lower().replace(" ", "")
        if key in HEADER_ALIASES:
            mapping[HEADER_ALIASES[key]] = i
    if "artist" in mapping and ("title" in mapping or "album" in mapping):
        return mapping
    return None


def parse_csv(path):
    """Parse CSV file, auto-detecting columns. Returns list of dicts."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        return []

    # Try first row as headers
    mapping = detect_columns(rows[0])
    if mapping:
        data_rows = rows[1:]
        print(f"  Detected columns: {mapping}", file=sys.stderr)
    else:
        # Guess: col 0 = artist, col 1 = title, col 2 = album (if exists)
        ncols = len(rows[0])
        mapping = {"artist": 0}
        if ncols >= 2:
            mapping["title"] = 1
        if ncols >= 3:
            mapping["album"] = 2
        data_rows = rows
        print(f"  No headers detected, guessing: {mapping}", file=sys.stderr)

    results = []
    for row in data_rows:
        if not row or all(c.strip() == "" for c in row):
            continue
        entry = {}
        for field, idx in mapping.items():
            if idx < len(row):
                entry[field] = row[idx].strip()
        if entry.get("artist"):
            results.append(entry)
    return results


# ── Search & scoring ──────────────────────────────────────────────────────────

def build_query(entry):
    """Build search query string from CSV entry."""
    parts = [entry.get("artist", "")]
    if entry.get("title"):
        parts.append(entry["title"])
    elif entry.get("album"):
        parts.append(entry["album"])
    return " ".join(p for p in parts if p)


def guess_format(filename):
    """Guess audio format and quality from filename."""
    fn = filename.lower()
    ext = fn.rsplit(".", 1)[-1] if "." in fn else ""
    if ext == "flac":
        return "flac"
    if ext == "wav":
        return "wav"
    if ext in ("m4a", "alac"):
        return "alac"
    if ext == "ogg":
        return "ogg"
    if ext == "aac":
        return "aac"
    if ext == "mp3":
        if "320" in fn or "320kbps" in fn:
            return "mp3-320"
        if "v0" in fn or "vbr" in fn:
            return "mp3-v0"
        if "256" in fn:
            return "mp3-256"
        if "192" in fn:
            return "mp3-192"
        return "mp3"
    return ext


def text_similarity(query_words, text):
    """Simple word-overlap similarity score (0-1)."""
    text_lower = text.lower()
    if not query_words:
        return 0
    matches = sum(1 for w in query_words if w in text_lower)
    return matches / len(query_words)


def score_file(file_info, query_words):
    """Score a file for quality and relevance. Higher = better."""
    filename = file_info.get("filename", "")
    fmt = guess_format(filename)
    format_score = FORMAT_SCORES.get(fmt, 10)
    relevance = text_similarity(query_words, filename)
    size_mb = file_info.get("size", 0) / (1024 * 1024)
    # Normalize size bonus (cap at 50MB)
    size_score = min(size_mb / 50, 1.0) * 10
    return (relevance * 50) + format_score + size_score


def pick_best(responses, query):
    """Pick the best file from search responses."""
    query_words = [w.lower() for w in query.split() if len(w) > 1]
    best_file = None
    best_score = -1
    best_username = None

    for resp in responses:
        username = resp.get("username", "")
        queue_len = resp.get("queueLength", 0)
        # Penalize users with long queues
        queue_penalty = min(queue_len / 100, 1.0) * 20

        for f in resp.get("files", []):
            fn = f.get("filename", "").lower()
            # Skip non-audio files
            ext = fn.rsplit(".", 1)[-1] if "." in fn else ""
            if ext not in ("flac", "mp3", "wav", "ogg", "aac", "m4a", "alac", "wma", "opus"):
                continue
            s = score_file(f, query_words) - queue_penalty
            if s > best_score:
                best_score = s
                best_file = f
                best_username = username

    return best_file, best_username, best_score


# ── Main workflow ─────────────────────────────────────────────────────────────

def search_and_download(entry, base_url, api_key, timeout):
    """Search for a single entry and queue download. Returns status dict."""
    query = build_query(entry)
    if not query:
        return {"status": "skipped", "reason": "empty query"}

    # 1. Initiate search
    search = slskd_api("POST", "/searches", base_url, api_key, {
        "searchText": query,
        "searchTimeout": timeout * 1000,
    })
    if not search:
        return {"status": "error", "reason": "search failed"}

    search_id = search.get("id")
    if not search_id:
        return {"status": "error", "reason": "no search ID returned"}

    # 2. Poll for completion
    elapsed = 0
    while elapsed < timeout + 5:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        state = slskd_api("GET", f"/searches/{search_id}", base_url, api_key)
        if not state:
            break
        if state.get("state", "").lower() in ("completed", "timedout"):
            break
        # Also check responseCount to bail early if we have results
        if state.get("responseCount", 0) > 0 and elapsed >= min(timeout, 8):
            break

    # 3. Get responses
    responses = slskd_api("GET", f"/searches/{search_id}/responses", base_url, api_key)
    if not responses:
        slskd_api("DELETE", f"/searches/{search_id}", base_url, api_key)
        return {"status": "no_results", "reason": "no responses"}

    # 4. Pick best match
    best_file, username, score = pick_best(responses, query)
    if not best_file:
        slskd_api("DELETE", f"/searches/{search_id}", base_url, api_key)
        return {"status": "no_results", "reason": "no audio files found"}

    # 5. Queue download
    filename = best_file.get("filename", "")
    dl = slskd_api("POST", f"/transfers/downloads/{username}", base_url, api_key, [
        {
            "filename": filename,
            "size": best_file.get("size", 0),
        }
    ])

    # 6. Cleanup search
    slskd_api("DELETE", f"/searches/{search_id}", base_url, api_key)

    if dl is None:
        return {"status": "error", "reason": "download queue failed",
                "file": filename, "username": username}

    fmt = guess_format(filename)
    short_name = filename.rsplit("\\", 1)[-1] if "\\" in filename else filename.rsplit("/", 1)[-1]
    return {
        "status": "queued",
        "file": short_name,
        "username": username,
        "format": fmt,
        "score": round(score, 1),
    }


def save_results(results, entries):
    os.makedirs("results", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join("results", f"slskd_dl_{ts}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["artist", "title", "album", "status", "file", "username", "format", "score"])
        for entry, res in zip(entries, results):
            w.writerow([
                entry.get("artist", ""),
                entry.get("title", ""),
                entry.get("album", ""),
                res.get("status", ""),
                res.get("file", ""),
                res.get("username", ""),
                res.get("format", ""),
                res.get("score", ""),
            ])
    return path


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("Usage: python3 slskd_dl.py [csv_file]")
        print()
        print("Search and download music from a CSV list via slskd (Soulseek).")
        print()
        print("CSV format (auto-detected):")
        print("  With headers: artist,title,album  (album optional)")
        print("  Without headers: col1=artist, col2=title, col3=album")
        print()
        print("Options are configured interactively at startup.")
        print("Set SLSKD_URL and SLSKD_API_KEY env vars to skip prompts.")
        sys.exit(0)

    print("slskd_dl — CSV music downloader via Soulseek\n", file=sys.stderr)

    # Config
    csv_path = sys.argv[1] if len(sys.argv) > 1 else ask("CSV file path", "")
    if not csv_path or not os.path.isfile(csv_path):
        print(f"Error: file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    base_url = os.environ.get("SLSKD_URL") or ask("slskd URL", DEFAULT_URL)
    base_url = base_url.rstrip("/")
    api_key = os.environ.get("SLSKD_API_KEY") or ask("slskd API key", "")
    if not api_key:
        print("Error: API key is required", file=sys.stderr)
        sys.exit(1)

    timeout = int(ask("Search timeout (seconds)", str(SEARCH_TIMEOUT)))

    # Parse CSV
    entries = parse_csv(csv_path)
    if not entries:
        print("Error: no entries found in CSV", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Found {len(entries)} entries to process\n", file=sys.stderr)

    # Test connection
    app_info = slskd_api("GET", "/application", base_url, api_key)
    if not app_info:
        print("Error: cannot connect to slskd. Check URL and API key.", file=sys.stderr)
        sys.exit(1)
    print(f"  Connected to slskd\n", file=sys.stderr)

    # Process each entry
    results = []
    queued = 0
    failed = 0
    no_results = 0

    try:
        for i, entry in enumerate(entries):
            label = f"{entry.get('artist', '?')} - {entry.get('title', entry.get('album', '?'))}"
            print(f"  [{i+1}/{len(entries)}] {label}", end="", flush=True, file=sys.stderr)

            res = search_and_download(entry, base_url, api_key, timeout)
            results.append(res)

            status = res["status"]
            if status == "queued":
                queued += 1
                print(f" → ✓ {res['file']} ({res['format']})", file=sys.stderr)
            elif status == "no_results":
                no_results += 1
                print(f" → no results", file=sys.stderr)
            elif status == "skipped":
                print(f" → skipped", file=sys.stderr)
            else:
                failed += 1
                print(f" → ✗ {res.get('reason', 'error')}", file=sys.stderr)

    except KeyboardInterrupt:
        print("\n\n  Interrupted! Saving partial results...", file=sys.stderr)
        # Pad results for unprocessed entries
        while len(results) < len(entries):
            results.append({"status": "not_processed"})

    # Save results
    out_path = save_results(results, entries)

    # Summary
    total = len([r for r in results if r["status"] != "not_processed"])
    print(f"\n  Done: {queued} queued, {no_results} no results, {failed} failed "
          f"({total}/{len(entries)} processed)", file=sys.stderr)
    print(f"  Results saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
