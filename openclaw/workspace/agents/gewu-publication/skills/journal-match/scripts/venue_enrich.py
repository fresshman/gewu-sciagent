#!/usr/bin/env python3
"""Enrich journal names with metadata from OpenAlex.

Usage:
    python venue_enrich.py --journals journals.json [--mailto paperskills@example.com]

Input:
    JSON file containing an array of journal name strings.
    Example: ["Nature", "Science", "PLOS ONE"]

Output:
    JSON array on stdout with enriched journal objects:
    [
        {
            "name": "Nature",
            "h_index": 1078,
            "works_count": 412345,
            "cited_by_count": 52345678,
            "is_oa": false,
            "homepage_url": "https://www.nature.com",
            "issn": ["0028-0836", "1476-4687"]
        },
        ...
    ]

Errors:
    Descriptive messages on stderr for journals not found or API failures.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def fetch_json(url: str) -> dict:
    """Fetch a URL and return parsed JSON. Raises on HTTP errors."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "PaperSkills/1.0 (venue_enrich.py)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(
                f"[WARN] Rate limited on {url}. Waiting 5 seconds...",
                file=sys.stderr,
            )
            time.sleep(5)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        raise


def enrich_journal(name: str, mailto: str) -> dict | None:
    """Look up a single journal in OpenAlex by display name.

    Returns an enriched dict or None if not found.
    """
    encoded_name = urllib.request.quote(name)
    url = (
        f"https://api.openalex.org/sources"
        f"?filter=display_name.search:{encoded_name}"
        f"&mailto={mailto}"
    )

    try:
        data = fetch_json(url)
    except Exception as e:
        print(
            f"[ERROR] API request failed for '{name}': {e}",
            file=sys.stderr,
        )
        return None

    results = data.get("results", [])
    if not results:
        print(
            f"[WARN] Journal not found in OpenAlex: '{name}'",
            file=sys.stderr,
        )
        return None

    # Pick the best match: prefer exact name match, otherwise first result
    source = results[0]
    for r in results:
        if r.get("display_name", "").lower() == name.lower():
            source = r
            break

    return {
        "name": source.get("display_name", name),
        "h_index": source.get("h_index"),
        "works_count": source.get("works_count"),
        "cited_by_count": source.get("cited_by_count"),
        "is_oa": source.get("is_oa"),
        "homepage_url": source.get("homepage_url"),
        "issn": source.get("issn", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich journal names with OpenAlex metadata.",
        epilog=(
            "Example: python venue_enrich.py "
            "--journals journals.json --mailto paperskills@example.com"
        ),
    )
    parser.add_argument(
        "--journals",
        required=True,
        help="Path to JSON file containing an array of journal name strings.",
    )
    parser.add_argument(
        "--mailto",
        default="paperskills@example.com",
        help=("Email for OpenAlex polite pool access (default: paperskills@example.com)."),
    )
    args = parser.parse_args()

    # Load journal names
    try:
        with open(args.journals, encoding="utf-8") as f:
            journal_names = json.load(f)
    except FileNotFoundError:
        print(
            f"[ERROR] File not found: {args.journals}",
            file=sys.stderr,
        )
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(
            f"[ERROR] Invalid JSON in {args.journals}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not isinstance(journal_names, list):
        print(
            "[ERROR] Expected a JSON array of journal name strings.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not journal_names:
        print(
            "[WARN] Empty journal list provided. Nothing to enrich.",
            file=sys.stderr,
        )
        print("[]")
        return

    enriched = []
    not_found_count = 0

    for i, name in enumerate(journal_names):
        if not isinstance(name, str) or not name.strip():
            print(
                f"[WARN] Skipping invalid entry at index {i}: {name!r}",
                file=sys.stderr,
            )
            continue

        result = enrich_journal(name.strip(), args.mailto)
        if result is not None:
            enriched.append(result)
        else:
            not_found_count += 1

        # Polite delay between requests
        if i < len(journal_names) - 1:
            time.sleep(0.2)

    print(json.dumps(enriched, indent=2, ensure_ascii=False))

    # Summary on stderr
    total = len(journal_names)
    found = len(enriched)
    print(
        f"\n[INFO] Enrichment complete: {found}/{total} journals found"
        f" ({not_found_count} not found).",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
