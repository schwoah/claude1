#!/usr/bin/env bash
#
# Scrape Discogs for 2025-2026 vinyl releases with high want/own ratio.
# Filters: at least 30 wants. Sorted by want/have ratio descending.
#
# Requirements: curl, jq (both widely available)
#
# Usage:
#   ./discogs_scraper.sh
#   ./discogs_scraper.sh --token YOUR_DISCOGS_TOKEN   # higher rate limits
#   ./discogs_scraper.sh --min-wants 50
#   ./discogs_scraper.sh --skip-details               # faster, no price data
#   ./discogs_scraper.sh --format csv
#   ./discogs_scraper.sh --format json

set -euo pipefail

# Defaults
TOKEN=""
MIN_WANTS=30
MAX_PAGES=10
YEARS="2025 2026"
FORMAT="table"
SKIP_DETAILS=false
USER_AGENT="DiscogsWantScraper/1.0 +https://github.com/schwoah/claude1"
RESULTS_FILE=$(mktemp)
DETAIL_FILE=$(mktemp)

trap 'rm -f "$RESULTS_FILE" "$DETAIL_FILE"' EXIT

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --token)     TOKEN="$2"; shift 2 ;;
        --min-wants) MIN_WANTS="$2"; shift 2 ;;
        --max-pages) MAX_PAGES="$2"; shift 2 ;;
        --years)     YEARS="$2"; shift 2 ;;
        --format)    FORMAT="$2"; shift 2 ;;
        --skip-details) SKIP_DETAILS=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--token TOKEN] [--min-wants N] [--max-pages N] [--years \"2025 2026\"] [--format table|csv|json] [--skip-details]"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Rate limit delay (seconds)
if [[ -n "$TOKEN" ]]; then
    DELAY=1
else
    DELAY=3
fi

# Build auth header
auth_header() {
    if [[ -n "$TOKEN" ]]; then
        echo "-H" "Authorization: Discogs token=$TOKEN"
    fi
}

# API request with retries
api_get() {
    local url="$1"
    local attempt
    for attempt in 1 2 3; do
        local response
        response=$(curl -s -w "\n%{http_code}" \
            -H "User-Agent: $USER_AGENT" \
            -H "Accept: application/json" \
            $(auth_header) \
            "$url" 2>/dev/null) || true

        local http_code body
        http_code=$(echo "$response" | tail -1)
        body=$(echo "$response" | sed '$d')

        if [[ "$http_code" == "200" ]]; then
            echo "$body"
            sleep "$DELAY"
            return 0
        elif [[ "$http_code" == "429" ]]; then
            local wait=$((2 ** (attempt + 1)))
            echo "  Rate limited, waiting ${wait}s..." >&2
            sleep "$wait"
        else
            echo "  HTTP $http_code for $url" >&2
            return 1
        fi
    done
    return 1
}

# URL encode
urlencode() {
    local string="$1"
    echo "$string" | jq -sRr @uri
}

echo "Searching Discogs for vinyl releases with >= $MIN_WANTS wants..." >&2
echo "" >&2

# Phase 1: Search
> "$RESULTS_FILE"

for year in $YEARS; do
    echo "[$year]" >&2
    for page in $(seq 1 "$MAX_PAGES"); do
        echo "  Fetching page $page/$MAX_PAGES..." >&2

        url="https://api.discogs.com/database/search?type=release&year=${year}&format=Vinyl&sort=want&sort_order=desc&per_page=100&page=${page}"
        data=$(api_get "$url") || { echo "  Failed to fetch page $page" >&2; break; }

        # Extract results and append to file
        count=$(echo "$data" | jq '.results | length')
        if [[ "$count" == "0" ]]; then
            echo "  No more results" >&2
            break
        fi

        echo "$data" | jq -c '.results[]' >> "$RESULTS_FILE"

        # Check if last result's wants are below threshold
        last_want=$(echo "$data" | jq '.results[-1].community.want // 0')
        if [[ "$last_want" -lt "$MIN_WANTS" ]]; then
            echo "  Wants dropped below $MIN_WANTS, stopping" >&2
            break
        fi

        # Check pagination
        total_pages=$(echo "$data" | jq '.pagination.pages // 0')
        if [[ "$page" -ge "$total_pages" ]]; then
            break
        fi
    done
done

# Filter by minimum wants
total_before=$(wc -l < "$RESULTS_FILE")
filtered_file=$(mktemp)
trap 'rm -f "$RESULTS_FILE" "$DETAIL_FILE" "$filtered_file"' EXIT

jq -c "select(.community.want >= $MIN_WANTS)" "$RESULTS_FILE" > "$filtered_file"
total_after=$(wc -l < "$filtered_file")

echo "" >&2
echo "$total_after releases with >= $MIN_WANTS wants (from $total_before total)" >&2

# Phase 2: Fetch details for price data
> "$DETAIL_FILE"
line_num=0
total_lines=$total_after

while IFS= read -r line; do
    line_num=$((line_num + 1))
    id=$(echo "$line" | jq -r '.id')
    title=$(echo "$line" | jq -r '.title // "Unknown"')
    genre=$(echo "$line" | jq -r '(.genre // .style // ["Unknown"]) | join(", ")')
    want=$(echo "$line" | jq -r '.community.want // 0')
    have=$(echo "$line" | jq -r '.community.have // 0')

    lowest_price="null"
    num_for_sale="null"

    if [[ "$SKIP_DETAILS" == false ]]; then
        short_title=$(echo "$title" | cut -c1-50)
        echo "  Fetching details $line_num/$total_lines: $short_title..." >&2

        details=$(api_get "https://api.discogs.com/releases/$id") || true
        if [[ -n "$details" ]]; then
            lowest_price=$(echo "$details" | jq '.lowest_price // null')
            num_for_sale=$(echo "$details" | jq '.num_for_sale // null')
            # More accurate community stats
            detail_want=$(echo "$details" | jq '.community.want // null')
            detail_have=$(echo "$details" | jq '.community.have // null')
            [[ "$detail_want" != "null" ]] && want="$detail_want"
            [[ "$detail_have" != "null" ]] && have="$detail_have"
            # Better genre info
            detail_genre=$(echo "$details" | jq -r '((.genres // []) + (.styles // [])) | join(", ")')
            [[ -n "$detail_genre" ]] && genre="$detail_genre"
        fi
    fi

    # Compute ratio
    if [[ "$have" -gt 0 ]]; then
        ratio=$(echo "scale=1; $want / $have" | bc)
    else
        ratio="inf"
    fi

    # Store as JSON
    jq -n -c \
        --arg title "$title" \
        --arg genre "$genre" \
        --argjson want "$want" \
        --argjson have "$have" \
        --arg ratio "$ratio" \
        --argjson lowest_price "$lowest_price" \
        --argjson num_for_sale "$num_for_sale" \
        --arg url "https://www.discogs.com/release/$id" \
        '{title: $title, genre: $genre, want: $want, have: $have, ratio: $ratio,
          lowest_price: $lowest_price, num_for_sale: $num_for_sale, url: $url}' \
        >> "$DETAIL_FILE"

