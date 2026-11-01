# Product specification

## Intent

Turn a personal recipe collection into a genuinely useful, public, offline-friendly cooking companion without exposing the private Vault that supplies it.

## Users and success

The primary user should be able to find a recipe quickly on a phone, understand whether its source data is complete, gather ingredients, follow steps in the kitchen, and return to it offline. Success means the current public catalog is navigable, usable without accounts, deployable through GitHub Pages, and reproducibly refreshable from the private source through a reviewed public-data diff.

## Security boundary

- The private Vault, source note, absolute source path, unrelated links, credentials, and Vault Git history must never be committed.
- Public output is generated locally through an allowlist and private-signal scan.
- GitHub Actions sees only this public repository and deploys only `site/`.
- Third-party media is linked or officially embedded; it is not copied or rehosted.
- Personal favorites, notes, check states, timers, and grocery data remain browser-local.

## Version-one workflows

1. Browse/search/filter catalog entries and identify completeness.
2. Open a recipe, follow source attribution, and optionally load a source video.
3. Scale recognizable quantities, check ingredients, and add them to a grocery list.
4. Enter kitchen mode, move through steps, and start detected timers.
5. Build a meal by combining a main, reusable sauce, and side.
6. Install the app and reopen the committed catalog offline.
7. Regenerate the sanitized catalog locally and review the exact public diff before publication.

## Non-goals

Accounts, cross-device synchronization, editing the Vault from the public site, reliable operating-system alarms, AI generation, and real-time collaboration are intentionally excluded.

## Architecture

A dependency-free browser application reads a generated JSON catalog. A Python standard-library exporter parses the source Markdown and enforces the publication boundary. Node and Python standard-library checks validate the static artifact. GitHub Actions deploys only the dedicated `site/` directory.

## Acceptance checks

- Exporter unit tests pass and generated count matches the JSON array.
- No excluded note section, Obsidian wikilink, home path, email, key material, or credential-like assignment appears in the public site.
- Every critical local asset and internal anchor resolves.
- JavaScript passes syntax checks and the live app renders without console errors.
- Search, recipe details, meal composer, grocery list, kitchen mode, and a video facade work in a real browser.
- GitHub Pages workflow succeeds and the public URL returns the intended application and catalog.
