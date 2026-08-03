# ATS Local RAG Assistant — Security, Privacy, Operations, Deployment, Observability, Dependencies, and Developer Environment

**Version:** 1.0  
**Date:** 2026-08-01  
**Classification:** Private / single-user system  
**System root:** `C:\ATS`  
**Status:** Operational baseline and implementation requirements; it distinguishes observed components from proposed controls.

## 1. Scope and evidence

This guide consolidates:

- The architecture review and DFDs in `C:\ATS\RAG_JOB_SEARCH_ARCHITECTURE_REVIEW.md`, `RAG_Architecture_Diagram.md`, and `RAG_SYSTEM_DFD_DIAGRAMS.md`.
- The target architecture artifact `1785584781384-copilot-tool-output-258847.txt`.
- The implementation reuse audit `1785572792951-copilot-tool-output-6e9a79.txt`.
- The synthesis report and local-model research in `1785552803811-copilot-tool-output-3d97ee.txt` and `1785507811564-copilot-tool-output-8f10ea.txt`.
- Direct inspection of `C:\ATS` and the host on 2026-08-01.

### 1.1 Observed baseline

| Item | Observed state | Required target |
|---|---|---|
| Code organization | About 80 independent scripts; no application package, tests, CI, shared configuration, or structured logging | `ats_local` package, migrations, tests, configuration, deployment scripts |
| Python | 3.12.10; pip 25.0.1 | Install and pin Python 3.11.x per the canonical development baseline |
| Requirements | Only `google-search-results==2.4.2` is declared | Complete direct dependency file and hash-locked transitive file |
| SQL Server | SQL Server 2022 Developer 16.0.1190.2 running; no `JobSearchRAG` database found | SQL Server 2022 relational system of record plus local Qdrant vector projection |
| SQL connectivity | Default service runs; no listener observed on TCP 1433; Browser disabled; Agent disabled | Prefer local named pipes/shared memory, or explicitly configure loopback TCP |
| Ollama | Not installed; no process/listener | Install and bind to loopback only |
| infinity-emb | Not installed; no process/listener | Optional embedding/reranking sidecar, loopback only |
| WSL2 | Not installed | Optional profile only; not needed for the default Windows-native profile |
| Secrets | SerpAPI credentials are hardcoded in multiple scripts | Rotate immediately; Windows Credential Manager/DPAPI |
| Scheduler | Scheduling is designed and `smart_scheduler.py` exists, but it is a credit ledger, not verified Task Scheduler orchestration | Registered tasks with non-interactive preflight, overlap control, and history |
| Current RAG | SerpAPI scraping and DOCX/ATS utilities exist; most retrieval, local inference, tracking, DLQ, and feedback components are proposed | Implement in phased gates below |

**Do not treat architecture diagrams as proof of implementation.** In particular, local Qwen models, BGE-M3, infinity-emb, SQL vector tables, BM25/RRF, reranking, NLI verification, and the application feedback loop were not found as working application components.

## 2. Security architecture

### 2.1 Assets and security objectives

Critical assets are: resume and contact data; employment history; work-authorization and salary preferences; job/application history; generated resumes; LinkedIn session material; API keys; SQL credentials; model prompts and outputs; provenance evidence; and backups.

Security objectives:

1. Resume content and credentials remain local unless an explicit, documented external call is approved.
2. No automatic application submission or LinkedIn account action.
3. Every generated claim is grounded in candidate facts and approved by the user.
4. External content is untrusted data, never instructions.
5. A compromised source, model, or dependency cannot silently modify approved artifacts.
6. Operations are auditable without logging PII or secrets.

### 2.2 Trust boundaries

```text
Internet / untrusted
  SerpAPI, public RSS/ATS endpoints, optional LinkedIn pages, package/model registries
       | HTTPS; validate size, type, schema, redirects, and rate limits
------- TB1: Internet to host -------------------------------------------------
Windows host / user boundary
  Scheduler -> Python application -> local files
       |              | loopback HTTP        | local DB protocol
       |              +-> Ollama             +-> SQL Server
       |              +-> infinity-emb
------- TB2: user process to privileged/local services ------------------------
Sensitive data stores
  SQL database, output DOCX/PDF, embedding cache, DLQ, logs, backups, credentials
------- TB3: live data to backup/removable/synced storage ---------------------
Optional WSL2 VM
  Linux Python/infinity/vLLM; Windows files only through explicit mounts
------- TB4: Windows to WSL2 virtualized/network boundary ---------------------
Human approval boundary
  Draft/flagged content -> explicit approve -> export/application record
```

Only the interactive user crosses the approval boundary. Scheduled jobs may ingest, parse, embed, and rank; they must not export a final resume, send a message, authenticate to LinkedIn, or submit an application.

### 2.3 Threat model