done < "$filtered_file"

# Sort by ratio descending (inf first, then numeric desc)
sorted_file=$(mktemp)
trap 'rm -f "$RESULTS_FILE" "$DETAIL_FILE" "$filtered_file" "$sorted_file"' EXIT

jq -s 'sort_by(if .ratio == "inf" then -999999 else -(.ratio | tonumber) end)' "$DETAIL_FILE" > "$sorted_file"

# Output
case "$FORMAT" in
    json)
        cat "$sorted_file"
        ;;
    csv)
        echo "Title,Genre,Want,Have,Ratio,Lowest Price,For Sale,URL"
        jq -r '.[] | [.title, .genre, .want, .have, .ratio,
            (if .lowest_price then ("$" + (.lowest_price | tostring)) else "N/A" end),
            (.num_for_sale // "N/A" | tostring), .url] | @csv' "$sorted_file"
        ;;
    table|*)
        printf "\n%-45s %-25s %5s %5s %7s %8s %5s  %s\n" \
            "Title" "Genre" "Want" "Have" "Ratio" "Price" "Sale" "URL"
        printf '%.0s=' {1..130}
        echo ""
        jq -r '.[] | [.title, .genre, (.want|tostring), (.have|tostring), .ratio,
            (if .lowest_price then ("$" + (.lowest_price | tostring)) else "N/A" end),
            (.num_for_sale // "N/A" | tostring), .url] | @tsv' "$sorted_file" |
        while IFS=$'\t' read -r title genre want have ratio price sale url; do
            # Truncate long fields
            [[ ${#title} -gt 45 ]] && title="${title:0:43}.."
            [[ ${#genre} -gt 25 ]] && genre="${genre:0:23}.."
            printf "%-45s %-25s %5s %5s %7s %8s %5s  %s\n" \
                "$title" "$genre" "$want" "$have" "$ratio" "$price" "$sale" "$url"
        done
        printf '%.0s=' {1..130}
        echo ""
        total=$(jq 'length' "$sorted_file")
        echo "Total: $total releases"
        ;;
esac
