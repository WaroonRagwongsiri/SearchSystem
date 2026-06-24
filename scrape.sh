#!/bin/bash

# Folder name
OUT="all_documents"
AUTHORIZATION="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJodHRwOi8vc2NoZW1hcy54bWxzb2FwLm9yZy93cy8yMDA1LzA1L2lkZW50aXR5L2NsYWltcy9uYW1laWRlbnRpZmllciI6IjFhMjkwMmI3LTA5NDAtNGVhZS1hOTUxLTMyOTRlOWMxODc4ZCIsInN1YiI6IjExMDIwMDM4NDg1MTQiLCJqdGkiOiJhZDAwY2NmNC03NTBmLTRmZGMtOWVhOC1jNTdjMWQ4MWFhMmIiLCJleHAiOjE3ODQzNjE4NTgsImlzcyI6IllvdXJJc3N1ZXIiLCJhdWQiOiJZb3VyQXVkaWVuY2UifQ.vq5NP7BXPurdufiaWFbdLDW7riIL6RNyaLYdF35oQpI"

# archives.nat.go.th serves an incomplete TLS chain (missing its Thawte intermediate),
# so curl can't verify the server. Ship the intermediate and trust it as an anchor —
# keeps verification ON (no --insecure). Re-fetch from cacerts.thawte.com if rotated.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACERT="$SCRIPT_DIR/certs/thawte-intermediate.pem"

# Create the target directory if it doesn't exist
mkdir -p "$OUT"

# Define the total number of pages to scrape
TOTAL_PAGES=7481

echo "Starting scrape for $TOTAL_PAGES pages (resumable: existing pages are skipped)..."

for (( i=1; i<=TOTAL_PAGES; i++ ))
do
	# Format the page number to 4 digits (e.g., 0001, 0002, 0010)
	PAGE_NUM=$(printf "%04d" $i)
	FILE="$OUT/page_${PAGE_NUM}.json"

	# Resume: a present, non-empty final file means this page was already fetched.
	[ -s "$FILE" ] && { echo "skip   page $i/$TOTAL_PAGES (have $FILE)"; continue; }

	echo "fetch  page $i/$TOTAL_PAGES -> $FILE"

	# Fetch to a .part file and move into place only on success, so a killed run
	# never leaves a half-written final file that resume would wrongly skip.
	# ponytail: known ceiling — if the API answers HTTP 200 with an error body (e.g.
	# auth token expired), that body is saved as if valid and skipped next run.
	# Add `--fail` to curl if this API signals errors via HTTP status.
	curl -s --cacert "$CACERT" 'https://archives.nat.go.th/api/SearchableArchivesDocumentEndpoint/SearchSearchableArchivesDocumentWithPagination' \
	-X POST \
	-H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0' \
	-H 'Accept: application/json' \
	-H 'Accept-Language: en-US,en;q=0.9' \
	-H 'Accept-Encoding: gzip, deflate, br, zstd' \
	-H 'Referer: https://archives.nat.go.th/Searching/DiscoveryPage' \
	-H 'Content-Type: application/json' \
	-H "Authorization: Bearer $AUTHORIZATION" \
	-H 'Origin: https://archives.nat.go.th' \
	-H 'Sec-GPC: 1' \
	-H 'Connection: keep-alive' \
	-H 'Sec-Fetch-Dest: empty' \
	-H 'Sec-Fetch-Mode: cors' \
	-H 'Sec-Fetch-Site: same-origin' \
	-H 'Priority: u=0' \
	-H 'TE: trailers' \
	--data-raw '{"search":"","sortOption":"fullContentCode","sortDirection":"asc","pageNumber":'$i',"pageSize":100}' \
	-o "$FILE.part" && mv "$FILE.part" "$FILE" || { echo "  page $i failed; will retry next run"; rm -f "$FILE.part"; }

	# Optional: Add a 0.3-second delay to avoid rate-limiting or overwhelming the server
	sleep 0.3
done

echo "Scraping complete! All files saved in the '$OUT' folder."