| Threat | Example | Required controls |
|---|---|---|
| Credential disclosure | Existing plaintext SerpAPI keys; `.env`, logs, crash dump, or synced folder leaks | Rotate exposed keys; Credential Manager; secret redaction; deny cloud sync; restricted ACL |
| Session theft | `li_at` or Playwright storage state copied from JSON | LinkedIn disabled by default; DPAPI-protect storage; short retention; user-only ACL; never log cookies |
| Prompt injection | Job description says to reveal resume or run commands | Treat source text as quoted data; no tools in model session; fixed system policy; schema allowlist; output validation |
| SQL injection | Vector JSON interpolated into SQL | Parameterized `pyodbc`; fixed stored procedures; least-privilege login; no dynamic SQL from model output |
| SSRF/file abuse | Malicious URL, redirect, `file:` URI, oversized document | Allow `https`; host/source allowlist; redirect cap; DNS/IP validation; byte/time limits; MIME and parser validation |
| Malicious document | Crafted DOCX/PDF exploits parser | Patch parsers; process in low-privilege account; reject macros; size/page limits; Defender scan |
| Dependency/model tampering | Typosquat, changed wheel, poisoned model revision | Hash locks; approved indexes; signed installers; model revision/SHA; SBOM and vulnerability/license scans |
| Local lateral access | Another account reads resumes/database/backups | NTFS ACL, BitLocker, separate service identities, local firewall, no broad shares |
| Model hallucination | Invented metric/employer/skill | Fact IDs, numeric/entity allowlist, NLI check, human approval, immutable provenance |
| Replay/duplicate processing | Scheduler overlap or retry creates duplicate jobs/applications | Run lock, idempotency keys, unique constraints, state machine, transactional outbox |
| Resource exhaustion | Huge JD, inference concurrency, retry storm | Input/token limits, bounded queue, one worker by default, timeout/circuit breaker, disk thresholds |
| Data loss/ransomware | SQL/file corruption or device loss | Encrypted versioned backups, restore drills, offline copy, checksum manifests |
| Overcollection/legal risk | Authenticated LinkedIn scraping or excessive PII retention | Public/API sources first; manual URL-only mode; purpose limitation; retention jobs; source/license ledger |

### 2.4 Required secure defaults

- Bind all local HTTP services to `127.0.0.1`, not `0.0.0.0`.
- Windows Firewall must block inbound access to application, Ollama, infinity-emb, and SQL ports.
- Run Python, Ollama, and infinity-emb as the normal user or dedicated unprivileged service accounts. Do not run as Administrator.
- Use Windows Integrated Authentication for SQL. The application identity receives `CONNECT`, required table DML, and migration-free execution rights only. A separate admin identity runs migrations/backups.
- Parameterize every query. Model output is never executable SQL, PowerShell, template code, path, or URL without deterministic validation.
- Validate JSON against a versioned schema and reject unknown fields.
- Normalize output paths and require them to remain beneath configured roots.
- Cap source documents, prompts, output tokens, retries, batch sizes, and process duration.
- Keep Windows Defender, SQL Server, Python, browsers/Playwright, Ollama, and drivers patched.

## 3. Secrets and session security

### 3.1 Immediate incident response

The reuse audit found two plaintext SerpAPI credentials across multiple scraper scripts. Treat both as compromised:

1. Revoke/rotate them at the provider.
2. Remove literals from all scripts and history before any repository is published.
3. Search source, logs, CSV/JSON, command history, backups, and synced copies for credential patterns.
4. Review provider usage for unauthorized requests.
5. Add secret scanning before commits and releases.

Never reproduce a secret in documentation, tickets, logs, tests, or sample configuration.

### 3.2 Storage hierarchy

1. **Preferred:** Windows Credential Manager through `keyring`.
2. **Acceptable for unattended tasks:** DPAPI-protected secret file tied to a dedicated scheduler account, with an ACL allowing only that account and SYSTEM.
3. **Development fallback only:** `.env`, excluded from source control and backup/sync, with user-only ACL. It must contain placeholders in `.env.example`.

Credential names: `ATS/SERPAPI_KEY`, `ATS/SQL_DSN` only if Integrated Authentication is impossible, and `ATS/LINKEDIN_STORAGE_STATE` only when the optional connector is explicitly enabled.

### 3.3 LinkedIn sessions

- Default `LINKEDIN_ENABLED=false`.
- Do not automate authenticated search, messaging, connection requests, applications, CAPTCHA handling, or access-control evasion.
- Do not collect people/profile data. A user-supplied public job URL may be fetched manually only after current terms and legal basis are reviewed.
- Prefer SerpAPI, employer ATS APIs, Greenhouse/Lever endpoints, and RSS.
- Never ask for or store a LinkedIn password.
- If a Playwright storage state is exceptionally authorized, encrypt it with DPAPI, bind it to the interactive user, store it outside `C:\ATS` and cloud-synced folders, ACL it to that user, and delete it after at most 24 hours or immediately after use.
- Any account challenge, `429`, consent page, robots denial, selector drift, or unexpected login page is a hard stop—no retries intended to bypass controls.
- Record source URL, acquisition time, collection method, and policy basis without recording cookies.

## 4. Privacy and data governance

### 4.1 PII classification

| Class | Examples | Handling |
|---|---|---|
| P0 public/non-personal | Public job descriptions, model/version metadata, aggregate service health | Normal integrity controls; source attribution |
| P1 internal operational | Configuration without secrets, run IDs, counts, latency, non-sensitive error codes | User-only by default; may enter logs |
| P2 personal/confidential | Name, email, phone, location, employment/education, resume text, application choices, recruiter interactions | Encrypt at rest; strict ACL; redact logs; purpose-limited retention |
| P3 highly sensitive/credential | API keys, session cookies, passwords, work authorization/visa, salary, DOB, marital status, nationality, private notes | Credential store or encrypted columns/files; never log; minimum collection; explicit consent |

