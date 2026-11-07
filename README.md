# Rogi's Recipe Book

A fast, installable cooking companion published on GitHub Pages. The public catalog is generated from a private canonical Markdown collection through a one-way sanitizing export; the private Vault and its Git history never enter this repository.

## Features

- Responsive search, category/status filters, and favorites
- Serving scaling with conservative quantity parsing
- Ingredient and method checklists
- Step-by-step kitchen mode with screen wake lock when supported
- One-tap timers extracted from recipe steps
- Local grocery list, personal kitchen notes, and meal composer
- Click-to-load YouTube, Instagram, and TikTok embeds with source attribution
- Offline-first Progressive Web App behavior
- Explicit completeness badges for partial source recipes

Browser-local preferences are intentionally device-local. The site has no accounts, backend, analytics, credentials, or private API keys.

## Local development

```bash
npm run validate
npm run serve
# open http://127.0.0.1:4173
```

## Refresh the public catalog

The source path is supplied at execution time and is never committed:

```bash
npm run sync -- --source "$RECIPE_COLLECTION_PATH"
npm run validate
git diff -- site/data/recipes.json
```

Review the generated diff before committing. The exporter:

1. allowlists known public catalog sections;
2. excludes meal plans, staging links, source-note consolidation, templates, legacy note metadata, and image references;
3. allowlists metadata and known ingredient component labels; unrecognized labeled fields fail the export for review;
4. converts Obsidian links to plain text and rejects home-directory paths, email addresses, credential-like assignments, private keys, and remaining wikilinks;
5. excludes task checkboxes and their nested content; source labels are published only when the exact canonical URL and label pair is reviewed in `REVIEWED_SOURCE_LABELS` (otherwise the label is generic);
6. preserves incomplete source information rather than inventing missing details. Review every generated change: automated checks cannot identify all private prose.

## Video policy

Third-party video is embedded through each platform's official player and loaded only after a visitor presses **Load video**. The written recipe remains useful if a creator removes or restricts a post. Third-party videos are linked and embedded, never downloaded or rehosted here.

## Publication

`.github/workflows/deploy.yml` validates the committed public artifact and deploys only `site/` through GitHub Pages. It cannot access the private source note.

## License

Application source is MIT licensed. Recipe text and embedded media remain attributed to their listed sources and creators where provided.
