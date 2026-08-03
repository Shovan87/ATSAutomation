# C:\ATS — Implementation-Level Reuse/Refactor/Replace Inventory
## Local RAG Job Assistant — Component Audit

**Audit Date:** 2026-08-01  
**Scope:** All executable Python scripts, validators, scrapers, schedulers, and DOCX generators under `C:\ATS\`  
**Methodology:** Direct source-code inspection with line citations; proposals and generated artifacts noted separately.

---

## 1. EXECUTIVE SUMMARY

The `C:\ATS\` workspace contains **~80 Python scripts** split across five functional clusters: (A) Job scrapers using SerpAPI, (B) ATS resume validators, (C) Keyword/density analyzers, (D) DOCX resume generators, and (E) a scheduler/credit tracker. The vast majority are **single-purpose, one-shot scripts** with hardcoded paths and API keys embedded in plain text — the single greatest security risk across the entire directory. There is **no shared library, no config file, no tests, no logging framework, and no secrets management**. Four scraper variants evolved by copy-paste, converging on the `FIXED` version as the only empirically validated one. The architecture documents (`RAG_JOB_SEARCH_ARCHITECTURE_REVIEW.md`, `RAG_MASTER_PROMPT.md`) are high-quality **design proposals** that describe the target RAG system but contain **no executable code**. The `ATSValidator` class in `ats_validator.py` is the most architecturally mature component.

---

## 2. CRITICAL SECURITY FINDING — ACT BEFORE ANYTHING ELSE

> ⚠️ **HARDCODED API KEY EXPOSURE** — HIGH SEVERITY

Multiple files contain a SerpAPI key in plain text:

| File | Line | Key Prefix |
|---|---|---|
| `google_jobs_scraper.py` | 13 | `<redacted>` |
| `google_jobs_scraper_beast_mode.py` | 15 | `<redacted>` |
| `google_jobs_scraper_optimized.py` | 15 | `<redacted>` |
| `google_jobs_scraper_comprehensive.py` | 15 | `<redacted>` |
| `google_jobs_scraper_FIXED.py` | 14 | `<redacted>` |
| `debug_serpapi.py` | 7 | `<redacted>` |
| `search_matching_roles_since_thursday.py` | 18 | different key, value removed |

**Action required:** Rotate both SerpAPI keys immediately. Move to environment variables (`os.getenv("SERPAPI_KEY")`) or a `.env` file excluded from any version control. Do **not** commit these files to any repository.

---

## 3. COMPONENT INVENTORY

### 3.1 SCRAPER SUBSYSTEM — Job Ingestion Layer

#### Component A1 — `google_jobs_scraper.py` (ORIGINAL)
| Attribute | Detail |
|---|---|
| **Status** | Executable — was the first working implementation |
| **Key symbols** | `search_google_jobs(query, location, date_posted)` → `list[dict]`, `main()` |
| **Behavior** | Runs 5 job titles × 6 GCC locations = 30 searches; date=`"today"`; UAE google domain (`google.ae`) |
| **Inputs** | Hardcoded `JOB_TITLES`, `LOCATIONS` lists; SerpAPI key at line 13 |
| **Outputs** | CSV at `c:\ATS\jobs_last_24_hours.csv` |
| **Dependencies** | `serpapi.GoogleSearch`, `csv`, `time` |
| **Defects** | (1) API key hardcoded line 13; (2) uses UAE-only Google domain (`google.ae`) — misses global results; (3) duplicate removal only on `job_link` — misses same job with different URL; (4) pagination logic duplicates the entire job-dict construction block (lines 87–97 = identical to 65–76); (5) `date_posted="today"` returns minimal results; (6) no retry/error recovery |
| **Coupling** | Fully self-contained monolith; no shared code with other scrapers |
| **Testability** | Zero — no functions extracted, no mock injection point for `GoogleSearch` |
| **Recommendation** | **ARCHIVE** |
| **Rationale** | Superseded by FIXED version. UAE-only domain is a regression. Pagination duplication makes maintenance error-prone. All useful logic reabsorbed into FIXED. |

---

#### Component A2 — `google_jobs_scraper_optimized.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable |
| **Key symbols** | `search_google_jobs(query, location, date_posted, fetch_all_pages=False)`, `main()` |
| **Behavior** | 3 combined queries × 9 locations = 27 searches; adds `fetch_all_pages` flag; skips pagination by default |
| **Inputs** | `OPTIMIZED_QUERIES` (3 OR-compound queries), `OPTIMIZED_LOCATIONS` (9); date=`"today"` |
| **Outputs** | CSV at `c:\ATS\jobs_last_24_hours.csv` — **same file as original**, risk of overwrite |
| **Defects** | (1) API key hardcoded line 15; (2) OR operators in location field confirmed **non-functional** by `debug_serpapi.py` TEST 6 (returns 0 results); (3) global `search_count` mutable state makes function impure |
| **Coupling** | Independent; shares no code with other scrapers |
| **Recommendation** | **ARCHIVE** |
| **Rationale** | The OR-in-location strategy was empirically disproved. FIXED version documents this finding and corrects it. |

---