Embeddings derived from P2/P3 text remain personal data: inversion/linkage risk means they receive the same classification as their source.

### 4.2 Collection and use

- Collect only fields necessary for matching, grounded resume creation, and outcome tracking.
- UAE-market fields such as DOB, marital status, nationality, visa, and photo are optional, market-specific, and disabled by default. They must never affect ranking unless the user explicitly configures a lawful need.
- Do not infer protected traits or use them for scoring.
- Separate raw source, normalized fact, inferred/adjacent skill, and user-confirmed fact. Inferences are never emitted as experience claims.
- Provide export, correction, and deletion commands by `CandidateID`, `ApplicationID`, and date range.

### 4.3 Encryption and ACLs

- Enable BitLocker for the OS/data volume and recovery-key governance.
- Use EFS only as a supplemental user-bound control; ensure recovery planning before use.
- SQL Server: prefer Windows authentication; protect data and log files with volume encryption. If TDE is enabled, back up and separately protect its certificate/private key.
- Backups must be encrypted (`WITH ENCRYPTION`) and protected by a key not stored beside the backup.
- Example ACL policy: owner and dedicated task identity = Modify; Administrators and SYSTEM = Full Control; remove inherited broad Users access. Validate with `icacls`.
- Keep `outputs`, `data`, `dlq`, `logs`, `backups`, and model caches outside OneDrive or other synchronization unless separately encrypted and approved.

### 4.4 Retention schedule

| Data | Default retention |
|---|---|
| Raw API payloads and rejected/DLQ payloads | 14 days; 30 days only while debugging |
| Active job postings | While active plus 90 days |
| Inactive job text/embeddings | 180 days, then delete or aggregate |
| Generated draft resumes | 90 days unless linked to an application |
| Approved/application resume and provenance | Application life plus 2 years, user-configurable |
| Application/outcome history | 2 years; retain longer only for an explicit analytics purpose |
| Operational logs | 30 days |
| Metrics/traces | 90 days; no raw PII |
| LinkedIn session state | Maximum 24 hours; preferably one session |
| Encrypted backups | Daily 30 days, weekly 12 weeks, monthly 12 months |

Deletion must remove relational rows, file outputs, lexical indexes, embedding cache entries, DLQ copies, and later expire backup copies. Record a non-PII deletion audit event.

## 5. Supply-chain controls

1. Use a dedicated virtual environment; never install packages globally.
2. Declare direct dependencies in `requirements.in`; compile `requirements.lock` with exact transitive versions and hashes using `pip-compile --generate-hashes`.
3. Install production with `pip install --require-hashes -r requirements.lock`.
4. Use only approved PyPI/index URLs; disable dependency confusion by avoiding unscoped private-package names.
5. Run `pip-audit`, an SBOM generator such as CycloneDX, a license allow/deny check, and secret scanning in CI and before releases.
6. Pin Git dependencies to immutable commits; do not install from mutable branches.
7. Pin Hugging Face models to immutable revisions and record repository, revision, file SHA-256, weight format, quantization, tokenizer, license, and retrieval date in `models.lock.json`.
8. Verify Authenticode/signatures and checksums for Python, Ollama, SQL Server, ODBC Driver 18, and GPU drivers.
9. Review model cards for training/use restrictions. A permissive serving library license does not override a model's license.
10. Monthly patch review; expedited update for exploitable critical vulnerabilities. Test, back up, deploy, observe, and retain rollback artifacts.

## 6. Observability

### 6.1 Logging

Use JSON structured logs with UTC timestamps:

`timestamp`, `level`, `service`, `version`, `environment`, `run_id`, `trace_id`, `stage`, `operation`, `attempt`, `duration_ms`, `status`, `error_code`, and safe counters.

Do not log resume/job text, prompts, generated bullets, URLs containing query tokens, headers, cookies, connection strings, email, phone, salary, work authorization, or model chain-of-thought. Apply key-name and pattern redaction before serialization. Hash stable entity IDs with a local salt if correlation is required.

Write rotating files to `%LOCALAPPDATA%\ATS\logs` and warning/error summaries to Windows Event Log source `ATS-RAG`. Restrict logs to the application identity. A local-only setup may use `structlog` plus rotating handlers; OpenTelemetry is recommended once multiple processes exist.

### 6.2 Metrics

| Area | Core metrics |
|---|---|
| Scheduler | run count/status, last success age, duration, overlap prevented |
| Ingestion | requests/source, credits remaining, HTTP status, new/duplicate/rejected/DLQ jobs |
| Parsing | documents, schema failures, truncations, invalid fields |
| Embedding | requests, batch size, cache hit ratio, latency, vector dimension mismatch |
| Inference | requests/model, queue depth, time-to-first-token, total latency, token counts, timeout/retry/schema-failure/fallback rates |
| Database | connection failures, query latency, deadlocks, transaction rollbacks, DB/data/log size |
| Ranking | candidate counts by stage, unknown hard gates, Top-10 generation latency |
| Safety | unsupported claims, numeric/entity mismatches, human rejection/edit rates |
| Resources | CPU, RAM, GPU VRAM/utilization, disk free, model/cache/log sizes |
| Outcomes | applications/callbacks by non-sensitive cohort; calibration only after enough labels |

