# Journal Match Style Guide

Guidelines for the journal recommendation report output. Follows PapervizAgent's Stylist Agent pattern — preserves semantic content while applying academic presentation standards.

## Tone and Voice

- **Objective and advisory**: present recommendations as data-driven suggestions, not directives.
- **Academic register**: formal but accessible. Avoid marketing language ("top-tier", "prestigious").
- **Evidence-based**: every recommendation must cite the data that supports it (similar papers found, h-index, scope alignment).

## Report Structure

### Tier Cards
Each journal recommendation card follows this structure:

```html
<div class="journal-card tier-{1|2|3}">
  <div class="journal-header">
    <h3><a href="{homepage_url}">{Journal Name}</a></h3>
    <span class="badge badge-tier-{1|2|3}">Tier {N}</span>
    <span class="badge badge-oa" data-oa="{yes|no}">{OA Status}</span>
  </div>
  <div class="journal-metrics">
    <span>Scope Match: {score}/5</span>
    <span>H-Index: {value}</span>
    <span>Works: {count}</span>
  </div>
  <p class="scope-reasoning">{One-line reasoning for scope match score}</p>
  <p class="similar-papers">Similar papers: {count} in last 3 years</p>
</div>
```

### Tier Color Coding

| Tier | Badge Color | Background |
|------|-------------|------------|
| Tier 1 — Best Match | Green `#38a169` | `rgba(56, 161, 105, 0.1)` |
| Tier 2 — Good Alternative | Blue `#2b6cb0` | `rgba(43, 108, 176, 0.1)` |
| Tier 3 — Specialized/Niche | Gray `#718096` | `rgba(113, 128, 150, 0.1)` |

### Scope Match Visualization

Display scope scores as a horizontal bar or dot indicator:
- Score 5: filled bar, green
- Score 4: mostly filled, green-blue
- Score 3: half filled, blue
- Score 2: partially filled, gray
- Score 1: minimal fill, gray

### Few-Shot Context Section

When the Retriever step found similar papers, include a section showing:

```html
<details>
  <summary>Similar Published Papers ({count} found)</summary>
  <table>
    <thead><tr><th>Title</th><th>Venue</th><th>Year</th><th>Citations</th></tr></thead>
    <tbody>
      <!-- Top 5-10 similar papers from the Retriever step -->
    </tbody>
  </table>
  <p class="methodology-note">
    Journal recommendations were guided by where these similar papers were published.
  </p>
</details>
```

## Design System

Follow `skills/shared/report-template.md` for base styling:
- Crimson Pro font
- CSS custom properties
- Academic book aesthetic
- NO Tailwind CDN