#### Component A3 — `google_jobs_scraper_beast_mode.py` (BEAST MODE)
| Attribute | Detail |
|---|---|
| **Status** | Executable |
| **Key symbols** | `search_google_jobs(query, location, date_posted)`, `remove_duplicates(jobs)`, `analyze_jobs_by_region(jobs)`, `log_progress(message)`, `main()` |
| **Behavior** | 1 mega-query × 6 OR-compound locations = 6 searches; date=`"month"`; logs to `search_progress.txt` |
| **Inputs** | `BEAST_MODE_QUERY` (all SQL Server variants in one OR string), `BEAST_MODE_LOCATIONS` (6 OR-compound city strings) |
| **Outputs** | CSV `jobs_beast_mode.csv`, progress log `search_progress.txt` |
| **Defects** | (1) API key hardcoded line 15; (2) OR-in-location non-functional per debug tests; (3) global mutation of `search_count`, `total_jobs_found` (lines 54–55); (4) hardcoded `250 - search_count` arithmetic assumes fresh account at line 295; (5) `remove_duplicates` uses both link and title/company composite key — good logic but title comparison is case-sensitive |
| **Notable reuse candidates** | `remove_duplicates()` (lines 114–131) — dual-key deduplication is the most sophisticated version; `analyze_jobs_by_region()` (lines 133–163) — reusable region classifier |
| **Recommendation** | **REFACTOR** (extract 2 functions, discard runner) |
| **Target module** | `ats_local/scraper/utils.py`: `deduplicate_jobs(jobs)`, `classify_region(location_str)` |

---

#### Component A4 — `google_jobs_scraper_comprehensive.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable — but interactive (prompts `input()` at line 157) |
| **Key symbols** | `search_google_jobs(query, location, date_posted)`, `main()` |
| **Behavior** | 4 queries × 31 explicit individual locations = 124 searches; uses `date_posted="today"` |
| **Defects** | (1) API key hardcoded; (2) `input()` call makes automation/scheduling impossible; (3) region analysis inline in `main()` (not extracted); (4) 124 searches = nearly the entire 250-credit budget in one run |
| **Recommendation** | **ARCHIVE** |

---

#### Component A5 — `google_jobs_scraper_FIXED.py` ⭐ CANONICAL SCRAPER
| Attribute | Detail |
|---|---|
| **Status** | Executable — empirically validated by debug tests |
| **Key symbols** | `is_sql_server_job(job) → bool` (lines 50–77), `search_google_jobs(query, location, date_posted)`, `remove_duplicates(jobs)`, `analyze_jobs_by_region(jobs)`, `main()` |
| **Behavior** | 2 simple queries × 10 individual locations = 20 searches; date=`"month"`; post-processing filter for SQL Server relevance; dual-key deduplication |
| **Inputs** | `WORKING_QUERIES` (2 simple strings), `PRIORITY_LOCATIONS` (10 explicit cities); SerpAPI key line 14 |
| **Outputs** | CSV `jobs_global_sql_server_dba.csv` (note: different filename from others — no clobbering) |
| **Defects** | (1) API key hardcoded line 14; (2) global mutable state `search_count`, `total_jobs_found`; (3) no retry on transient HTTP errors; (4) `time.sleep(1)` hard-coded rate limiter — not back-off based; (5) `is_sql_server_job` checks both `title` and full `description` — description is ~500 chars truncated from API response, causing false negatives |
| **Notable reuse candidates** | `is_sql_server_job()` lines 50–77 — clean predicate function, unit-testable; `remove_duplicates()` — same dual-key pattern as Beast Mode |
| **Testability** | `is_sql_server_job` is the only pure function in the entire scraper family — easily unit-tested with a mock dict |
| **Recommendation** | **REFACTOR** into RAG ingestion module |
| **Target module** | `ats_local/scraper/serpapi_fetcher.py` |
| **Refactor actions** | (1) Inject API key via constructor/env; (2) Replace global state with dataclass; (3) Add `tenacity` retry decorator; (4) Extract `is_sql_server_job` as standalone predicate; (5) Parameterize queries and locations via config YAML; (6) Replace hard `sleep(1)` with exponential backoff |

---

#### Component A6 — `debug_serpapi.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable test harness — 8 sequential API calls |
| **Behavior** | Tests 8 increasingly complex SerpAPI query patterns; writes raw JSON to `c:\ATS\test{N}_response.json` |
| **Key finding documented** | TEST 6 (line 156): OR in location field returns 0 results — invalidates strategies in A2 and A3 |
| **Defects** | (1) API key hardcoded line 7; (2) no assertions — visual inspection only; (3) writes raw API responses including any PII in job descriptions to unprotected local files |
| **Recommendation** | **REFACTOR into test suite** |
| **Target module** | `tests/test_serpapi_integration.py` — with real key injected from env; assert on `len(results.get('jobs_results', []))` > 0 for known-good queries |

---

#### Component A7 — `search_matching_roles_since_thursday.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable |
| **Behavior** | 5 queries × 9 locations = 45 searches; `date_posted="5days"` (non-standard — may not be supported by SerpAPI); deduplicates by `job_id` (different strategy from others); extracts `via` field |
| **Defects** | (1) **Different hardcoded API key** at line 18; the value has been removed; (2) `"5days"` is not a documented SerpAPI filter value — likely silently ignored or returns error; (3) `job_id` dedup key may not be populated in all API responses |
| **Recommendation** | **ARCHIVE** |
| **Rationale** | Non-standard date filter, different API key suggests experimental one-off. Use FIXED version with `date_posted="week"`. |

---

### 3.2 SCHEDULER / CREDIT TRACKER