Avoid high-cardinality labels such as job URL, company, candidate, prompt, or error text.

### 6.3 Tracing

Create one trace per scheduled or interactive run. Propagate W3C trace context through Python, infinity-emb, Ollama calls, and SQL spans where supported. Record only operation names and IDs—not content. Suggested spans:

`preflight -> fetch -> validate -> deduplicate -> persist_raw -> parse -> embed -> index -> retrieve_sparse -> retrieve_dense -> rrf -> rerank -> score -> report`, and separately `fact_retrieve -> rewrite -> entity_check -> nli_check -> human_gate -> docx_export`.

### 6.4 Alerts and service-level objectives

| Alert | Threshold / response |
|---|---|
| Daily pipeline missing | No successful run for 26 hours |
| Repeated failure | Two consecutive failures or failure rate >20% in 1 hour |
| Source throttling | Any 401/403; three 429s in 15 minutes; open circuit and stop |
| DLQ growth | >10 items/run or oldest item >24 hours |
| SQL unavailable | Three failed checks over 5 minutes |
| Model unavailable | Three failed checks over 5 minutes; deterministic stages may continue |
| Schema/grounding regression | >5% invalid model JSON or >10% unsupported claims |
| Capacity | Disk <15% or <20 GB; memory/VRAM >90% for 10 minutes |
| Backup | No successful encrypted backup in 26 hours; restore verification >7 days old |
| Credential anomaly | Authentication failures or secret-redaction event; stop affected connector |

Initial SLOs: 99% successful scheduled runs over 30 days; 95% of daily batches under 30 minutes excluding model download; zero unapproved resume exports; zero PII/secrets in logs; RPO 24 hours and RTO 4 hours.

## 7. Resilience, idempotency, DLQ, and recovery

### 7.1 Retry policy

- Retry only transient network failures, `408`, `425`, `429`, `500`, `502`, `503`, `504`, SQL deadlock `1205`, and brief local-service unavailability.
- Use exponential backoff with full jitter (for example 1, 2, 4, 8, 16 seconds), provider `Retry-After`, a maximum of 5 network attempts and 3 model attempts.
- Do not retry authentication/authorization failures, malformed input, policy denial, unsupported content, deterministic schema errors after repair, or LinkedIn challenges.
- Set connect/read/overall deadlines. Use a circuit breaker after repeated source/model failures.
- Never retry a non-idempotent external action automatically. The product does not auto-apply or auto-message.

### 7.2 Idempotency and concurrency

- Scheduler mutex: `Global\ATS-RAG-Daily` or an atomic lock file with stale-lock validation. Task Scheduler policy: **Do not start a new instance**.
- Run key: `pipeline_name + business_date + config_version`.
- Job key: canonical source ID when stable, otherwise SHA-256 of normalized URL/title/company/location/posting date. Enforce unique constraints.
- Embedding key: SHA-256 of normalized text + model revision + dimensions + chunker version.
- Resume variant key: application/job ID + source fact-set hash + prompt/model/template versions.
- API credit ledger: update transactionally after a confirmed request; include provider request ID where available.
- Use database transactions and an outbox for cross-store updates. Never mark a stage complete before its durable outputs commit.

### 7.3 Dead-letter handling

DLQ entries contain: `event_id`, `run_id`, stage, safe source ID, first/last failure time, attempt count, normalized error code, payload SHA-256, encrypted payload path, and replay status. They must not contain secrets.

Store encrypted payloads under `%LOCALAPPDATA%\ATS\dlq`, user-only ACL, 14-day retention. Classify outcomes:

- `REJECTED_POLICY` and `INVALID_INPUT`: terminal; manual review only.
- `TRANSIENT_EXHAUSTED`: replay after dependency recovery.
- `POISON_SCHEMA`: quarantine until parser/schema changes.
- `DUPLICATE`: metric/audit event, not a DLQ error.

Replay uses the original idempotency key and current approved parser version; never bulk replay without a dry run and count limit.

### 7.4 Recovery sequence

1. Stop new scheduled starts; preserve logs and run metadata.
2. Identify the last committed stage using run/state tables.
3. Restore dependency health and validate credentials without printing them.
4. Verify SQL integrity and free disk space.
5. Replay only `TRANSIENT_EXHAUSTED` DLQ entries, bounded by source and count.
6. Rebuild BM25/embedding indexes from canonical SQL/fact data rather than treating indexes as authoritative.
7. Compare row counts, hashes, model/schema versions, and grounding gates.
8. Resume scheduling and monitor one full run.

## 8. Backup and disaster recovery

### 8.1 Authoritative and rebuildable data

Authoritative: SQL schema/data, candidate source documents, approved generated artifacts and provenance, configuration excluding secrets, migration history, model lockfile, and application/outcome records.

Rebuildable: BM25 index, embedding cache, temporary reports, downloaded model weights (if revisions remain available), and transient queues.

