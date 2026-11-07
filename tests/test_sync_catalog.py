import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from sync_catalog import build_catalog, clean_text, parse_entry, sanitize, split_entries


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
    def setUp(self):
        # Synthetic URLs are test-only, never production export approvals.
        patcher = patch.dict('sync_catalog.REVIEWED_SOURCE_LABELS', {
            'https://example.com/watch/1': None,
            'https://example.com/recipe': None,
            'https://www.instagram.com/reel/example/': None,
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_tasks_and_nested_continuations_are_never_exported(self):
        for section in ('Notes:', 'Ingredients:', 'Steps:', 'Use with:'):
            for marker in ('- [ ]', '- [x]', '- [X]', '* [ ]', '+ [x]', '1. [ ]', '2) [X]'):
                with self.subTest(section=section, marker=marker):
                    recipe = parse_entry('Mains', 'Soup', [section, marker + ' secret-task',
                        '  secret-continuation', '  - secret-nested', '- public sibling'])
                    payload = json.dumps(recipe).casefold()
                    self.assertNotIn('secret-', payload)
                    self.assertIn('public sibling', payload)
        reference = parse_entry('Cooking Reference', 'Grilling tip',
                                ['Checklist:', '- [x] secret-task', '- public sibling'])
        self.assertNotIn('secret-task', json.dumps(reference))
        self.assertIn('public sibling', reference['reference'])

    def test_source_labels_require_exact_reviewed_url_and_label_pair(self):
        url = 'https://www.instagram.com/reel/Dbe4svTK3Pq/'
        label = 'Instagram Reel — Daniella Christie (@daniyellla)'
        source = parse_entry('Mains', 'Soup', ['Source: ' + label + ' — ' + url])['source']
        self.assertEqual(source['label'], label)
        for value in (f'Private label — {url}',
                      f'{label} secret — {url}',
                      f'Private label — https://example.com/watch/1'):
            with self.subTest(value=value):
                recipe = parse_entry('Mains', 'Soup', ['Source: ' + value])
                self.assertEqual(recipe['source']['label'], 'Original source')
                self.assertNotIn('private label', json.dumps(recipe).casefold())
                self.assertNotIn('secret', json.dumps(recipe).casefold())

    def test_private_field_blocks_respect_indentation(self):
        recipe = parse_entry('Mains', 'Soup', ['Notes:', '- Original note: secret-one',
            '  Ingredients:', '  - secret-two', '  Notes:', '  - secret-three',
            '- Public note', 'Original title:', '  Steps:', '  - secret-four',
            'Ingredients:', '- water'])
        self.assertNotIn('secret', json.dumps(recipe))
        self.assertEqual(recipe['notes'], ['Public note'])
        self.assertEqual(recipe['ingredients'][0]['text'], 'water')

    def test_punctuation_labels_fail_closed(self):
        for label in ('Private!:', 'Private #1:', 'Private?:', 'Private\u2019s:', 'Private @ info:', 'Private!:secret:'):
            with self.subTest(label=label), self.assertRaises(ValueError):
                parse_entry('Mains', 'Soup', ['Notes:', '- ' + label + ' secret'])

    def test_html_and_comments_fail_closed(self):
        for text in ('<!-- secret -->', '<b>secret</b>', '<!--', '  <div>'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_entry('Mains', 'Soup', ['Notes:', '- safe ' + text])

    def test_private_cross_note_todo_is_not_published(self):
        recipe = parse_entry('Mains', 'Soup', ['Notes:',
            '- Original Dinner Recipes note had this as a todo.', '- Keep chilled'])
        self.assertEqual(recipe['notes'], ['Keep chilled'])
        self.assertNotIn('dinner recipes', recipe['searchText'])

    def test_cabbage_mixed_groups_are_reference_not_ingredients(self):
        recipe = parse_entry('Sides & Components', 'Cabbage Stir Fry', ['Recipe 1:',
            '- cabbage', '- When translucent, add sauce.', 'Recipe 2:',
            '- Mix in a bowl:', '  - 2 tbsp sauce', '- Sauté garlic.',
            'Recipe 3:', '- teriyaki sauce'])
        self.assertEqual(recipe['ingredients'], [])
        self.assertEqual(recipe['reference'], ['Recipe 1:', 'cabbage',
            'When translucent, add sauce.', 'Recipe 2:', 'Mix in a bowl:',
            '2 tbsp sauce', 'Sauté garlic.', 'Recipe 3:', 'teriyaki sauce'])

    def test_meal_plans_and_internal_metadata_never_export(self):
        text = SAMPLE.replace('Makes: 2 servings', '''Makes: 2 servings
Image: confidential-photo.png
Original note: private-history
Original title/caption: private-caption''') + '''
## Meal Plans
### Private weekly menu
Notes:
- confidential-dinner
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.md'
            source.write_text(text, encoding='utf-8')
            catalog = build_catalog(source)
        payload = json.dumps(catalog)
        for secret in ('Meal Plans', 'confidential', 'private-history', 'private-caption'):
            self.assertNotIn(secret, payload)
        self.assertEqual(catalog['count'], 1)

    def test_images_omitted_across_recipe_content(self):
        entry = ('Mains', 'Soup', ['Image: secret.jpg', 'Ingredients:',
                 '- 1 cup water ![[secret-image.png]]',
                 '- ![photo](images/secret2.jpg)', 'Steps:',
                 '1. Stir. ![photo](https://example.com/secret3.png)',
                 'Notes:', '- ![[secret4.webp]]'])
        payload = json.dumps(parse_entry(*entry))
        self.assertNotIn('secret', payload)
        self.assertIn('1 cup water', payload)
        self.assertIn('Stir.', payload)

    def test_unknown_fields_fail_closed_in_all_sections(self):
        for prefix in ([], ['Ingredients:', '- 1 cup water'],
                       ['Steps:', '1. Mix'], ['Notes:', '- Good']):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                parse_entry('Mains', 'Soup', prefix + ['Private detail: sensitive-value'])
            with self.subTest(bulleted=prefix), self.assertRaises(ValueError):
                parse_entry('Mains', 'Soup', prefix + ['- Private detail: sensitive-value'])
            with self.subTest(underscored=prefix), self.assertRaises(ValueError):
                parse_entry('Mains', 'Soup', prefix + ['private_1: sensitive-value'])

    def test_unlabelled_intro_is_not_exported(self):
        recipe = parse_entry('Mains', 'Soup', ['private-intro', '- private-list', 'Ingredients:', '- 1 cup water'])
        self.assertNotIn('private-', json.dumps(recipe))

    def test_site_validator_accepts_synthetic_catalog_and_rejects_leaks(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            shutil.copytree(root / 'site', target / 'site')
            (target / 'scripts').mkdir()
            shutil.copy(root / 'scripts' / 'validate.mjs', target / 'scripts')
            source = target / 'input.md'
            source.write_text(SAMPLE, encoding='utf-8')
            catalog = build_catalog(source)
            catalog_path = target / 'site' / 'data' / 'recipes.json'
            def validate():
                catalog_path.write_text(json.dumps(catalog), encoding='utf-8')
                return subprocess.run(['node', str(target / 'scripts' / 'validate.mjs')], capture_output=True, text=True)
            self.assertEqual(validate().returncode, 0)
            for key, value in [('category', 'Meal Plans'), ('meta', ['Original note: private']), ('notes', ['secret.png'])]:
                with self.subTest(key=key):
                    old = catalog['recipes'][0][key]
                    catalog['recipes'][0][key] = value
                    result = validate()
                    self.assertNotEqual(result.returncode, 0)
                    catalog['recipes'][0][key] = old

    def test_reviewed_intro_components_and_private_intro(self):
        title = 'Turkey Lettuce Wraps with Cilantro Lime Yogurt Sauce'
        recipe = parse_entry('Mains', title, ['private-intro', 'Turkey:', '- 1 lb turkey',
            'Sauce:', '- 2 cups yogurt', 'Toppings:', '- lettuce'])
        self.assertEqual([x['group'] for x in recipe['ingredients']], ['Turkey', 'Sauce', 'Toppings'])
        self.assertNotIn('private-intro', json.dumps(recipe))
        with self.assertRaises(ValueError):
            parse_entry('Mains', 'Another recipe', ['Turkey:', '- 1 lb turkey'])

    def test_reviewed_fields_keep_notes_and_method_without_private_labels(self):
        recipe = parse_entry('Mains', 'Soup', ['Ingredients:', 'Main:', '- 1 cup water',
            'Optimized Steps:', '1. Mix', 'Cleanup / Safety Notes:', '- Wash up',
            'Notes:', '- Original caption: private caption', '- Source: Private source', '- Keep chilled'])
        self.assertEqual(recipe['steps'], ['Mix'])
        self.assertEqual(recipe['notes'], ['Wash up', 'Keep chilled'])
        self.assertNotIn('private caption', json.dumps(recipe))
        self.assertIsNone(recipe['source'])

    def test_wikilinks_do_not_publish_cross_note_names(self):
        recipe = parse_entry('Mains', 'Soup', ['Ingredients:', '- 1 cup [[#Sauce]]',
            'Notes:', '- See [[Private Note|private alias]]'])
        payload = json.dumps(recipe)
        self.assertIn('1 cup Sauce', payload)
        self.assertNotIn('Private Note', payload)
        self.assertNotIn('private alias', payload)

    def test_unknown_section_and_unapproved_source_fail_closed(self):
        with self.assertRaises(ValueError):
            split_entries(SAMPLE + '\n## Unknown section\n')
        for url in ('http://example.com/path', 'https://example.com.evil.invalid/path',
                    'https://user@example.com/path'):
            with self.subTest(url=url):
                self.assertIsNone(parse_entry('Mains', 'Soup', ['Source: ' + url])['source'])

    def test_urls_are_individually_reviewed_and_never_export_queries(self):
        approved = 'https://downshiftology.com/recipes/cucumber-radish-salad/'
        for suffix in ('?private=secret', '#private-secret', '?private=secret#other'):
            recipe = parse_entry('Mains', 'Soup', ['Source: ' + approved + suffix])
            self.assertEqual(recipe['source']['url'], approved)
            self.assertNotIn('secret', json.dumps(recipe))
            self.assertEqual(clean_text('See ' + approved + suffix), 'See ' + approved)
        for url in ('https://www.instagram.com/direct/t/123456/',
                    'https://www.instagram.com/reel/other/',
                    'https://www.instagram.com/reel/Dbe4svTK3Pq/../direct/t/123/',
                    'https://www.instagram.com/reel/Dbe4svTK3Pq/%2e%2e/direct/',
                    'https://downshiftology.com/private?token=secret',
                    'https://www.instagram.com.evil.invalid/reel/Dbe4svTK3Pq/'):
            recipe = parse_entry('Mains', 'Soup', ['Source: ' + url])
            self.assertIsNone(recipe['source'], url)
            self.assertNotIn(url.split('?')[0], json.dumps(recipe))
            self.assertEqual(clean_text('See ' + url), 'See')

    def test_duplicate_identifiers_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.md'
            source.write_text('## Mains\n### Soup\nIngredients:\n- water\n### Soup\nIngredients:\n- water\n')
            with self.assertRaises(ValueError):
                build_catalog(source)

    def test_source_on_next_bullet(self):
        recipe = parse_entry('Mains', 'Salad', ['Source:', '- https://example.com/recipe'])
        self.assertEqual(recipe['source']['url'], 'https://example.com/recipe')

    def test_known_yield_and_component_groups(self):
        recipe = parse_entry('Mains', 'Soup', ['Servings: 3', 'Ingredients:',
            'For the chicken:', '- 1 chicken', 'Sauce:', '- 2 cups water',
            'Steps:', '1. Mix'])
        self.assertEqual(recipe['servings'], '3')
        self.assertEqual([item['group'] for item in recipe['ingredients']], ['For the chicken', 'Sauce'])

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
        self.assertRegex(catalog["catalogRevision"], r"^[a-f0-9]{12}$")
        self.assertNotIn("sourceRevision", catalog)
        self.assertNotIn("generatedAt", catalog)
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