#### Component B1 — `smart_scheduler.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable dashboard — reads/writes `c:\ATS\credit_tracker.json` |
| **Key symbols** | `load_credit_tracker() → dict`, `save_credit_tracker(tracker)`, `record_search(script_type, credits_used, jobs_found) → dict`, `get_recommendation()`, `show_optimal_schedule()`, `main()` |
| **Behavior** | Loads/saves JSON credit ledger; computes remaining runs; prints dashboard with tiered recommendations; analyzes burn-rate from history |
| **Constants** | `BEAST_MODE_CREDITS_PER_RUN=6`, `OPTIMIZED_CREDITS_PER_RUN=27`, `COMPREHENSIVE_CREDITS_PER_RUN=132`, `TOTAL_FREE_CREDITS=250` (lines 11–14) |
| **Inputs** | `c:\ATS\credit_tracker.json` (auto-created on first run); caller passes `(script_type, credits_used, jobs_found)` to `record_search()` |
| **Outputs** | Updated JSON, stdout report |
| **Defects** | (1) `save_credit_tracker` uses `json.dump(tracker, indent=2, fp=f)` — **wrong argument order** at line 33: `json.dump(obj, fp, ...)` not `json.dump(obj, indent=, fp=)` — **this will raise `TypeError` on Python 3.x**; (2) `total_credits_available` in JSON never decremented — cosmetic bug; (3) no file locking — concurrent runs could corrupt JSON; (4) `TOTAL_FREE_CREDITS` hardcoded — should be read from tracker JSON for paid plans |
| **Testability** | `record_search` and `load_credit_tracker` are testable with temp file injection |
| **Recommendation** | **REFACTOR** — fix the `json.dump` bug first, then extract as `CreditLedger` class |
| **Target module** | `ats_local/scheduler/credit_ledger.py` |
| **Refactor actions** | (1) Fix `json.dump` arg order; (2) Add `filelock` for concurrent safety; (3) Move constants to config; (4) Integrate `record_search()` as post-hook in scraper run loop |

---

### 3.3 ATS VALIDATORS

#### Component C1 — `ats_comprehensive_validator.py` (Script-level validator)
| Attribute | Detail |
|---|---|
| **Status** | Executable — but script-level, not importable as module |
| **Behavior** | 10-test suite: prohibited chars, critical keywords, advanced keywords, quantified achievements, contact info extraction, experience chronology, section headers, bullet-7 specific validation, keyword density, file format |
| **Key data** | `PROHIBITED_CHARS` dict (lines 43–70) — 26 Unicode chars; `CRITICAL_KEYWORDS` (lines 104–115); `ADVANCED_KEYWORDS` (lines 143–158) |
| **Hardcoding** | Target file hardcoded at line 21: `r'C:\ATS\candidate_resume.docx'`; test date hardcoded line 15; `Test Date: 2026-03-20` |
| **Weighted scoring** | Lines 438–453: composite score with weights (prohibited chars 25%, critical keywords 20%, advanced 15%, etc.) |
| **Defects** | (1) Hardcoded target file path — not reusable for any other file; (2) all code at module level — `import` causes immediate execution; (3) keyword density calculation at lines 383–390 has a complex inline comprehension that mixes `dict.items()` with `isinstance` check — this will silently compute wrong density if `ADVANCED_KEYWORDS` structure changes; (4) `Location` detection at line 252 only looks for 5 Indian cities — UAE location not covered; (5) `Test 8` at line 333 is purely Candidate-specific (`BULLET7_KEYWORDS` includes proprietary bullet content) |
| **Reusable data** | `PROHIBITED_CHARS` dict is the most complete prohibited character set in the codebase; `QUANTITY_PATTERNS` regex list (lines 185–196) is reusable |
| **Recommendation** | **REFACTOR** |
| **Target module** | `ats_local/validators/ats_rules.py` (data constants), `ats_local/validators/resume_validator.py` (logic class) |
| **Refactor actions** | (1) Wrap all test logic in `class ATSValidator`; (2) Accept file path as constructor arg; (3) Extract `PROHIBITED_CHARS`, `QUANTITY_PATTERNS` to `ats_rules.py`; (4) Remove Test 8 (resume-specific) from generic validator; (5) Make keyword sets configurable per role |

---

#### Component C2 — `ats_validator.py` — `ATSValidator` class ⭐ MOST ARCHITECTURALLY MATURE
| Attribute | Detail |
|---|---|
| **Status** | Executable — proper class with `__init__`; **but Gemini client is not installed in requirements.txt** |
| **Key symbols** | `class ATSValidator`, `validate_resume(resume_path, market, role, target_companies, use_optimization) → dict`, `_optimized_validation(...)`, `_single_pass_validation(...)`, `batch_validate(resume_paths, market, role) → list`, `_extract_text(file_path) → str`, `_load_core_prompt() → dict`, `_estimate_tokens(text) → int` |
| **Behavior** | 2-step LLM validation: Gemini Flash for structural pre-check, Gemini Pro for deep analysis; batch validation mode; prompt caching placeholder |
| **Inputs** | Resume file path (DOCX/TXT, no PDF), market string, role string, optional company list |
| **Outputs** | JSON dict with scores, analysis, cost breakdown |
| **Dependencies** | `google.genai` (NOT in `requirements.txt`), `python-docx` |
| **Defects** | (1) `_load_core_prompt()` at lines 307–310 opens `c:/ATS/MASTER_ATS_VALIDATION_PROMPT.md` with a bare `open()` — no try/except, relative path assumption; (2) `_get_cached_master_prompt()` returns `None` (stub at line 338) — cache savings in cost table are fictitious; (3) `_extract_text` raises `NotImplementedError` for PDF at line 299; (4) Quick scan prompt at line 84 has a Python comment (`# First 2000 chars`) **inside the f-string body** — this will be sent verbatim to the LLM; (5) `_estimate_tokens` at line 342 uses `len(text) // 4` — rough but acceptable; (6) API key taken from `os.getenv('GEMINI_API_KEY')` at line 349 — **this is correct** and is the only file in the repo that uses env vars; (7) `market_extensions` and `role_extensions` in `_load_market_extensions` / `_load_role_extensions` are placeholder strings (lines 313–324), not loaded from files |
| **Testability** | Good — injectable `api_key`, `_extract_text` can be mocked, methods are properly encapsulated |
| **Recommendation** | **REFACTOR** |
| **Target module** | `ats_local/validators/llm_validator.py` |
| **Refactor actions** | (1) Add `google-generativeai` to `requirements.txt`; (2) Load market/role extensions from YAML/JSON config files; (3) Implement prompt caching using Gemini API; (4) Fix f-string comment leak; (5) Add PDF support via `PyPDF2`; (6) Add try/except in `_load_core_prompt` |