### 8.2 Backup design

- SQL: nightly encrypted full backup; optional 6-hour differential; transaction-log backup every hour if using Full recovery model. Run `DBCC CHECKDB` weekly.
- Files: nightly versioned encrypted backup of authoritative roots. Exclude credentials, transient model cache, logs past policy, and raw session cookies.
- Maintain SHA-256 manifests. Use VSS-aware capture or stop writers; do not copy live SQL MDF/LDF files.
- Follow 3-2-1: three copies, two media types, one offline/off-device encrypted copy.
- Protect backup encryption certificates/keys separately. Test key recovery.
- Quarterly full restore drill to an isolated instance; monthly sample file restore. Record duration and evidence.

Target **RPO: 24 hours** (1 hour for SQL when log backups are enabled). Target **RTO: 4 hours** on replacement Windows hardware.

### 8.3 DR runbook

1. Build a patched Windows host and enable BitLocker.
2. Install the approved Python, ODBC, SQL Server, Ollama/infinity profile.
3. Restore SQL encryption certificate, then full/differential/log backups in order.
4. Restore files and ACLs; retrieve secrets from the approved recovery channel.
5. Verify hashes and `DBCC CHECKDB`.
6. Recreate venv from the hash lock and models from `models.lock.json`.
7. Rebuild indexes/caches.
8. Run offline golden tests and health checks.
9. Keep schedules disabled until a manual end-to-end approval test succeeds.

## 9. Deployment profiles

### 9.1 Profile A — Windows native (recommended)

```text
Windows Task Scheduler / interactive CLI
  -> Python 3.11 venv under C:\ATS\.venv
  -> SQL Server local service (Integrated Authentication)
  -> Ollama Windows process, 127.0.0.1:11434
  -> infinity-emb optional Windows Python service, 127.0.0.1:7997
  -> private data under %LOCALAPPDATA%\ATS
```

Benefits: simplest single-user operation, native Credential Manager/DPAPI/ACL integration, no WSL filesystem/network boundary. Keep source in `C:\ATS`; keep mutable private data outside the source directory.

Suggested processes:

| Process | Identity/start | Restart policy |
|---|---|---|
| SQL Server | Existing Windows service; Integrated Authentication | Service Control Manager automatic |
| Ollama | Dedicated user process/task at logon, loopback bind | Restart up to 3 times; alert thereafter |
| infinity-emb | Optional scheduled/background task using `.venv` | Restart up to 3 times; never expose externally |
| Daily pipeline | Task Scheduler daily, after services | No overlap; 2-hour execution cap |
| Weekly maintenance | Task Scheduler weekly | Backup, retention, integrity, index rebuild |

### 9.2 Profile B — WSL2

Use only for vLLM, Linux-first GPU libraries, or an infinity build that cannot meet Windows requirements.

```text
Windows: SQL Server + Credential Manager + Task Scheduler
WSL2 Ubuntu: Python app/infinity/vLLM
Communication: loopback/WSL virtual network with firewall restrictions
Data: Linux ext4 filesystem; do not run model/database workloads from /mnt/c
```

Requirements: install WSL2 and Ubuntu, enable GPU support with Microsoft/NVIDIA-supported drivers, pin the distribution version, and use a systemd user service. Do not copy secrets into shell profiles or WSL environment files. Obtain short-lived runtime secrets from an approved bridge or use a WSL-native secret mechanism with `0600` permissions. WSL2 is not currently installed on the inspected host.

WSL IPs can change. Prefer Windows `localhost` forwarding where supported; otherwise discover and firewall the current address. SQL must remain restricted to the host/WSL path and use encryption plus certificate validation if TCP crosses the VM boundary.

### 9.3 Ports and network policy

| Service | Default/proposed | Binding | Health |
|---|---:|---|---|
| Ollama | TCP 11434 | `127.0.0.1` only | `GET http://127.0.0.1:11434/api/version` |
| infinity-emb | TCP 7997 | `127.0.0.1` only | `GET http://127.0.0.1:7997/health` and `/models` as supported |
| SQL Server | Named pipes/shared memory preferred; TCP 1433 only if explicitly fixed | Localhost/WSL only | `SELECT 1`, database/schema/version query |
| SQL Browser | UDP 1434 | Disabled unless a documented named-instance need exists | Service state |
| Application UI | None by default (CLI) | N/A | CLI `doctor` command |
| Metrics | No open port by default; file/SQLite/Event Log | N/A | freshness query |

At inspection time, no listeners were observed on 11434, 7997, 1433, or 1434. Do not assume a SQL TCP port; the running default service may use shared memory or a dynamic port.

## 10. Health checks and task scheduling

### 10.1 Preflight checks

Run before every batch:

1. Configuration/schema parses and required directories have safe ACLs.
2. Required secret handles exist; never print values.
3. SQL `SELECT 1`, expected database, migration version, and sufficient disk space.
4. Ollama `/api/version`, required models installed, and a bounded test generation/embedding when the stage needs it.
5. infinity `/health` and model list when selected.
6. Source credit/quota available and last successful run old enough.
7. Lock acquired and no conflicting maintenance task.
8. Clock is synchronized and backup is recent.

