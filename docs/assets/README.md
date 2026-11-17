# Documentation assets

Keep reusable material for Markdown guides, the README, and a future MkDocs site here. The
directories are organized by how an asset is used:

- `styles/`: future documentation theme overrides and custom CSS.
- `images/`: reviewed diagrams and screenshots that can be embedded in documentation.
- `scripts/`: small, reproducible helpers for generating or checking documentation assets.

The TUI SVGs are headless captures of the credential-free Demo workspace. They illustrate layout
and are not physical Windows Terminal evidence. The pytest SVG snapshots under
`tests/unit/runtimes/tui/__snapshots__/` remain the automated visual regression baselines.

Run `uv run --group test python docs/assets/scripts/export_tui_previews.py` to regenerate the
document screenshots. Keep assets free of real project identifiers, tokens, and device payloads.