---

#### Component C3 — `ats_score_calculator.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable script — runs at import |
| **Behavior** | Checks resume text against 3 keyword categories (critical, high-value, AI/ML); formatting checks; content quality; weighted final score |
| **Hardcoding** | `'candidate_master_resume.txt'` (line 11 — bare filename, not absolute path); `'jobs_global_sql_server_dba.csv'` (line 16 — uses job CSV as context but only prints count); `'hotmail.com'` as contact check (line 104); `<employment-period>` as chronology check (line 113); `'17'` years (line 136) |
| **Defects** | (1) Everything hardcoded to specific person/file; (2) all code at module level; (3) contact check at line 104 (`'hotmail.com' in resume_text`) is PII-tied; (4) `check_keywords` function (lines 69–87) is the only clean, reusable function |
| **Reusable symbols** | `check_keywords(keyword_dict, category_name) → tuple[float, int, int]` (lines 69–87) — clean pattern worth extracting; keyword category dicts `critical_keywords`, `high_value_keywords`, `ai_keywords` as reusable data structures |
| **Recommendation** | **REFACTOR** — extract `check_keywords()` and keyword dicts; discard the runner |
| **Target module** | `ats_local/validators/keyword_scorer.py` |

---

#### Component C4 — `uae_ats_comprehensive_validator.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable script (module-level) |
| **Behavior** | UAE-specific validation: nationality, visa status, DOB, marital status, salary expectation, photo check; then standard keyword/character tests |
| **Key data** | `UAE_REQUIRED_FIELDS` dict (lines 57–64) — 7 UAE-specific personal fields; photo detection via `doc.part.rels` (lines 42–48) |
| **Hardcoding** | Target file: `r'C:\ATS\candidate_resume.docx'` (line 23); `<candidate-birth-year>` as DOB check (line 16 in `validate_condensed.py`); location check hardcoded to `<candidate-location>` (lines 63) |
| **Defects** | (1) Module-level execution; (2) DOB hardcoded to `<candidate-birth-year>` (line 62) — fragile; (3) marital status check includes `'single'` which would match "single-node", "single-tenant" etc. |
| **Reusable symbols** | Photo detection logic (lines 42–48) — `any("image" in rel.target_ref for rel in doc.part.rels.values())`; `UAE_REQUIRED_FIELDS` structure for market-specific validation config |
| **Recommendation** | **REFACTOR** — merge with C1/C3 into unified `ResumeValidator(market="UAE")` |

---

#### Component C5 — `validate_condensed.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable — 43-line quick-check script |
| **Behavior** | Opens hardcoded DOCX; counts paragraphs, chars, words; checks photo, nationality, visa, DOB; checks 3 keyword frequencies; prints pass/fail |
| **Hardcoding** | `r'C:\ATS\candidate_resume.docx'` (line 5); `<candidate-birth-year>` DOB (line 15) |
| **Recommendation** | **ARCHIVE** — all logic is a subset of C4; no new capability |

---

#### Component C6 — `validate_condensed_comprehensive.py`, `validate_final_resume.py`, `validate_updated_migration_resume.py`, `validate_condensed.py`, `comprehensive_ats_validation_iac.py`, `comprehensive_ats_validation_migration.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable scripts — each validates one hardcoded resume variant |
| **Pattern** | Each is a copy of C1/C4 with a different hardcoded file path and minor keyword list tweaks |
| **Recommendation** | **ARCHIVE** all — replaced by parameterized validator (C2 REFACTORED) |

---

#### Component C7 — `comprehensive_ats_validation_all_platforms.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable — has a proper `validate_comprehensive(filepath)` function |
| **Key symbols** | `validate_comprehensive(filepath)` — accepts path argument |
| **Behavior** | Most thorough character safety check: 10 Unicode categories; hyphen consistency regex; section header detection; keyword coverage; formatting and page count |
| **Defects** | (1) Function body uses `filepath` arg correctly — no hardcoding!; (2) However, called with hardcoded path if invoked directly (no `__main__` guard visible in snippet) |
| **Reusable symbols** | `prohibited_chars` dict structure (lines 38–49) with Unicode codepoints grouped by category — most systematic in codebase; `validate_comprehensive(filepath)` is the only validator with a proper function signature |
| **Recommendation** | **REFACTOR** — this is the best starting point for a generic ATS validator |
| **Target module** | `ats_local/validators/resume_validator.py::validate_comprehensive(filepath, rules_config)` |