Health states are `healthy`, `degraded`, and `unhealthy`. In degraded mode, local deterministic/reporting stages may run, but no component may bypass grounding or approval.

### 10.2 Suggested Task Scheduler plan

| Task | Trigger | Conditions/actions |
|---|---|---|
| `ATS-RAG-Services` | At user logon | Start Ollama/infinity if installed; non-admin identity |
| `ATS-RAG-Daily` | Daily 06:00 local | Network required only for ingestion; no overlap; retry task twice at 15-minute intervals; 2-hour cap |
| `ATS-RAG-Weekly` | Sunday 07:00 | Aggregation, retention, DLQ review, integrity checks |
| `ATS-RAG-Backup` | Daily 22:00 | Encrypted SQL/file backup; fail closed if key unavailable |
| `ATS-RAG-Dependency-Audit` | Monthly | `pip-audit`, SBOM/license report, model/dependency update report; no automatic upgrade |

Use `Program/script` as the full Python executable in `.venv`, `Start in` as `C:\ATS`, and redirect through an application entry point that returns meaningful exit codes. Store task XML in source after removing usernames and secrets.

## 11. Dependency and license matrix

Licenses must be verified against the exact selected release and model card before distribution.

### 11.1 Existing direct usage

| Dependency/import | Current declaration | Purpose | Typical license | Decision/gap |
|---|---|---|---|---|
| `google-search-results` / `serpapi` | Pinned `2.4.2` | SerpAPI job search | MIT | Retain temporarily; credential and retry refactor required |
| `python-docx` / `docx` | Missing | DOCX parsing/generation | MIT | Required |
| `PyPDF2` | Missing | PDF extraction | BSD-3-Clause | Replace with maintained `pypdf` |
| `google.genai` | Missing | Gemini path in `ats_validator.py` | Apache-2.0 client | Current import maps to `google-genai`, not legacy `google-generativeai`; optional in local-only target |
| `docx2pdf` | Missing | Word-backed PDF conversion | MIT | Windows/Word-specific optional extra |
| `markdown`, `markdown2` | Missing | Markdown conversion | BSD-3-Clause / MIT | Consolidate to one implementation |
| `Pygments` | Missing | Syntax highlighting | BSD-2-Clause | Optional docs extra |
| `WeasyPrint` | Missing | HTML/PDF rendering | BSD-3-Clause | Optional; native runtime dependencies must be documented |

Standard-library imports (`csv`, `json`, `pathlib`, `re`, etc.) require no package entry.

### 11.2 Target runtime

| Dependency | Purpose | Typical license | Pinning/control |
|---|---|---|---|
| `pyodbc` + Microsoft ODBC Driver 18 | SQL access | MIT client; Microsoft driver terms | Pin Python package; signed driver installer/version inventory |
| `requests` or `httpx` | HTTP | Apache-2.0 / BSD-3-Clause | Choose one; explicit timeouts |
| `tenacity` | bounded retry | Apache-2.0 | Pin exact |
| `pydantic` | schemas/config | MIT | Pin exact major/minor; reject extras |
| `keyring` | Credential Manager | MIT | Pin exact and verify backend |
| `filelock` | process/file coordination | Unlicense | Pin exact |
| `structlog` | structured logging | Apache-2.0 OR MIT | Pin exact |
| `opentelemetry-*` | traces/metrics | Apache-2.0 | Optional observability extra; pin coordinated versions |
| `bm25s` | sparse retrieval | Apache-2.0 | Canonical MVP lexical projection; pin exact |
| `qdrant-client` + Qdrant | dense retrieval | Apache-2.0 | Loopback only; pin client and server/container digest |
| `sentence-transformers`, `transformers`, `torch` | local embeddings/NLI | Apache-2.0 / BSD-style | Hardware-specific lock; use approved wheel index |
| `spacy` | NER | MIT | Pin package and model separately |
| `scikit-learn` | calibration after label gate | BSD-3-Clause | Optional analytics extra |
| `infinity-emb` | embedding/reranking service | MIT (verify release) | Pin package/container digest and model revisions |
| Ollama | local generation server | MIT server; model licenses vary | Pin signed release and each model digest |
| Qwen3 models | local generation/reranking | Apache-2.0 for selected Qwen3 weights | Pin model digest/revision |
| BGE-M3 | multilingual embeddings | MIT model card for selected weights; verify | Pin revision and embedding dimensions |
| Nomic Embed v1.5 | CPU embedding alternative | Apache-2.0 | Pin revision; enforce query/document prefixes |
| DeBERTa NLI checkpoint | claim verification | Model-specific | Approve exact checkpoint/license, pin SHA |
| SQL Server | relational system of record | Microsoft product terms | Developer edition is non-production; verify deployment rights |

`joeyism/linkedin_scraper` is an optional Apache-2.0 code dependency according to the research artifact, but license permissiveness does not authorize collection that violates site terms, privacy law, or account rules.

### 11.3 Dependency groups

