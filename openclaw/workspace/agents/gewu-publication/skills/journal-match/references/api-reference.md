# API Reference — Journal Match

Endpoint details for the APIs used in the journal-match skill. All requests use the WebFetch tool. Include `mailto=paperskills@example.com` on all OpenAlex requests for polite pool access.

---

## Semantic Scholar — Paper Search

Search for papers matching keyword combinations.

```
GET https://api.semanticscholar.org/graph/v1/paper/search
  ?query={keywords}
  &limit=50
  &fields=title,venue,year,citationCount,externalIds
```

**Parameters:**
- `query`: URL-encoded keyword string (combine 3-5 terms)
- `limit`: max 100 per request
- `fields`: comma-separated list of fields to return

**Response fields of interest:**
- `venue` — journal or conference name
- `year` — publication year
- `citationCount` — total citations
- `externalIds.DOI` — DOI if available

**Usage:** Run 3 keyword combinations (e.g., broad, narrow, methodology-specific). Extract venue from each result and tally frequency.

---

## OpenAlex — Works Search

Search for works (papers) and extract venue distribution.

```
GET https://api.openalex.org/works
  ?search={keywords}
  &per_page=50
  &sort=cited_by_count:desc
  &mailto=paperskills@example.com
```

**Parameters:**
- `search`: free-text search across title, abstract, fulltext
- `per_page`: max 200
- `sort`: `cited_by_count:desc` for most-cited first, `publication_date:desc` for newest first

**Response fields of interest:**
- `primary_location.source.display_name` — journal name
- `primary_location.source.id` — OpenAlex source ID (for enrichment)
- `cited_by_count` — citation count
- `publication_year` — year

**Usage:** Group results by venue, count papers per venue, calculate average citations per venue.

---

## OpenAlex — Sources (Journal Details)

Retrieve metadata for a specific journal by name search or by ID.

### By name search:
```
GET https://api.openalex.org/sources
  ?filter=display_name.search:{journal_name}
  &mailto=paperskills@example.com
```

### By OpenAlex ID:
```
GET https://api.openalex.org/sources/{source_id}
  ?mailto=paperskills@example.com
```

**Response fields of interest:**
- `display_name` — full journal name
- `h_index` — journal h-index
- `works_count` — total papers published
- `cited_by_count` — total citations received
- `is_oa` — whether journal is open access
- `homepage_url` — journal website
- `issn` — array of ISSNs
- `type` — "journal", "repository", "conference", etc.
- `country_code` — ISO country code

---

## CrossRef — Journals

Look up journal by ISSN for publication frequency and subject coverage.

```
GET https://api.crossref.org/journals/{issn}
```

**Parameters:**
- `{issn}` — print or electronic ISSN (e.g., `0140-6736`)

**Response fields of interest:**
- `title` — journal title
- `publisher` — publisher name
- `subjects` — array of subject classifications
- `counts.total-dois` — total DOIs registered
- `coverage.references-current` — reference coverage percentage

**Fallback use:** When a journal is not found in OpenAlex, attempt CrossRef lookup by ISSN.

---

## Rate Limits and Error Handling

| API | Rate Limit | Action on 429 |
|---|---|---|
| Semantic Scholar | 100 req/5 min (unauthenticated) | Wait 5 seconds, retry once |
| OpenAlex | Polite pool (with mailto) ~10 req/sec | Wait 1 second, retry |
| CrossRef | ~50 req/sec (polite pool with mailto) | Wait 1 second, retry |

- If an API returns a 404 for a journal/source, mark as "not found" and proceed with remaining APIs.
- If an API is entirely down (5xx), proceed with data from other APIs and note the gap in the report.
