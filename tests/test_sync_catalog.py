import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from sync_catalog import build_catalog, parse_entry, sanitize, split_entries


SAMPLE = """# Recipe Collection
Tags: [[Private]]

## Mains

### Test Soup

Source: Example — https://example.com/watch/1

Makes: 2 servings

Ingredients:
- 1 cup water
- Salt, to taste

Steps:
1. Stir for 5 minutes.

Notes:
- Source-provided note.

### Staged Reel

Status: external recipe to extract.
https://www.instagram.com/reel/example/?igsh=opaque

## External Links / To Extract

- https://private.example/

## Recipe Template

### Recipe Name

Ingredients:
- Ingredient
"""


class SyncCatalogTests(unittest.TestCase):
    def test_split_entries_allowlists_categories(self):
        entries = split_entries(SAMPLE)
        self.assertEqual([(category, title) for category, title, _ in entries], [("Mains", "Test Soup")])

    def test_parse_entry_preserves_source_and_structure(self):
        entry = split_entries(SAMPLE)[0]
        recipe = parse_entry(*entry)
        self.assertEqual(recipe["source"]["url"], "https://example.com/watch/1")
        self.assertEqual(recipe["servings"], "2 servings")
        self.assertEqual(recipe["ingredients"][0]["text"], "1 cup water")
        self.assertEqual(recipe["steps"], ["Stir for 5 minutes."])
        self.assertEqual(recipe["status"], "complete")

    def test_social_source_url_is_canonicalized(self):
        entry = split_entries(SAMPLE.replace("https://example.com/watch/1", "https://www.instagram.com/reel/example/?igsh=opaque"))[0]
        recipe = parse_entry(*entry)
        self.assertEqual(recipe["source"]["url"], "https://www.instagram.com/reel/example/")

    def test_catalog_does_not_export_note_metadata_or_excluded_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "recipes.md"
            source.write_text(SAMPLE, encoding="utf-8")
            catalog = build_catalog(source)
        payload = json.dumps(catalog)
        self.assertEqual(catalog["count"], 1)
        self.assertNotIn("Private", payload)
        self.assertNotIn("private.example", payload)
        self.assertNotIn("Recipe Name", payload)

    def test_sanitize_rejects_private_material(self):
        for payload in (
            '{"path":"/home/person/Vault/file.md"}',
            '{"api_key":"abcdefghijk"}',
            '{"contact":"person@example.com"}',
            '{"link":"[[Internal Note]]"}',
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                sanitize(payload)


if __name__ == "__main__":
    unittest.main()