- `requirements.in`: minimum production direct dependencies.
- `requirements-dev.in`: production file plus pytest, coverage, ruff/type checker, pip-tools, pip-audit, SBOM/license tooling.
- `requirements-ml-cpu.in` and `requirements-ml-cuda.in`: mutually tested ML profiles.
- `requirements-docs.in`: DOCX/PDF/Markdown conversion extras.
- Generated `*.lock` files: exact versions and hashes; committed alongside source when a repository is created.
- `models.lock.json`: immutable model artifacts and licenses.

Use compatible-release ranges only in `.in`; deployment always uses locks. Regenerate locks in a clean environment after review, run tests/security/license checks, and promote by pull request. Do not hand-edit lockfiles.

## 12. Environment variables

Environment variables contain configuration or credential references, not plaintext secrets where Credential Manager is available.

| Variable | Default | Notes |
|---|---|---|
| `ATS_ENV` | `dev` | `dev`, `test`, `prod-local` |
| `ATS_HOME` | `%LOCALAPPDATA%\ATS` | Mutable private root |
| `ATS_LOG_LEVEL` | `INFO` | Never enable content logging |
| `ATS_SQL_SERVER` | `localhost` | Prefer Integrated Authentication |
| `ATS_SQL_DATABASE` | `JobSearchRAG` | Expected DB |
| `ATS_SQL_DRIVER` | `ODBC Driver 18 for SQL Server` | Validate installed driver |
| `ATS_SQL_ENCRYPT` | `yes` | For TCP; validate cert outside local dev |
| `ATS_SERPAPI_CREDENTIAL` | `ATS/SERPAPI_KEY` | Credential Manager target name |
| `ATS_OLLAMA_URL` | `http://127.0.0.1:11434` | Reject non-loopback in local profile |
| `ATS_INFINITY_URL` | `http://127.0.0.1:7997` | Optional |
| `ATS_LLM_MODEL` | unset | Select from approved `models.lock.json` |
| `ATS_EMBED_MODEL` | unset | Dimension must match schema |
| `ATS_RERANK_MODEL` | unset | Optional |
| `ATS_LINKEDIN_ENABLED` | `false` | Manual governed mode only |
| `ATS_MAX_INPUT_BYTES` | `2097152` | Per source, tune downward where possible |
| `ATS_HTTP_TIMEOUT_SECONDS` | `30` | Stage-specific override allowed |
| `ATS_MAX_RETRIES` | `5` | Model schema repair remains max 3 |
| `ATS_RETENTION_DAYS_LOGS` | `30` | Policy bounded |
| `ATS_RETENTION_DAYS_DLQ` | `14` | Policy bounded |
| `ATS_TELEMETRY_EXPORTER` | `file` | No cloud exporter by default |

## 13. Setup runbook

### 13.1 Windows-native

1. Patch Windows, enable BitLocker and Defender, and create the private data directories.
2. Remove inherited broad ACLs; grant only the interactive/task identity, Administrators, and SYSTEM.
3. Install approved Python 3.11.x and create `C:\ATS\.venv`.
4. Compile/review locks on a controlled build machine; install with `--require-hashes`.
5. Install signed ODBC Driver 18. Use the existing SQL Server 2022 for relational state and install Qdrant for dense-vector retrieval. Developer edition is not licensed for production.
6. Create `JobSearchRAG`, schema migration account, least-privilege runtime account/group, backup target, and retention job.
7. Rotate exposed SerpAPI credentials and store the replacement in Credential Manager.
8. Install the pinned Ollama release, set its host to loopback, pull models from `models.lock.json`, and verify digests/licenses.
9. If selected, install infinity-emb in a separate venv, bind to `127.0.0.1:7997`, and load only pinned models.
10. Run migrations, seed configuration, ingest the candidate fact base, and build indexes.
11. Execute unit, integration, golden grounding, restore, and `doctor` checks.
12. Register services/tasks from reviewed XML. Keep scheduled resume export/application actions disabled.

### 13.2 WSL2

1. Enable virtualization and install WSL2/approved Ubuntu; patch both Windows and Ubuntu.
2. Install supported GPU drivers if applicable and verify GPU availability inside WSL.
3. Put code/data on the Linux ext4 filesystem; expose only approved output paths to Windows.
4. Build a Linux lockfile separately from Windows; never reuse platform-specific ML locks.
5. Install infinity/vLLM as a systemd user service bound to loopback.
6. Configure protected Windows SQL connectivity, test certificate validation, and apply firewall scope.
7. Register a Windows task invoking `wsl.exe -d <approved-distro> -- <entrypoint>` with no inline secrets.
8. Run the same golden and recovery tests.

## 14. Operator runbook

### Start

1. Check disk, recent backup, SQL service, and task identity.
2. Start/verify Ollama and optional infinity.
3. Run `python -m ats_local doctor --redacted`.
4. Confirm model revisions, DB migration, source quotas, and scheduler lock.
5. Run one bounded dry-run ingestion before enabling schedule after upgrades.

### Daily

- Review the run summary, alerts, DLQ count, quota, Top-10 explanations, unsupported-claim flags, and disk/backup status.
- Approve/edit/reject resume drafts interactively. Record application actions manually.

### Stop

- Disable new task starts, allow/terminate the active run at a transaction boundary, flush logs/metrics, checkpoint state, then stop optional model services. SQL may remain running for backup/maintenance.

### Upgrade

