# Repository validation

Run these checks before committing or sharing changes.

## Python syntax

```powershell
python -m py_compile `
  .\google_jobs_scraper.py `
  .\google_jobs_scraper_beast_mode.py `
  .\google_jobs_scraper_comprehensive.py `
  .\google_jobs_scraper_FIXED.py `
  .\google_jobs_scraper_optimized.py `
  .\smart_scheduler.py
```

## Sensitive-content scan

Confirm there are no credentials, personal identifiers, private endpoints, or employer-internal URLs:

```powershell
rg -n -i 'api[_-]?key\s*=\s*["''][^"'']{8,}|bearer\s+[a-z0-9._-]{16,}|dev\.azure\.com|visualstudio\.com' .
```

Expected matches are limited to environment-variable reads and clearly synthetic placeholders.

## Repository scope

Confirm that generated and private artifacts are not staged:

```powershell
git status --short
git diff --cached --check
git ls-files | rg -i '\.(docx|pdf|csv|json|log|backup)$'
```

The final command should return no results unless a deliberately reviewed, synthetic fixture is added later with a narrow `.gitignore` exception.

## Runtime data

Prototype scripts write to `data/` by default. This directory is ignored. Set `ATS_DATA_DIR` when data must be stored elsewhere:

```powershell
$env:ATS_DATA_DIR = 'C:\private\ats-data'
```

Never point it at a directory tracked by Git.
