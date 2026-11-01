# AGENTS.md

## Mission

Maintain a polished, public, offline-friendly recipe companion while preserving a strict one-way boundary from the private canonical recipe collection.

Read `spec.md` before changing architecture, publication behavior, or the catalog schema.

## Hard constraints

- Never copy the private Vault, canonical Markdown source, absolute source path, unrelated note content, or Vault Git history into this repository.
- Run `scripts/sync_catalog.py` locally with an explicit `--source`; review the generated `site/data/recipes.json` diff before publishing.
- Treat source quantities and steps as facts: preserve missing information visibly and never infer recipe details.
- Embed or link third-party media through official public players; never download or rehost media without ownership and explicit approval.
- Keep GitHub Pages deployment limited to `site/`. Do not add secrets to client code or workflows.
- Prefer dependency-free static behavior until real usage proves that a backend is necessary.

## Validation

```bash
npm run validate
git diff --check
git status --short --branch
```

For UI changes, also serve `site/` over HTTP and exercise the affected flow in a real browser at mobile and desktop widths.

## Collaboration

For genuine product decisions, ask selectable MCQs with the recommended option first. Decide low-stakes implementation details without interruption. Ask before unrelated or destructive external actions; a user request to publish the site is authorization for the scoped repository creation, push, Pages enablement, and deployment verification.
