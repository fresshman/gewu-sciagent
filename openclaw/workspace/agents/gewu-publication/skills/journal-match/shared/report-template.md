# Report Template — Base Design System (journal-match local copy)

Local copy of the PaperSkills base design system so the journal-match skill is
self-contained inside Gewu (the upstream LobeHub `skills/shared/` layout is not
present in this repo). Apply these CSS custom properties and base styles as the
foundation for `../assets/journal-report-template.md` and the style guide.

**Hard rule: NO Tailwind CDN.** Use only the custom properties and classes below.

## Fonts

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Crimson+Pro:wght@400;600;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
```

## CSS Custom Properties + Base Styles

```css
:root {
  /* Typography */
  --font-heading: 'Crimson Pro', Georgia, 'Times New Roman', serif;
  --font-body: 'Source Sans 3', system-ui, -apple-system, sans-serif;

  /* Palette — warm academic paper */
  --paper: #fbfaf7;
  --surface: #ffffff;
  --ink: #1c1a17;
  --text: #2d2a25;
  --muted: #6b655c;
  --border: #e4ded3;
  --accent: #8a1c1c;        /* deep crimson */
  --positive: #2f7d4f;      /* OA green text */

  /* Tier colors (from style guide) */
  --tier1: #38a169;
  --tier1-bg: rgba(56, 161, 105, 0.10);
  --tier2: #2b6cb0;
  --tier2-bg: rgba(43, 108, 176, 0.10);
  --tier3: #718096;
  --tier3-bg: rgba(113, 128, 150, 0.10);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--paper);
  color: var(--text);
  font-family: var(--font-body);
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}

.report {
  max-width: 880px;
  margin: 2.5rem auto;
  padding: 2.5rem 2.75rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.report-header { border-bottom: 2px solid var(--accent); padding-bottom: 1rem; margin-bottom: 1.5rem; }
.report-tag {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.72rem;
  color: var(--accent);
  font-weight: 600;
  margin: 0 0 0.25rem;
}
.report-title { font-family: var(--font-heading); font-size: 2rem; font-weight: 700; color: var(--ink); margin: 0.25rem 0; line-height: 1.2; }
.report-subtitle { color: var(--muted); margin: 0.25rem 0 0.75rem; }
.report-meta { font-size: 0.8rem; color: var(--muted); }
.meta-sep { margin: 0 0.4rem; }

.metrics { display: flex; gap: 1rem; margin: 1.5rem 0; flex-wrap: wrap; }
.metric-card {
  flex: 1 1 0;
  min-width: 140px;
  background: var(--paper);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1rem;
  text-align: center;
}
.metric-value { font-family: var(--font-heading); font-size: 1.6rem; font-weight: 700; color: var(--ink); }
.metric-label { font-size: 0.78rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }

.callout {
  background: var(--paper);
  border-left: 3px solid var(--accent);
  padding: 0.85rem 1.1rem;
  margin: 1.25rem 0;
  font-size: 0.92rem;
  border-radius: 0 4px 4px 0;
}

h2 { font-family: var(--font-heading); color: var(--ink); border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; margin-top: 2rem; }

.report-footer { margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid var(--border); font-size: 0.82rem; color: var(--muted); }
.report-footer p { margin: 0.3rem 0; }

.tag {
  display: inline-block;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  padding: 0.15rem 0.5rem;
  border-radius: 3px;
  background: var(--paper);
  border: 1px solid var(--border);
  color: var(--muted);
}
.tag-oa { background: #e8f5e9; color: var(--positive); border-color: #c8e6c9; }
```
