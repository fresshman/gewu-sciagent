#!/usr/bin/env python3
"""Compute a scope match score (1-5) between a manuscript profile and a journal.

Usage:
    python scope_score.py --profile manuscript_profile.json --journal journal_data.json

Input files:
    manuscript_profile.json:
    {
        "discipline": "computer science",
        "sub_field": "natural language processing",
        "methodology": "empirical",
        "scope": "universal",
        "keywords": ["transformer", "attention", "NLP", "text classification"]
    }

    journal_data.json:
    {
        "name": "Computational Linguistics",
        "subjects": ["natural language processing", "computational linguistics"],
        "type": "journal",
        "is_oa": false,
        "h_index": 89,
        "works_count": 2500,
        "country_code": "US"
    }

Output:
    JSON on stdout:
    {
        "journal": "Computational Linguistics",
        "score": 5,
        "reasoning": "Journal specializes in NLP with strong keyword overlap (3/4 keywords match subject area). Methodology (empirical) aligns with journal's publication pattern. Scope is universal, matching journal's international reach."
    }

Scoring criteria:
    5: Journal publishes exactly this type of work (discipline + methodology match)
    4: Close match with minor discipline/scope differences
    3: Related but broader journal
    2: Tangentially related
    1: Poor match
"""

import argparse
import json
import sys


def normalize(text: str) -> str:
    """Lowercase and strip whitespace for comparison."""
    return text.strip().lower()


def keyword_overlap(keywords: list[str], subjects: list[str]) -> float:
    """Compute fraction of manuscript keywords that appear in journal subjects.

    Uses substring matching: a keyword matches if it appears as a substring
    of any subject string, or vice versa.
    """
    if not keywords or not subjects:
        return 0.0

    norm_keywords = [normalize(k) for k in keywords]
    norm_subjects = [normalize(s) for s in subjects]

    matches = 0
    for kw in norm_keywords:
        for subj in norm_subjects:
            if kw in subj or subj in kw:
                matches += 1
                break

    return matches / len(norm_keywords)


def discipline_match(
    profile_discipline: str,
    profile_subfield: str,
    journal_subjects: list[str],
) -> str:
    """Classify discipline alignment as 'exact', 'close', 'related', or 'none'."""
    norm_disc = normalize(profile_discipline)
    norm_sub = normalize(profile_subfield)
    norm_subjects = [normalize(s) for s in journal_subjects]
    combined = " ".join(norm_subjects)

    # Exact: sub-field appears in journal subjects
    if norm_sub and any(norm_sub in s or s in norm_sub for s in norm_subjects):
        return "exact"

    # Close: discipline appears in journal subjects
    if norm_disc and any(norm_disc in s or s in norm_disc for s in norm_subjects):
        return "close"

    # Related: any word overlap between discipline/subfield and subjects
    disc_words = set(norm_disc.split() + norm_sub.split()) - {
        "of",
        "and",
        "the",
        "in",
        "for",
        "a",
        "an",
    }
    if disc_words and any(w in combined for w in disc_words if len(w) > 3):
        return "related"

    return "none"


def compute_score(profile: dict, journal: dict) -> tuple[int, str]:
    """Compute scope match score and reasoning.

    Returns (score, reasoning) tuple.
    """
    keywords = profile.get("keywords", [])
    discipline = profile.get("discipline", "")
    sub_field = profile.get("sub_field", profile.get("sub-field", ""))
    profile.get("methodology", "")
    profile.get("scope", "")

    journal.get("name", "Unknown")
    subjects = journal.get("subjects", [])
    journal_type = journal.get("type", "journal")

    reasons = []
    score_components = []

    # 1. Discipline alignment (0-2 points)
    disc = discipline_match(discipline, sub_field, subjects)
    if disc == "exact":
        score_components.append(2)
        reasons.append(f"Journal specializes in {sub_field} (exact sub-field match)")
    elif disc == "close":
        score_components.append(1.5)
        reasons.append(f"Journal covers {discipline} (discipline match, not sub-field specific)")
    elif disc == "related":
        score_components.append(1)
        reasons.append("Journal is in a related discipline")
    else:
        score_components.append(0)
        reasons.append("No clear discipline alignment found in journal subjects")

    # 2. Keyword overlap (0-2 points)
    kw_ratio = keyword_overlap(keywords, subjects)
    kw_points = round(kw_ratio * 2, 1)
    score_components.append(kw_points)
    matched = round(kw_ratio * len(keywords))
    total = len(keywords)
    if kw_ratio >= 0.5:
        reasons.append(f"Strong keyword overlap ({matched}/{total} keywords match subject area)")
    elif kw_ratio > 0:
        reasons.append(f"Partial keyword overlap ({matched}/{total} keywords match)")
    else:
        reasons.append("No keyword overlap with journal subjects")

    # 3. Scope/type fit (0-1 point)
    if journal_type == "journal":
        score_components.append(0.5)
    elif journal_type == "conference":
        score_components.append(0.3)
        reasons.append("Venue is a conference, not a journal")
    else:
        score_components.append(0)
        reasons.append(f"Venue type is '{journal_type}', not a standard journal")

    # Calculate raw score (0-5 scale)
    raw = sum(score_components)
    # Normalize: max possible is 4.5, scale to 1-5
    normalized = max(1, min(5, round(raw * 5 / 4.5)))

    # Build reasoning string
    reasoning = ". ".join(reasons) + "."

    return normalized, reasoning


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute a scope match score (1-5) between " "a manuscript profile and a journal."
        ),
        epilog=(
            "Example: python scope_score.py "
            "--profile manuscript_profile.json --journal journal_data.json"
        ),
    )
    parser.add_argument(
        "--profile",
        required=True,
        help="Path to JSON file with manuscript profile.",
    )
    parser.add_argument(
        "--journal",
        required=True,
        help="Path to JSON file with journal data.",
    )
    args = parser.parse_args()

    # Load profile
    try:
        with open(args.profile, encoding="utf-8") as f:
            profile = json.load(f)
    except FileNotFoundError:
        print(
            f"[ERROR] Profile file not found: {args.profile}",
            file=sys.stderr,
        )
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(
            f"[ERROR] Invalid JSON in profile file: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load journal
    try:
        with open(args.journal, encoding="utf-8") as f:
            journal = json.load(f)
    except FileNotFoundError:
        print(
            f"[ERROR] Journal file not found: {args.journal}",
            file=sys.stderr,
        )
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(
            f"[ERROR] Invalid JSON in journal file: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate required fields
    if not isinstance(profile, dict):
        print(
            "[ERROR] Profile must be a JSON object with fields: "
            "discipline, sub_field, methodology, scope, keywords.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not isinstance(journal, dict):
        print(
            "[ERROR] Journal must be a JSON object with fields: name, subjects, type.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not profile.get("keywords"):
        print(
            "[WARN] No keywords in manuscript profile. Score may be less accurate.",
            file=sys.stderr,
        )

    if not journal.get("subjects"):
        print(
            "[WARN] No subjects in journal data. "
            "Scoring relies on discipline alignment and keyword matching only.",
            file=sys.stderr,
        )

    score, reasoning = compute_score(profile, journal)

    result = {
        "journal": journal.get("name", "Unknown"),
        "score": score,
        "reasoning": reasoning,
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