1. Back up and snapshot configuration/model locks.
2. Review changelogs, vulnerabilities, licenses, migration, and model behavior.
3. Build a new venv; never mutate the active one in place.
4. Run unit/integration/golden and restore tests.
5. Stop scheduler, migrate, atomically switch the venv/config pointer, and run canary.
6. Roll back package environment and schema only through tested down/forward recovery; preserve data added after upgrade.

## 15. Troubleshooting

| Symptom | Checks | Resolution |
|---|---|---|
| SQL service runs but TCP 1433 is closed | Test local Integrated Authentication/shared memory; inspect SQL network configuration and error log | Keep local protocol or explicitly configure fixed loopback TCP; do not open firewall broadly |
| Qdrant is unavailable | Check `http://127.0.0.1:6333/readyz` and Windows process/service state | Restart Qdrant; continue ingestion to SQL/outbox; rebuild the vector projection |
| `JobSearchRAG` missing | Query `sys.databases`, migration history | Create via migration under admin identity; never let runtime auto-create |
| Ollama command/health missing | `Get-Command ollama`; `/api/version` | Install pinned signed release, loopback bind, pull approved model |
| infinity health fails | Process, port 7997, model path, RAM/VRAM | Start isolated venv service; verify model revision and batch size |
| WSL command says not installed | `wsl --status` | Use native profile or install WSL2 deliberately; it is currently absent |
| Model JSON invalid | Prompt/schema/model revision/token truncation metrics | Repair prompt up to 3 times, then deterministic fallback and DLQ; never consume raw text |
| Embedding dimension mismatch | DB column, model lock, response length | Stop writes; use versioned vector column/table and re-embed; never pad/truncate silently |
| Duplicate jobs/resumes | Idempotency key, normalization version, unique index, overlapping tasks | Fix key/constraint and replay safely; configure no-overlap |
| SerpAPI 401/403/429 | Credential handle, quota, `Retry-After`, provider dashboard | Stop on auth; open circuit on throttling; do not rotate identities to evade limits |
| Task works interactively only | Task identity, `Start in`, full paths, Credential Manager scope, ACL | Store secrets for task identity; use absolute executable/path; capture exit code/Event Log |
| DOCX-to-PDF fails | Word installation/desktop session for `docx2pdf`; WeasyPrint native dependencies | Treat converters as optional profiles; retain DOCX and use a tested headless path |
| Logs contain PII | Redaction config and exception formatting | Stop exporter, restrict/delete affected logs, rotate exposed secrets if any, add regression test |
| Disk growth | Model cache, raw payload, DLQ, logs, SQL log/backups | Enforce retention, investigate stuck backup/log truncation; do not delete authoritative data ad hoc |

## 16. Implementation gap register

### P0 — before further use or publication

- Rotate and remove hardcoded SerpAPI credentials.
- Fix `smart_scheduler.py` JSON persistence defect.
- Prevent any cloud-sync exposure of resume/session/secret material.
- Parameterize planned SQL vector inserts; never implement the documented f-string example.

### P1 — foundation

- Create `ats_local`, tests, migrations, configuration schemas, lockfiles, SBOM, and secret store.
- Provision SQL Server 2022 relational schemas and the pinned Qdrant local service.
- Install/lock Ollama and embedding profile; currently neither is present.
- Implement private directories, ACLs, structured redacted logging, health checks, run state, locks, idempotency constraints, DLQ, and encrypted backups.
- Complete dependency declarations: current scripts import several undeclared packages.

### P2 — safety and quality gates

- Build candidate fact/provenance store before new generative resume functionality.
- Add hybrid retrieval, model/versioned embedding cache, schema validation, deterministic numeric/entity checks, NLI verification, and mandatory human approval.
- Keep LinkedIn disabled unless a current responsible-use review authorizes the narrow manual mode.
- Implement application tracking and descriptive feedback; do not claim calibrated callback probability before at least 100 suitable labeled outcomes.

### P3 — operational maturity

- OpenTelemetry traces/metrics, alert routing, SLO review, performance tests, restore drills, update automation that proposes rather than auto-applies changes, and WSL2/vLLM only if measured demand justifies it.

## 17. Acceptance checklist

- [ ] Exposed credentials revoked; source and logs scan clean.
- [ ] All private roots encrypted and ACL-verified.
- [ ] No local service listens beyond loopback/approved WSL boundary.
- [ ] Complete hash lock, SBOM, vulnerability report, license inventory, and model lock exist.
- [ ] SQL version/profile decision documented; migration and least privilege verified.
- [ ] Health, logging, metrics, traces, alerts, retry/circuit-breaker, idempotency, and DLQ tests pass.
- [ ] Encrypted backup restores successfully inside RPO/RTO.
- [ ] LinkedIn is off by default and cannot auto-act.
- [ ] Golden prompt-injection, schema, truncation, entity, unsupported-claim, and approval-gate tests pass.
- [ ] Scheduled jobs cannot overlap or export/apply without human approval.
- [ ] Retention and complete deletion—including indexes/embeddings—are tested.

---

This document is the operating baseline. Where it conflicts with an old design proposal, the secure local-only, least-privilege, provenance-first, human-approval requirements here take precedence until a reviewed architecture decision supersedes them.


