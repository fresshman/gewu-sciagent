# Subagent Prompt — Find Similar Papers

Use this prompt template when launching the Step 2 subagent. Replace placeholders with values from the manuscript profile.

---

## Prompt

```
TASK: Find journals where similar research is published and return a venue
distribution table.

MANUSCRIPT PROFILE:
- Keywords: {keywords}
- Discipline: {discipline}
- Sub-field: {sub_field}
- Methodology: {methodology}
- Language: {language}
- Scope: {scope}

INSTRUCTIONS:

1. Construct 3 keyword combinations from the profile:
   a. Broad: combine discipline + 2 general keywords
   b. Narrow: combine sub-field + 3 specific keywords
   c. Methodology-specific: combine methodology + 2 keywords

2. For each keyword combination, search Semantic Scholar:
   WebFetch: https://api.semanticscholar.org/graph/v1/paper/search?query={keywords}&limit=50&fields=title,venue,year,citationCount,externalIds
   - Extract the "venue" field from each result.
   - Discard results where venue is empty or null.

3. For each keyword combination, search OpenAlex:
   WebFetch: https://api.openalex.org/works?search={keywords}&per_page=50&sort=cited_by_count:desc&mailto=paperskills@example.com
   - Extract primary_location.source.display_name as venue.
   - Extract primary_location.source.id as source_id (for later enrichment).
   - Discard results where venue is empty or null.

4. Merge all results. Group by venue name (normalize: strip "The ", match case-insensitively).

5. For the top 15 venues by paper count, retrieve journal details from OpenAlex:
   WebFetch: https://api.openalex.org/sources?filter=display_name.search:{journal_name}&mailto=paperskills@example.com
   - Extract: h_index, works_count, cited_by_count, is_oa, country_code

6. Assign a preliminary scope match score (1-5) for each journal:
   - 5: Journal clearly publishes this discipline + methodology regularly
   - 4: Close match, minor scope differences
   - 3: Related but broader venue
   - 2: Tangentially related
   - 1: Poor match

7. If the manuscript language is not English, also search for journals
   in that language by adding language-specific keywords.

OUTPUT FORMAT (return exactly this table):

| Rank | Journal | Papers Found | Avg Citations | H-Index | OA? | Country | Scope Match (1-5) | Source ID |
|------|---------|-------------|---------------|---------|-----|---------|-------------------|-----------|
| 1    | ...     | ...         | ...           | ...     | ... | ...     | ...               | ...       |

Sort by: Scope Match (desc), then Papers Found (desc).

If fewer than 5 journals are found, note this and suggest broadening the search.
```
