"""Ingest boundary helpers.

Ingest is responsible for:
- Assigning stable IDs for inputs (content-addressed when possible).
- Dedupe at the boundary (avoid duplicating blobs/records for identical inputs).
- Writing minimal evidence records + provenance (journal/ledger via event builder).

It must not trigger heavy processing (OCR/VLM/embeddings); those occur in idle jobs.
"""

from __future__ import annotations

from .file_ingest import ingest_file  # noqa: F401
from .handoff_ingest import DrainResult, HandoffIngestor, IngestResult  # noqa: F401
