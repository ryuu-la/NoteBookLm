Contributing
============

Install the development extra, then run `python -m pytest -q` and `ruff check src tests scripts benchmarks` before submitting changes.

Keep modules focused and preferably below 250–350 lines. Put UI rendering in `ui`, parsing in `ingestion`, retrieval in `retrieval`, and provider-specific behavior in the provider adapter. Use descriptive types and names; add comments to explain non-obvious constraints rather than narrate code.

Tests should exercise behavior: source isolation, replay safety, citation validity, parser provenance, or error recovery. Do not substitute fake outputs for model behavior in the product. Test fixtures and mock provider responses belong in tests and must be identified as such.

Browser checks use an isolated local library. `--live` uses the configured provider and consumes quota; ordinary tests should run without a cloud key. Never commit credentials, personal source files, runtime databases, or generated test logs.

The current schema starts at version 1. Changes to stored data or embedding dimensions need a migration/rebuild strategy, and changes to chunk boundaries need a plan for existing citation targets.