---

### 3.4 KEYWORD ANALYZERS

#### Component D1 — `keyword_density_analysis.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable script (module-level) |
| **Key symbols** | `analyze_resume(file_path) → dict` (lines 4–60) |
| **Behavior** | Opens DOCX, counts 30 keyword instances, computes density percentage, estimates pages, rates density vs 15–25% optimal target |
| **Outputs** | Platform-specific keyword coverage for Bayt.com, Naukrigulf, GulfTalent |
| **Reusable symbols** | `analyze_resume()` returns clean dict — good building block; keyword list is UAE DBA-specific but easily parameterized |
| **Defects** | (1) Hardcoded target file `r'C:\ATS\candidate_resume.docx'` at line 67; (2) density formula at line 51 counts raw string occurrences divided by word count — over-counts multi-word phrases; (3) emoji characters in output (line 123: `⬆️⬆️⬆️`) — ironic given ATS prohibited char rules |
| **Recommendation** | **REFACTOR** — extract `analyze_resume(path, keywords_config) → dict` |
| **Target module** | `ats_local/validators/keyword_density.py` |

---

#### Component D2 — `keyword_density_optimization_plan.md`
| Attribute | Detail |
|---|---|
| **Status** | **Generated artifact / proposal document** — not executable |
| **Recommendation** | **ARCHIVE** — informational only |

---

#### Component D3 — `extract_keywords_and_search.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable |
| **Key symbols** | `extract_keywords_from_resume() → dict` (lines 9–80+) |
| **Behavior** | Reads DOCX, counts ~50 keyword occurrences, detects experience level, extracts role patterns; then calls SerpAPI to search jobs based on extracted keywords |
| **Architecture** | Good pipeline concept: resume → extract keywords → drive search queries |
| **Defects** | (1) Hardcoded file `'C:/ats/candidate_resume.docx'` (line 16); (2) combines keyword extraction and job searching in one script — should be separate modules; (3) `re.findall(keyword, ...)` at line 57 with unescaped keywords — `"Query Store"`, `"SQL Server"` etc. could match partial words |
| **Recommendation** | **REFACTOR** — split into keyword extractor + search driver |
| **Target modules** | `ats_local/resume/keyword_extractor.py`, `ats_local/scraper/query_builder.py` |

---

#### Component D4 — `alwayson_summary_analysis.py`, `compare_three_resumes.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable one-shot analysis scripts |
| **Recommendation** | **ARCHIVE** — single-use analysis, no reusable logic |

---

### 3.5 DOCX RESUME GENERATORS

There are **~35 DOCX generator scripts** (`create_*.py`). They all share the same architectural pattern:

**Common pattern across all `create_*.py` scripts:**
```python
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()
# Set margins (0.5–0.6 inches)
for section in doc.sections:
    section.top_margin = Inches(0.5)
# Hardcoded content inline: name, title, contact, summary, skills, experience, education
doc.save(r'C:\ATS\<output_filename>.docx')
```

**Full inventory of create_* scripts and disposition:**

| File | Unique feature | Recommendation |
|---|---|---|
| `create_final_resume_v2.py` | Reads from `.txt` file, converts to formatted DOCX (lines 25–96) | **REFACTOR** — text-to-DOCX converter is reusable |
| `legacy_resume_builder.py` | Full inline DOCX from code; most complete formatting example | **REFACTOR** — extract formatting helpers |
| `legacy_resume_builder_variant.py`, `legacy_resume_builder_variant.py` | Variants of SQL Architect resume | **ARCHIVE** |
| `legacy_resume_builder_variant.py`, `legacy_resume_builder_variant.py` | SRE variants | **ARCHIVE** |
| `create_Database_Architect_resume.py`, `_v2.py`, `_FINAL.py`, `_2PAGE_STRICT.py`, `_FINAL_2PAGE.py` | DB Architect versions | **ARCHIVE** (keep only FINAL_2PAGE) |
| `create_final_resume.py`, `create_final_2page_resume.py` | Earlier final versions | **ARCHIVE** |
| `create_UAE_resume.py`, `create_UAE_resume_CONDENSED.py` | UAE-specific variants | **ARCHIVE** — CONDENSED is latest |
| `create_VERSION_A_docx.py` | Version A 2-page variant | **ARCHIVE** |
| `create_BALANCED_2page_resume.py` | 2-page balanced | **ARCHIVE** |
| `create_MERGED_COMPLETE_2page_resume.py` | Merged content | **ARCHIVE** |
| `create_FIS_resume_docx.py` | FIS-specific role | **ARCHIVE** |
| `create_Azure_Cloud_Architect_resume.py` | Azure Cloud role | **ARCHIVE** |
| `create_UPDATED_master_resume.py`, `create_updated_resume_with_migration.py` | Master with IaC | **ARCHIVE** |
| `create_fixed_resume.py`, `create_proper_word_resume.py`, `create_resume_with_hyperlinks.py` | One-off fixes | **ARCHIVE** |
| `create_pdf.py` | Tries `reportlab`, falls back | **ARCHIVE** |
| `legacy_resume_builder.py` | See above | **REFACTOR** |

**Key reusable DOCX helper patterns** found across these scripts:

