#!/usr/bin/env python3
"""Export a sanitized public recipe catalog from the canonical Markdown note."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

PUBLIC_CATEGORIES = {
    "Cooking Reference",
    "Sauces & Dressings",
    "Mains",
    "Bowls & Salads",
    "Sides & Components",
    "Smoothies",
}
EXCLUDED_TITLES = {"Recipe Name"}
EXCLUDED_CATEGORIES = {"Index", "External Links / To Extract", "Source Notes Consolidated", "Recipe Template", "Meal Plans"}
# Every public URL must be reviewed individually. A None label permits the URL
# but keeps attribution generic; changed labels also fall back to generic.
REVIEWED_SOURCE_LABELS = {
    "https://www.instagram.com/reel/DfY98OytZr-/": "Instagram Reel — @themacrosnerd",
    "https://www.instagram.com/reel/Dbe4svTK3Pq/": "Instagram Reel — Daniella Christie (@daniyellla)",
    "https://www.instagram.com/reel/DFT-yfhtjoa/": "Instagram Reel — Alissa Nguyen Won (@alissanguyen_)",
    "https://www.tiktok.com/@annlmartinez/video/7688129794373913870/": "TikTok — annlmartinez (@annlmartinez)",
    "https://www.instagram.com/reel/DejuHUotxuj/": "Instagram Reel — Panacea Palm | Dij (@panaceapalm)",
    "https://www.instagram.com/reel/DfEJH8ev4rG/": "Instagram Reel — Angel (@angelunsweetened)",
    "https://recipesbykip.com/recipe/cowboy-butter-lemon-bowtie-chicken/": "Recipes By Kip",
    "https://www.instagram.com/reel/DewnoMXut3C/": "Instagram Reel — Arash Hashemi / Shred Happens (@shredhappens)",
    "https://www.tiktok.com/@amandajanelles/video/7524083839396760887/": "TikTok — Amanda Janelle 🇵🇭 (@amandajanelles)",
    "https://www.instagram.com/reel/De-ZeM9POHt/": "Instagram Reel — Sivan's Kitchen (@sivanskitchen)",
    "https://youtube.com/shorts/82YTLiB-i_U/": "YouTube Shorts",
    "https://www.youtube.com/shorts/ImUPlhOEeIw/": "YouTube Shorts",
    "https://www.instagram.com/reel/DduIRLSS4sb/": "Instagram Reel — soo / soosfoods",
    "https://www.instagram.com/reel/DcHUkkRyn3D/": "Instagram Reel — Asanebo Restaurant (@asanebo_restaurant)",
    "https://www.instagram.com/reel/DcgIJGiTxvs/": "Instagram Reel — Lunch O’Clock (@lunches_at_home)",
    "https://www.tiktok.com/@stephvnietea/video/7324865404797504811/": "TikTok by @stephvnietea",
    "https://www.instagram.com/reel/Db0S_62TPDQ/": "Instagram Reel — Lunch O’Clock (@lunches_at_home)",
    "https://spiceupbites.com/slow-cooker-mexican-chicken-pozole-verde/": "Spice Up Bites — Millie Pham",
    "https://downshiftology.com/recipes/cucumber-radish-salad/": None,
    "https://www.instagram.com/reel/DbGVJwyKJfF/": "Instagram Reel — Adam Wolfe | Fitness (@adamwolfefitness)",
    "https://www.instagram.com/reel/Dbpd8QsS5_U/": "Instagram Reel — bear_wife (@bear_wife_)",
    "https://www.tiktok.com/@heresyourbite/video/7390533434273238303/": "TikTok by @heresyourbite",
    "https://www.instagram.com/reel/DcSBHD7MIW2/": "Instagram Reel — Sarah | Fit Foodie (@scmfitfoodie)",
    "https://www.instagram.com/reel/DclvFdeMpfP/": "Instagram Reel — Erika Izumi | Easy Japanese Recipes (@easy.japanese.kitchen)",
}
PUBLIC_META_FIELDS = {"makes", "servings", "serves", "yield", "prep time", "cook time", "marinating time", "calories", "protein", "fiber", "carbohydrates", "fat", "per serving", "per large serving", "per meal", "whole pot"}
PRIVATE_FIELDS = {"image", "images", "original note", "original title", "original title/caption", "status", "category", "original reel caption", "original caption", "original reel title", "original description", "video overlay/title", "missing image reference from legacy note"}
REFERENCE_LABELS = {"boneless chicken breast", "bone-in chicken breast", "boneless thighs", "bone-in thighs / drumsticks", "whole chicken", "why", "checklist"}
INLINE_LABELS = {"optional", "optional finish", "the caption says", "set out 6 bowls", "organize ingredients", "mix in a bowl"}
INGREDIENT_GROUPS = {name.casefold() for name in (
    "For the chicken", "Sauce", "For the street corn", "For the cowboy butter sauce",
    "For the sauce", "For the dressing", "For the dairy-free Greek salad", "Marinade",
    "Seasoning", "Optional toppings", "For topping", "For the pasta and broccoli",
    "Skillet rice", "For finishing", "For serving", "For the chicken and potatoes",
    "Sauces", "Side", "For a vegan version", "Main",
)}
INTRO_GROUPS = {
    "Turkey Lettuce Wraps with Cilantro Lime Yogurt Sauce": {"turkey", "sauce", "toppings"},
    "Quinoa Turkey Bowls": {"stir fry", "sear", "base", "top with"},
    "Chicken Gyro Wraps": {"tzatziki sauce", "chicken marinade", "vegetable medley"},
}
IMAGE_EMBED_RE = re.compile(r"!\[\[[^\]]*\]\]|!\[[^\]]*\]\([^)]*\)")
IMAGE_FILENAME_RE = re.compile(r"(?i)(?:[^\s/\\]+[/\\])*[^\s/\\]+\.(?:png|jpe?g|gif|webp|heic|svg)(?:\?[^\s]*)?")
PRIVATE_PATTERNS = [
    ("absolute home path", re.compile(r"/home/[A-Za-z0-9._-]+/")),
    ("credential-like assignment", re.compile(r"(?i)(?:token|api[_-]?key|password|secret)[\"']?\s*[:=]\s*[\"']?[^\s,\"']{8,}")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
]
URL_RE = re.compile(r"https?://[^\s)>]+")
HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
NUMBERED_RE = re.compile(r"^\d+[.)]\s+(.+)$")
BULLET_RE = re.compile(r"^-\s+(.+)$")
TASK_RE = re.compile(r"^(?:[-+*]|\d+[.)])\s+\[[ xX]\](?:\s|$)")
FIELD_RE = re.compile(r"^([^:]+):\s*(.*)$")
HTML_RE = re.compile(r"<(?:!|\?|/?[A-Za-z])")
PRIVATE_TODO_RE = re.compile(r"^original .+ note had this as a todo\.?$", re.I)


def canonicalize_url(value: str) -> str:
    # Strip query/fragment and incidental sentence punctuation. A single
    # trailing slash may be added only when the exact resulting URL is reviewed.
    # Never normalize path segments, hostname, encoding, credentials or scheme.
    candidate = value.rstrip(".,").split("#", 1)[0].split("?", 1)[0]
    if candidate in REVIEWED_SOURCE_LABELS:
        return candidate
    if not candidate.endswith("/") and candidate + "/" in REVIEWED_SOURCE_LABELS:
        return candidate + "/"
    return ""


def clean_text(value: str) -> str:
    if HTML_RE.search(value):
        raise ValueError("Public export rejected: HTML or comment")
    value = value.strip()
    value = IMAGE_EMBED_RE.sub("", value)
    value = IMAGE_FILENAME_RE.sub("", value)
    value = URL_RE.sub(lambda match: canonicalize_url(match.group(0)), value)
    # Only local heading links can be rendered as recipe text; a cross-note
    # link may name a private note, even when its syntax is stripped.
    value = re.sub(r"\[\[([^]|]+)(?:\|([^]]+))?\]\]", lambda m: (m.group(2) or m.group(1)[1:]) if m.group(1).startswith("#") else "", value)
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
    if url not in REVIEWED_SOURCE_LABELS:
        raise ValueError("Public export rejected: unapproved source URL")
    public_label = label if REVIEWED_SOURCE_LABELS.get(url) == label else "Original source"
    return {"label": public_label, "url": url, "platform": platform_for(url)}


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
            if category not in PUBLIC_CATEGORIES | EXCLUDED_CATEGORIES:
                raise ValueError("Public export rejected: unrecognized section")
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
    servings = None
    nutrition: list[str] = []
    excluded_indent: int | None = None
    excluded_list_item = False
    previous_section = "intro"
    task_indent: int | None = None

    for raw in body:
        expanded = raw.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip())
        if not raw.strip():
            continue
        if task_indent is not None:
            if indent > task_indent:
                continue
            task_indent = None
        if TASK_RE.match(raw.lstrip()):
            task_indent = indent
            continue
        line = clean_text(raw)
        if not line or line == "---" or line in {"-", "*"}:
            continue
        if excluded_indent is not None:
            if indent > excluded_indent:
                continue
            if excluded_list_item and indent == excluded_indent and BULLET_RE.match(line):
                section = previous_section
            elif not BULLET_RE.match(line) and not NUMBERED_RE.match(line) and FIELD_RE.match(line):
                section = "intro"
            else:
                continue
            excluded_indent = None
        item = BULLET_RE.match(line) or NUMBERED_RE.match(line)
        if PRIVATE_TODO_RE.match(item.group(1) if item else line):
            continue
        lower = line.casefold()
        if lower == "ingredients:":
            section = "ingredients"
            continue
        if lower in {"steps:", "instructions:", "method:", "optimized steps:"}:
            section = "steps"
            continue
        if lower in {"notes:", "cleanup / safety notes:"}:
            section = "notes"
            continue
        if lower == "use with:":
            section = "use"
            continue
        numbered = NUMBERED_RE.match(line)
        bullet = BULLET_RE.match(line)
        content_match = bullet or numbered
        field = FIELD_RE.match(content_match.group(1) if content_match else line)
        # Explicitly reviewed public fields for this entry; other labels remain closed.
        if (title == "Chicken & Broccoli Salad" and section == "ingredients"
                and line == "Dressing:"):
            ingredient_group = "Dressing"
            continue
        if (title == "Chicken & Broccoli Salad" and section == "notes" and bullet
                and bullet.group(1) == "Creator's stated nutrition: 455 calories, 64 g protein, 15 g fat, and 16 g carbohydrates. Serving count is not specified."):
            field = None
        if section == "source" and bullet and bullet.group(1).startswith("https://"):
            source = parse_source("Source: " + bullet.group(1))
            section = "intro"
            continue
        # This reviewed ingredient uses a colon to enumerate its berries.
        if (title == "Berry Blast Smoothie" and section == "ingredients" and bullet
                and bullet.group(1) == "1 cup mixed berries: strawberries, blueberries, raspberries"):
            field = None

        # Recognize fields before processing the current section: otherwise a
        # private field after Ingredients/Notes becomes public recipe content.
        if field:
            name = field.group(1).casefold()
            value = field.group(2).strip()
            if name in PRIVATE_FIELDS:
                previous_section = section
                excluded_indent = indent
                excluded_list_item = bool(content_match)
                section = "excluded"
                continue
            if name == "source":
                if source is None:
                    source = parse_source("Source: " + value)
                if not content_match:
                    section = "source" if not value else "intro"
                continue
            if not content_match and not value and name in INTRO_GROUPS.get(title, set()) and section in {"intro", "ingredients"}:
                section = "ingredients"
                ingredient_group = field.group(1)
                continue
            if title == "Cabbage Stir Fry" and not content_match and not value and name in {"recipe 1", "recipe 2", "recipe 3"}:
                section = "mixed-reference"
                reference.append(line)
                continue
            if section == "mixed-reference" and content_match and name == "mix in a bowl" and not value:
                reference.append(content_match.group(1))
                continue
            if category == "Cooking Reference" and name in REFERENCE_LABELS:
                reference.append(clean_text(content_match.group(1)) if content_match else line)
                continue
            if content_match and name in INLINE_LABELS and section in {"ingredients", "steps", "notes"}:
                field = None
            elif name in PUBLIC_META_FIELDS:
                if value:
                    meta.append(line)
                    if name in {"makes", "servings", "serves", "yield"}:
                        servings = value
                    if name in {"calories", "protein", "fiber", "carbohydrates", "fat", "per serving", "per large serving", "per meal", "whole pot"}:
                        nutrition.append(line)
                section = "intro"
                continue
            if field and section == "ingredients" and not bullet and not numbered and name in INGREDIENT_GROUPS and not value:
                ingredient_group = field.group(1)
                continue
            if field:
                raise ValueError("Public export rejected: unrecognized field or component label")

        if section == "excluded":
            continue

        if section == "mixed-reference":
            reference.append(content_match.group(1) if content_match else line)
        elif section == "ingredients":
            if bullet:
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
        # Unlabelled introduction text is not an approved public field.

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
    seen: set[str] = set()
    for recipe in recipes:
        if recipe["id"] in seen:
            raise ValueError("Public export rejected: ambiguous recipe identifier")
        seen.add(recipe["id"])


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
    if HTML_RE.search(markdown):
        raise ValueError("Public export rejected: HTML or comment")
    recipes = [parse_entry(*entry) for entry in split_entries(markdown)]
    unique_ids(recipes)
    recipes.sort(key=lambda item: (item["category"], item["title"].casefold()))
    catalog = {
        "schemaVersion": 1,
        "count": len(recipes),
        "categories": sorted({recipe["category"] for recipe in recipes}),
        "recipes": recipes,
    }
    public_bytes = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    catalog["catalogRevision"] = hashlib.sha256(public_bytes).hexdigest()[:12]
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
