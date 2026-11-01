#!/usr/bin/env python3
"""Export a sanitized public recipe catalog from the canonical Markdown note."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

PUBLIC_CATEGORIES = {
    "Cooking Reference",
    "Sauces & Dressings",
    "Mains",
    "Bowls & Salads",
    "Sides & Components",
    "Smoothies",
    "Meal Plans",
}
EXCLUDED_TITLES = {"Recipe Name"}
PRIVATE_PATTERNS = [
    ("absolute home path", re.compile(r"/home/[A-Za-z0-9._-]+/")),
    ("credential-like assignment", re.compile(r"(?i)(?:token|api[_-]?key|password|secret)[\"']?\s*[:=]\s*[\"']?[^\s,\"']{8,}")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
]
URL_RE = re.compile(r"https?://[^\s)>]+")
HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
NUMBERED_RE = re.compile(r"^\d+[.)]\s+(.+)$")
BULLET_RE = re.compile(r"^-\s+(?:\[[ xX]\]\s*)?(.+)$")
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z &/()-]{1,40}):\s*(.*)$")


def canonicalize_url(value: str) -> str:
    value = value.rstrip(".,")
    parsed = urlparse(value)
    host = parsed.netloc.casefold().removeprefix("www.")
    if any(domain in host for domain in ("instagram.com", "tiktok.com", "youtube.com", "youtu.be")):
        value = parsed._replace(query="", fragment="").geturl().rstrip("/") + "/"
    return value


def clean_text(value: str) -> str:
    value = value.strip()
    value = URL_RE.sub(lambda match: canonicalize_url(match.group(0)), value)
    value = re.sub(r"\[\[([^]|]+)(?:\|([^]]+))?\]\]", lambda m: m.group(2) or m.group(1), value)
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    return value.strip()


def slugify(value: str) -> str:
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "recipe"


def platform_for(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).netloc.casefold().removeprefix("www.")
    if "instagram.com" in host:
        return "instagram"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "tiktok.com" in host:
        return "tiktok"
    return "web"


def parse_source(line: str) -> dict | None:
    raw = clean_text(line.removeprefix("Source:").strip())
    match = URL_RE.search(raw)
    url = match.group(0).rstrip(".,") if match else None
    label = raw.replace(match.group(0), "").strip(" —–-:") if match else raw
    # Non-URL source labels are often private cross-note references rather than
    # public provenance. Do not publish them.
    if not url:
        return None
    return {"label": label or "Original source", "url": url, "platform": platform_for(url)}


def split_entries(markdown: str) -> list[tuple[str, str, list[str]]]:
    entries: list[tuple[str, str, list[str]]] = []
    category: str | None = None
    title: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal body
        is_staged = any("status: external recipe to extract." in clean_text(line).casefold() for line in body)
        if category in PUBLIC_CATEGORIES and title and title not in EXCLUDED_TITLES and not is_staged:
            entries.append((category, title, body[:]))
        body = []

    for raw in markdown.splitlines():
        match = HEADING_RE.match(raw)
        if match and len(match.group(1)) == 2:
            flush()
            category = clean_text(match.group(2))
            title = None
        elif match and len(match.group(1)) == 3:
            flush()
            title = clean_text(match.group(2))
        elif title:
            body.append(raw.rstrip())
    flush()
    return entries


def parse_entry(category: str, title: str, body: list[str]) -> dict:
    source = None
    ingredients: list[dict] = []
    steps: list[str] = []
    notes: list[str] = []
    use_with: list[str] = []
    meta: list[str] = []
    reference: list[str] = []
    section = "intro"
    ingredient_group = "Main"

    for raw in body:
        line = clean_text(raw)
        if not line or line == "---":
            continue
        lower = line.casefold()
        if lower == "ingredients:":
            section = "ingredients"
            continue
        if lower in {"steps:", "instructions:", "method:"}:
            section = "steps"
            continue
        if lower == "notes:":
            section = "notes"
            continue
        if lower == "use with:":
            section = "use"
            continue
        if line.startswith("Source:") and source is None:
            source = parse_source(line)
            continue

        numbered = NUMBERED_RE.match(line)
        bullet = BULLET_RE.match(line)
        field = FIELD_RE.match(line)

        if section == "ingredients":
            if field and not bullet and not numbered and not field.group(2):
                ingredient_group = clean_text(field.group(1))
            elif bullet:
                ingredients.append({"group": ingredient_group, "text": clean_text(bullet.group(1))})
            else:
                ingredients.append({"group": ingredient_group, "text": line})
        elif section == "steps":
            if numbered:
                steps.append(clean_text(numbered.group(1)))
            elif bullet:
                steps.append(clean_text(bullet.group(1)))
            else:
                steps.append(line)
        elif section == "notes":
            notes.append(clean_text((bullet or numbered).group(1)) if (bullet or numbered) else line)
        elif section == "use":
            use_with.append(clean_text(bullet.group(1)) if bullet else line)
        elif category == "Cooking Reference":
            reference.append(clean_text((bullet or numbered).group(1)) if (bullet or numbered) else line)
        elif bullet:
            reference.append(clean_text(bullet.group(1)))
        else:
            meta.append(line)

    # Promote recognizable metadata and retain source-provided claims verbatim.
    servings = None
    nutrition: list[str] = []
    for item in meta[:]:
        if re.match(r"(?i)^makes\s*:", item):
            servings = item.split(":", 1)[1].strip()
        if re.search(r"(?i)\b(?:calories?|protein|fiber|carbohydrates?|fat)\b", item):
            nutrition.append(item)

    if category == "Cooking Reference":
        status = "reference"
    elif ingredients and steps:
        status = "complete"
    elif ingredients:
        status = "ingredients-only"
    elif steps or reference:
        status = "method-only"
    else:
        status = "limited"

    missing_quantity = bool(ingredients) and any(
        not re.search(r"(?:\d|[¼½¾⅓⅔⅛⅜⅝⅞]|\b(?:pinch|dash|to taste|as needed|handful|whole|half)\b)", item["text"], re.I)
        for item in ingredients
    )
    badges = [status]
    if missing_quantity:
        badges.append("some quantities missing")
    if source and source.get("platform") in {"instagram", "youtube", "tiktok"}:
        badges.append("source video")

    recipe = {
        "id": slugify(title),
        "title": title,
        "category": category,
        "source": source,
        "servings": servings,
        "ingredients": ingredients,
        "steps": steps,
        "notes": notes,
        "useWith": use_with,
        "meta": meta,
        "nutrition": nutrition,
        "reference": reference,
        "status": status,
        "badges": badges,
    }
    recipe["searchText"] = " ".join(
        [title, category]
        + [x["text"] for x in ingredients]
        + steps
        + notes
        + use_with
        + meta
        + reference
    ).casefold()
    return recipe


def unique_ids(recipes: list[dict]) -> None:
    seen: dict[str, int] = {}
    for recipe in recipes:
        base = recipe["id"]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            recipe["id"] = f"{base}-{seen[base]}"


def sanitize(payload: str) -> None:
    failures = []
    for name, pattern in PRIVATE_PATTERNS:
        if pattern.search(payload):
            failures.append(name)
    if "[[" in payload or "]]" in payload:
        failures.append("Obsidian wikilink")
    if failures:
        raise ValueError("Public export rejected: " + ", ".join(sorted(set(failures))))


def build_catalog(source: Path) -> dict:
    markdown = source.read_text(encoding="utf-8")
    recipes = [parse_entry(*entry) for entry in split_entries(markdown)]
    unique_ids(recipes)
    recipes.sort(key=lambda item: (item["category"], item["title"].casefold()))
    source_hash = hashlib.sha256(markdown.encode()).hexdigest()[:12]
    source_updated = datetime.fromtimestamp(source.stat().st_mtime, UTC).isoformat(timespec="seconds")
    catalog = {
        "schemaVersion": 1,
        "generatedAt": source_updated,
        "sourceRevision": source_hash,
        "count": len(recipes),
        "categories": sorted({recipe["category"] for recipe in recipes}),
        "recipes": recipes,
    }
    encoded = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    sanitize(encoded)
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Path to the private canonical Markdown note")
    parser.add_argument("--output", type=Path, default=Path("site/data/recipes.json"))
    parser.add_argument("--check", action="store_true", help="Fail when generated output differs; do not write")
    args = parser.parse_args()

    if not args.source.is_file():
        parser.error(f"source does not exist: {args.source}")
    catalog = build_catalog(args.source)
    encoded = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != encoded:
            print(f"Catalog is stale: {args.output}", file=sys.stderr)
            return 1
        print(f"Catalog is current: {catalog['count']} entries")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    counts: dict[str, int] = {}
    for recipe in catalog["recipes"]:
        counts[recipe["status"]] = counts.get(recipe["status"], 0) + 1
    print(f"Exported {catalog['count']} sanitized entries to {args.output}")
    print("Status summary: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