```python
# Pattern 1: Add formatted section heading (repeated in every create_* script)
# Source: legacy_resume_builder.py:47-51
def add_section_heading(doc, text, font_size=11):
    h = doc.add_paragraph(text)
    h.runs[0].font.bold = True
    h.runs[0].font.size = Pt(font_size)
    h.space_after = Pt(3)

# Pattern 2: Add bullet point (repeated in every create_* script)
def add_bullet(doc, text, font_size=10, indent_level=0):
    p = doc.add_paragraph(text, style='List Bullet')
    for run in p.runs:
        run.font.size = Pt(font_size)
        run.font.name = 'Calibri'

# Pattern 3: Set document margins (identical in ALL 35 scripts)
def set_margins(doc, top=0.5, bottom=0.5, left=0.6, right=0.6):
    for section in doc.sections:
        section.top_margin = Inches(top)
        section.bottom_margin = Inches(bottom)
        section.left_margin = Inches(left)
        section.right_margin = Inches(right)
```

**REFACTOR target**: `ats_local/docx_builder/helpers.py` — extract the 4–5 common helper functions; then the resume generator becomes a thin data-driven template.

---

### 3.6 TEXT EXTRACTORS

#### Component E1 — `extract_all_resumes.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable — dynamically installs missing packages at runtime (lines 9–18) |
| **Key symbols** | `extract_text_from_docx(docx_path) → str`, `extract_text_from_pdf(pdf_path) → str`, `main()` |
| **Behavior** | Glob-scans `candidate_resume*.docx` and `*.pdf`; extracts text; writes to `extracted_resume_texts/` |
| **Defects** | (1) `subprocess.check_call([sys.executable, "-m", "pip", "install", package])` at line 16 — runtime pip install is an antipattern; (2) `import PyPDF2` — deprecated, replaced by `pypdf`; (3) uses `Path.cwd()` not a fixed path — behaviour changes based on where script is launched from |
| **Reusable symbols** | `extract_text_from_docx()` and `extract_text_from_pdf()` — clean, exception-handled functions |
| **Recommendation** | **REFACTOR** — extract the two text-extraction functions |
| **Target module** | `ats_local/resume/text_extractor.py` (merge with `ATSValidator._extract_text`) |

---

#### Component E2 — `rename_resume_standard.py`
| Attribute | Detail |
|---|---|
| **Status** | Executable |
| **Behavior** | Renames resume files to standard naming convention |
| **Recommendation** | **ARCHIVE** — one-time utility, no ongoing value |

---

### 3.7 LINKEDIN / CONTENT GENERATORS

| File | Status | Recommendation |
|---|---|---|
| `generate_linkedin_INTEGRATED_FINAL.py` | Executable DOCX generator | **ARCHIVE** — generated artifact |
| `generate_linkedin_profile_UNIQUE_HIGH_IMPACT.py` | Executable DOCX generator | **ARCHIVE** |
| `generate_linkedin_profile_karthick_style.py` | Executable DOCX generator | **ARCHIVE** |
| `generate_wsa_email.py` | Executable, generates email text | **ARCHIVE** |
| `append_learnings_to_master_prompt.py` | Executable, appends text to MD file | **ARCHIVE** |

---

### 3.8 PATCH/FIX SCRIPTS

| File | Behavior | Recommendation |
|---|---|---|
| `patch_resume.py` | Opens DOCX, modifies specific text | **ARCHIVE** — one-off fix |
| `patch_bi.py` | BI section patch | **ARCHIVE** |
| `fix_pb.py` | PowerBI fix | **ARCHIVE** |
| `fix_uae_whatsapp.py` | WhatsApp field add | **ARCHIVE** |
| `add_alwayson_to_resume.py`, `_fixed.py` | Add AlwaysOn bullet | **ARCHIVE** |
| `add_contact_to_uae.py`, `add_whatsapp_*.py` | Contact field patches | **ARCHIVE** |
| `add_iac_content_to_resume.py` | IaC bullet add | **ARCHIVE** |
| `update_migration_resume_with_iac.py` | Migration content | **ARCHIVE** |
| `update_uae_resume.py` | UAE update | **ARCHIVE** |

---

### 3.9 PDF CONVERTERS

| File | Dependencies | Recommendation |
|---|---|---|
| `convert_to_pdf.py`, `convert_final_resume_v2_to_pdf.py`, etc. | `reportlab`, `docx2pdf`, or PowerShell | **ARCHIVE** — use a single `pdf_converter.py` with `docx2pdf` |
| `markdown_to_pdf_simple.py` | `markdown2`, `weasyprint` | **ARCHIVE** |

---

### 3.10 ARCHITECTURE DOCUMENTS — Proposals vs. Executable Code

These are **markdown files describing the planned RAG system**. They contain embedded SQL and Python code snippets that are **not executable as-is** but represent the authoritative design spec.

| File | Status | Value |
|---|---|---|
| `RAG_JOB_SEARCH_ARCHITECTURE_REVIEW.md` | **Design proposal** | HIGH — defines SQL Server 2025 schema, vector search queries, recommended API sources |
| `RAG_MASTER_PROMPT.md` | **Design proposal** | HIGH — defines LLM prompt contract, zero-hallucination rules, ATS compliance rules |
| `RAG_Architecture.html` / `RAG_Architecture_Diagram.md` | **Diagrams** | MEDIUM — visual reference |
| `RAG_EXTENSION_SUMMARY.md`, `RAG_SEARCH_OPTIMIZATION_STRATEGY.md` | **Proposals** | MEDIUM |
| `RAG_SYSTEM_DFD_DIAGRAMS.md` | **Data flow diagrams** | MEDIUM |
| `MASTER_ATS_VALIDATION_PROMPT.md` | **Prompt template** | HIGH — loaded by `ats_validator.py::_load_core_prompt()` |
| `Job Search System.html` | **Generated HTML artifact** | ARCHIVE |
| All candidate-specific resume and cover-letter variants | **Generated artifacts** | ARCHIVE |
| `DBA_Job_Data_Tables_2026.csv` | **Data file** | Keep as reference test fixture |
| `jobs_global_sql_server_dba.csv`, `jobs_last_24_hours.csv` | **Output data files** | Keep for RAG seeding |

