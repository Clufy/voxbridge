# Contributing

## Development setup

Requires Python 3.12+.

```bash
uv venv && uv pip install -e ".[dev,docs]"
```

Without uv:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev,docs]"    # Windows: .venv\Scripts\python
```

## The local gate

Run all four before opening a PR; CI runs the same checks:

```bash
.venv/bin/python -m ruff check . \
  && .venv/bin/python -m mypy src tests \
  && .venv/bin/python -m pytest -q \
  && .venv/bin/python -m mkdocs build --strict
```

(On Windows use `.venv/Scripts/python`.) Delete the generated `site/` directory
afterwards. Tests must stay offline: HTTP is mocked with `respx`, and coverage
must stay at or above 90%.

## Fixtures

Test fixtures under `tests/fixtures/` are hand-authored from the provider's
published documentation, never captured from a live account. Sanitize them: fake
ids, fake `+1555` numbers, no real keys, secrets or personal data.

Every behaviour change to a sync provider method needs the same change on its
`a`-prefixed async twin, each with a test. A capability a provider cannot do must
raise `NotSupported`, not silently no-op.

## Commit style

Use [conventional commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`,
`docs:`, `test:`, `build:`, `chore:`), with an optional scope such as
`fix(retell): ...`. Do not add AI attribution trailers (`Co-Authored-By`,
"Generated with ...") to commits or PR descriptions.

## Releasing

One-time setup:

1. Create the GitHub repository `Clufy/voxbridge` and push `main`.
2. Enable GitHub Pages for the repository, serving from the `gh-pages` branch
   (the docs workflow publishes to it).
3. Confirm the name `voxbridge` is free on PyPI.
4. On PyPI, add a Trusted Publisher: owner `Clufy`, repository `voxbridge`,
   workflow `publish.yml`, environment `pypi`.
5. On GitHub, create the environment `pypi` (Settings, Environments).

For each release:

1. Move the CHANGELOG `Unreleased` heading to the release date, for example
   `## [0.1.0] - 2026-11-20`, and commit.
2. Tag and push: `git tag v0.1.0 && git push --tags`.
3. Check that the Publish workflow succeeded and the version appears on PyPI.
