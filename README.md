# ATSAutomation

AI-powered ATS automation research and a private, sanitized preservation of the ATS/RAG job-assistant architecture, prompts, and early SerpAPI prototypes developed under `C:\ATS`.

## Repository contents

- `docs/00-START-HERE.md` through `docs/07-RESEARCH-FOUNDATION.md`: reconciled implementation baseline.
- `docs/research/original-research-synthesis.md`: original consolidated research synthesis.
- `RAG_*.md`: earlier architecture, optimization, prompt, and DFD artifacts retained for traceability.
- `MASTER_ATS_VALIDATION_PROMPT.md`: reusable ATS validation prompt.
- `google_jobs_scraper*.py`: sanitized historical SerpAPI prototypes.
- `smart_scheduler.py`: prototype API-credit tracker.
- `migration/README.md`: migration scope and exclusions.

The canonical design is `docs/00-START-HERE.md`. Earlier artifacts may describe superseded choices and are retained as research history, not current implementation authority.

## Privacy and publication scope

This repository intentionally excludes:

- resumes, cover letters, application drafts, and extracted resume text;
- personal contact details and candidate-specific generated content;
- DOCX, PDF, HTML, CSV, JSON payload, log, backup, and cache artifacts;
- local tool settings and temporary files;
- hardcoded credentials, private endpoints, and internal URLs;
- SQL files requiring a separate provenance and confidentiality review.

The original `C:\ATS` workspace is not modified by this migration.

## Prototype setup

The prototype scripts require Python 3.11 and a SerpAPI key:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SERPAPI_API_KEY = '<your-key>'
python .\google_jobs_scraper_FIXED.py
```

Generated job data is written to the ignored `data/` directory. Override it with `ATS_DATA_DIR`:

```powershell
$env:ATS_DATA_DIR = 'C:\private\ats-data'
```

Do not commit `.env` files, API responses, job exports, resumes, or candidate data.

## Current maturity

This is primarily a design and research repository. The target `src/ats_local` package, migrations, tests, CLI, Qdrant projection, local model integration, and production controls described in the canonical documents have not yet been implemented.