---

## 4. CONSOLIDATED RECOMMENDATION TABLE

| File | Classification | Recommendation | Target Module |
|---|---|---|---|
| `google_jobs_scraper.py` | Executable | **ARCHIVE** | — |
| `google_jobs_scraper_optimized.py` | Executable | **ARCHIVE** | — |
| `google_jobs_scraper_beast_mode.py` | Executable | **REFACTOR** (extract 2 functions) | `ats_local/scraper/utils.py` |
| `google_jobs_scraper_comprehensive.py` | Executable | **ARCHIVE** | — |
| `google_jobs_scraper_FIXED.py` | Executable ⭐ | **REFACTOR** | `ats_local/scraper/serpapi_fetcher.py` |
| `debug_serpapi.py` | Executable | **REFACTOR** → test suite | `tests/test_serpapi_integration.py` |
| `search_matching_roles_since_thursday.py` | Executable | **ARCHIVE** | — |
| `smart_scheduler.py` | Executable (has bug) | **REFACTOR** (fix json.dump) | `ats_local/scheduler/credit_ledger.py` |
| `ats_comprehensive_validator.py` | Executable (script-level) | **REFACTOR** | `ats_local/validators/resume_validator.py` |
| `ats_validator.py` — `ATSValidator` | Executable class ⭐ | **REFACTOR** | `ats_local/validators/llm_validator.py` |
| `ats_score_calculator.py` | Executable (script-level) | **REFACTOR** (extract fn) | `ats_local/validators/keyword_scorer.py` |
| `uae_ats_comprehensive_validator.py` | Executable (script-level) | **REFACTOR** (merge into C1) | `ats_local/validators/resume_validator.py` |
| `validate_condensed.py` | Executable | **ARCHIVE** | — |
| `validate_condensed_comprehensive.py` | Executable | **ARCHIVE** | — |
| `validate_final_resume.py` | Executable | **ARCHIVE** | — |
| `validate_updated_migration_resume.py` | Executable | **ARCHIVE** | — |
| `comprehensive_ats_validation_all_platforms.py` | Executable ⭐ | **REFACTOR** | `ats_local/validators/resume_validator.py` |
| `comprehensive_ats_validation_iac.py` | Executable | **ARCHIVE** | — |
| `comprehensive_ats_validation_migration.py` | Executable | **ARCHIVE** | — |
| `keyword_density_analysis.py` | Executable | **REFACTOR** | `ats_local/validators/keyword_density.py` |
| `extract_keywords_and_search.py` | Executable | **REFACTOR** (split) | `ats_local/resume/keyword_extractor.py` |
| `alwayson_summary_analysis.py` | Executable | **ARCHIVE** | — |
| `compare_three_resumes.py` | Executable | **ARCHIVE** | — |
| `create_final_resume_v2.py` | Executable | **REFACTOR** | `ats_local/docx_builder/txt_to_docx.py` |
| `legacy_resume_builder.py` | Executable | **REFACTOR** (extract helpers) | `ats_local/docx_builder/helpers.py` |
| All other `create_*.py` (33 files) | Executable | **ARCHIVE** | — |
| `extract_all_resumes.py` | Executable | **REFACTOR** | `ats_local/resume/text_extractor.py` |
| `rename_resume_standard.py` | Executable | **ARCHIVE** | — |
| All `generate_linkedin_*.py` | Executable | **ARCHIVE** | — |
| All `patch_*.py`, `fix_*.py`, `add_*.py`, `update_*.py` | Executable | **ARCHIVE** | — |
| All `convert_*.py` | Executable | **ARCHIVE** | — |
| `RAG_JOB_SEARCH_ARCHITECTURE_REVIEW.md` | Design proposal | **REUSE_AS_IS** (spec) | Reference |
| `RAG_MASTER_PROMPT.md` | Design proposal | **REUSE_AS_IS** (prompt) | `ats_local/prompts/master_prompt.md` |
| `MASTER_ATS_VALIDATION_PROMPT.md` | Prompt template | **REUSE_AS_IS** | `ats_local/prompts/ats_validation_prompt.md` |
| `requirements.txt` | Config | **REPLACE** | See below |
| `smart_scheduler.py` strategy constants | Config data | **REFACTOR** | `ats_local/config/scraper_config.yaml` |

---

## 5. REQUIREMENTS.TXT — STATUS

**Current content** (`requirements.txt:1–2`):
```
google-search-results==2.4.2
```

**Critical gaps:**
- `python-docx` — used by every validator and generator — **missing**
- `google-generativeai` — used by `ats_validator.py` — **missing**
- `PyPDF2` — used by `extract_all_resumes.py` (deprecated, should be `pypdf`)
- `sentence-transformers` — required by RAG architecture
- `requests`, `tenacity`, `filelock`, `python-dotenv` — all needed for production

