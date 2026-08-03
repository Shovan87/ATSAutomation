# Migration record

## Source

- Original workspace: `C:\ATS`
- Original state: 277 files, approximately 25 MB, not a Git repository
- Migration method: copy into a separate staging directory; the source workspace was not modified

## Included

- Canonical ATS/RAG design documentation
- Consolidated and original research synthesis
- Historical RAG architecture, prompt, retrieval, and DFD documents
- Sanitized SerpAPI ingestion prototypes
- Credit scheduling prototype

## Excluded

The following categories remain only in the original local workspace:

- all resumes, cover letters, application correspondence, and candidate-specific content;
- extracted resume text and generated validation reports;
- generated DOCX, PDF, HTML, CSV, JSON, log, and backup files;
- personal contact information and profile URLs;
- scripts whose primary purpose is generating a specific person's resume or profile;
- local editor/agent settings and temporary output;
- files containing hardcoded credentials or private/internal URLs unless safely rewritten;
- SQL artifacts pending a separate provenance and confidentiality review;
- unrelated PostgreSQL, SQL Server interview, salary, and market-analysis guides.

## Sanitization performed

- Removed the hardcoded SerpAPI credential from all retained scripts.
- Retained scripts now read `SERPAPI_API_KEY` from the environment.
- Removed internal URLs and local session-state paths.
- Replaced candidate-specific names, contact data, and filenames in retained design documents.
- Redirected generated prototype data to the ignored `data/` directory.

## Important limitation

This repository is a sanitized engineering and research record, not a byte-for-byte backup. The original local workspace remains the complete private archive.