**Replacement `requirements.txt`:**
```
google-search-results==2.4.2    # SerpAPI
python-docx>=1.1.0              # DOCX read/write
pypdf>=4.0.0                    # PDF extraction (replaces deprecated PyPDF2)
google-generativeai>=0.5.0      # Gemini LLM
sentence-transformers>=2.7.0    # Local embeddings
python-dotenv>=1.0.0            # Secret management
tenacity>=8.2.0                 # Retry logic
filelock>=3.13.0                # Safe concurrent file access
requests>=2.31.0                # HTTP client
```

---

## 6. PROPOSED TARGET MODULE STRUCTURE

```
ats_local/
├── config/
│   └── scraper_config.yaml          # queries, locations, credit limits (from smart_scheduler.py constants)
├── scraper/
│   ├── serpapi_fetcher.py           # Refactored from google_jobs_scraper_FIXED.py
│   └── utils.py                     # deduplicate_jobs(), classify_region() from beast_mode.py
├── scheduler/
│   └── credit_ledger.py             # Refactored from smart_scheduler.py (fix json.dump bug)
├── validators/
│   ├── ats_rules.py                 # PROHIBITED_CHARS, QUANTITY_PATTERNS, keyword lists
│   ├── resume_validator.py          # Class from comprehensive_ats_validation_all_platforms.py
│   ├── llm_validator.py             # Refactored ATSValidator class from ats_validator.py
│   └── keyword_scorer.py            # check_keywords() + keyword dicts from ats_score_calculator.py
├── resume/
│   ├── text_extractor.py            # extract_text_from_docx/pdf from extract_all_resumes.py
│   └── keyword_extractor.py         # extract_keywords_from_resume() from extract_keywords_and_search.py
├── docx_builder/
│   ├── helpers.py                   # set_margins(), add_section_heading(), add_bullet()
│   └── txt_to_docx.py               # Text-to-DOCX converter from create_final_resume_v2.py
└── prompts/
    ├── master_prompt.md             # Copied from RAG_MASTER_PROMPT.md
    └── ats_validation_prompt.md     # Copied from MASTER_ATS_VALIDATION_PROMPT.md
tests/
└── test_serpapi_integration.py      # Refactored from debug_serpapi.py (inject key from env)
.env.example                         # SERPAPI_KEY=, GEMINI_API_KEY= (keys removed from all source files)
```

---

## 7. PRIORITY BUG-FIX LIST (Before Any Refactor)

| Priority | File | Line | Bug | Fix |
|---|---|---|---|---|
| **P0 SECURITY** | All 6 scraper files | 7–18 | Hardcoded SerpAPI key | `os.getenv("SERPAPI_KEY")` |
| **P0 RUNTIME** | `smart_scheduler.py` | 33 | `json.dump(tracker, indent=2, fp=f)` — wrong kwarg order, will raise `TypeError` | `json.dump(tracker, f, indent=2)` |
| **P1 DATA** | `google_jobs_scraper.py` | 80–97 | Pagination block duplicates job dict construction | Extract to helper function |
| **P1 LOGIC** | `ats_validator.py` | 84 | Python comment inside f-string literal sent to LLM | Remove `# First 2000 chars` from f-string |
| **P1 MISSING** | `ats_validator.py` | 349 | `google-generativeai` not in requirements.txt | Add to requirements.txt |
| **P2 LOGIC** | `google_jobs_scraper_beast_mode.py` / `_optimized.py` | 32–47 / 32–49 | OR in SerpAPI location field returns 0 results | Switch to individual locations (FIXED pattern) |
| **P2 LOGIC** | `search_matching_roles_since_thursday.py` | 71 | `"5days"` is not a valid SerpAPI `chips` value | Use `"week"` |
| **P2 USABILITY** | `google_jobs_scraper_comprehensive.py` | 157 | `input()` blocks automated runs | Remove; accept `--yes` CLI flag |
| **P3 QUALITY** | Multiple validators | various | All validators are module-level scripts (run on import) | Wrap in `if __name__ == "__main__"` + extract functions |

---

## 8. CLASSIFICATION SUMMARY

| Category | Count | REUSE_AS_IS | REFACTOR | REPLACE | ARCHIVE |
|---|---|---|---|---|---|
| Scrapers | 7 | 0 | 2 (FIXED + beast utils) | 0 | 5 |
| Scheduler | 1 | 0 | 1 | 0 | 0 |
| ATS Validators | 9 | 0 | 4 | 0 | 5 |
| Keyword Analyzers | 3 | 0 | 2 | 0 | 1 |
| DOCX Generators | ~35 | 0 | 2 | 0 | ~33 |
| Text Extractors | 2 | 0 | 1 | 0 | 1 |
| PDF Converters | ~6 | 0 | 0 | 1 consolidated | ~5 |
| Patch/Fix Scripts | ~12 | 0 | 0 | 0 | ~12 |
| LinkedIn Generators | ~5 | 0 | 0 | 0 | ~5 |
| Architecture Docs | ~8 | 5 | 0 | 0 | 3 |
| Requirements.txt | 1 | 0 | 0 | 1 | 0 |
| **TOTAL** | **~89** | **5** | **12** | **2** | **~70** |

**Bottom line:** ~12 components are worth carrying forward into the RAG system. The other ~70 are single-purpose generated artifacts or superseded script versions that should be moved to an `archive/` subdirectory to keep the working directory clean. The most important immediate actions are: (1) rotate and remove the hardcoded SerpAPI keys, (2) fix the `json.dump` bug in `smart_scheduler.py`, and (3) add `python-docx` and `google-generativeai` to `requirements.txt`.


