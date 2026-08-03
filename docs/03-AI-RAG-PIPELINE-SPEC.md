# C:\ATS Local Job Assistant - AI/RAG Pipeline Implementation Specification

**Status:** implementation specification  
**Target:** local Windows 11, Python 3.11, SQL Server 2022 system of record, Qdrant dense index, bm25s lexical index, local model runtime  
**Primary quality rule:** deterministic policy and provenance gates control decisions; models extract, rank, rewrite, or critique but never establish facts.

## 1. Scope, sources, and decisions

This specification consolidates:

- `C:\ATS\Download the Markdown file.md` - research report and target product behavior.
- `historical architecture working notes (not published)` - architecture, DFDs, state machines, deployment profiles, and failure flows.
- `historical reuse-audit working notes (not published)` - executable-code reuse/refactor audit.
- Relevant `C:\ATS` RAG documents and scripts, especially `RAG_MASTER_PROMPT.md`, `RAG_JOB_SEARCH_ARCHITECTURE_REVIEW.md`, `RAG_SEARCH_OPTIMIZATION_STRATEGY.md`, `google_jobs_scraper_FIXED.py`, `smart_scheduler.py`, `ats_validator.py`, and resume/ATS utilities.

The architecture artifact refers to a 25-component research formula that is not fully reproduced in the supplied files. Section 8 therefore defines a complete, normalized V1 formula rather than silently copying the older research formula, whose displayed weights sum to 1.05. All V1 weights are hypotheses and must be versioned and evaluated.

## 2. Non-negotiable invariants

1. Local-first: resume facts, generated resumes, embeddings, and model prompts remain on the machine.
2. No auto-apply. A user approves every resume export and application action.
3. Every generated claim has one or more immutable `FactID` references and source spans.
4. Unsupported or contradicted claims block export. An override, if enabled, is explicit, reasoned, and audited.
5. Eligibility uses `PASS | FAIL | UNKNOWN`; absent data is never treated as failure.
6. Lexical and semantic retrieval remain independent and are fused by rank, not raw score.
7. Every derived artifact records parser, taxonomy, embedding, index, model, prompt, and score versions.
8. Raw model output is never trusted before JSON Schema and semantic validation.
9. Callback values are qualitative bands until at least 100 closed, labeled outcomes and calibration gates pass.
10. Secrets come from Windows Credential Manager or environment variables, never source.

## 3. Target package boundaries

```text
ats_local/
  config/{pipeline.yaml,models.yaml,taxonomy.yaml,scraper_config.yaml}
  ingestion/{orchestrator.py,raw_store.py,canonicalizer.py,deduplicator.py}
  scraper/{serpapi_fetcher.py,rss_fetcher.py,utils.py}
  parsing/{job_parser.py,requirement_classifier.py,resume_parser.py}
  taxonomy/{skills.py,titles.py,locations.py,companies.py}
  retrieval/{bm25.py,dense.py,rrf.py,cross_encoder.py}
  ranking/{constraints.py,fit_scorer.py,mmr.py,explainer.py,orchestrator.py}
  factbase/{builder.py,repository.py,evidence.py,provenance.py}
  generation/{fact_retriever.py,bullet_selector.py,rewriter.py,verifier.py}
  validators/{ats_rules.py,ats_simulator.py,readability.py,keyword_scorer.py}
  docx_builder/{helpers.py,docx_builder.py}
  slm/{router.py,ollama_client.py,schemas.py}
  prompts/{registry.py,templates/,schemas/}
  evaluation/{datasets.py,ranking.py,generation.py,regression.py}
  scheduler/{credit_ledger.py,daily.py}
  tracker/{applications.py,outcomes.py}
  storage/{repositories.py,migrations/}
  ui/{cli.py,approval_gate.py,report_renderer.py}
tests/
  unit/ integration/ golden/ fixtures/
```

Services exchange typed dataclasses/Pydantic models, not unstructured dictionaries. Repositories own SQL; pipeline modules do not issue ad hoc SQL.

## 4. Storage and versioning model

Canonical relational names come from `02-DATA-AND-API-DESIGN.md`: `rag.Job`, `rag.JobRequirement`, `rag.CandidateFact`, `rag.SkillEvidence`, `rag.JobScore`, `rag.ResumeVariant`, `rag.Application`, and `rag.Outcome`. Terms such as “job description” and “resume fact” in this document describe concepts, not alternate tables.

Core entities:

- `RawJobEnvelope`: source, source job ID, request ID, fetched time, HTTP metadata, raw payload hash, encrypted/raw payload location.
- `JobDescription`: canonical URL, raw and normalized title/company/location, clean text, posted time, duplicate cluster, processing state, parser version.
- `JobChunk`: job ID, field (`title`, `requirement`, `responsibility`, `company`), ordinal, text, token count, content hash.
- `JobRequirement`: exact source text/span, class, canonical skill/title/domain, mandatory flag, minimum years, confidence, extractor version.
- `CandidateProfile`: target roles, locations, work authorization, employment preference, compensation floor, seniority, career direction.
- `ResumeFact`: original text, normalized text, source document/section/start/end, employer/role/project/date range, confidence, verification state, content hash.
- `Skill`, `SkillAlias`, `SkillRelation`; `SkillEvidence` links a skill to a fact with depth, recency, confidence, and evidence class.
- `JobScore`: all feature values, gates, penalties, retrieval ranks, final score, explanation, and score version.
- `ResumeVariant`: generated content hash, per-sentence provenance, generator/prompt/model versions, ATS/readability results, approval.
- `PromptVersion`, `ModelVersion`, `EmbeddingVersion`, `TaxonomyVersion`, `EvaluationRun`.

Vectors of different dimensions must never share a collection. Use separate Qdrant collections for Nomic 768-dimensional and BGE-M3 1024-dimensional embeddings. Re-embedding writes a new versioned collection and atomically switches the active collection only after validation.

Processing is idempotent with:

```text
idempotency_key = SHA256(source + source_job_id + canonical_url + raw_payload_hash)
derived_key     = SHA256(content_hash + component_version + configuration_hash)
```

## 5. Ingestion and parsing

### 5.1 Fetch

`SerpApiFetcher.fetch(query, location, date_filter)` is refactored from `google_jobs_scraper_FIXED.py`.

- Inject API key and HTTP/search client.
- Use simple queries and individual locations; do not use OR expressions in the location field.
- Persist request metadata before the call and response metadata after it.
- Retry 429 and 5xx up to three times with exponential delay (2-30 seconds) and jitter. Honor `Retry-After`.
- Timeout connect/read separately.
- Record attempted and billable calls in the credit ledger.
- Continue other query/location pairs after terminal failure.
- Store malformed payloads in a local NDJSON dead-letter queue with sensitive fields minimized.

Other connectors implement the same `JobSource` protocol. Greenhouse/Lever/RSS are preferred free feeds. LinkedIn automation is disabled by default and manual-only.

### 5.2 Parse and clean

Never destroy raw input. Produce `clean_text` by:

1. Decode with declared encoding, then `charset-normalizer` fallback.
2. Strip scripts, styles, tracking pixels, repeated navigation, cookie/legal boilerplate.
3. Convert structural HTML to ordered plain text; preserve headings and list boundaries.
4. Normalize Unicode to NFKC for matching while retaining original text/spans.
5. Collapse whitespace without merging list items.
6. Detect language. V1 accepts English; other languages are stored with `PARSE_UNSUPPORTED_LANGUAGE` and optionally translated only in a separate, provenance-bearing field.
7. Reject/flag empty descriptions, access-denied pages, and descriptions below a configurable information threshold.

Use deterministic patterns first, then a local schema-constrained SLM for:

- title, seniority, role family;
- responsibilities;
- mandatory, preferred, legal/eligibility, education, certification, compensation, and disqualifier requirements;
- remote mode and location constraints.

The model must return each item with `source_start`, `source_end`, exact `source_text`, confidence, and `null` for missing facts. Post-validation verifies that source spans reproduce the submitted text. Rules override the model for phrases such as `must`, `required`, `minimum`, `nice to have`, `preferred`, and `eligible to work`.

### 5.3 Chunking

Create both document and field-aware representations:

- title/company/location: one short chunk;
- each requirement or bullet: one atomic chunk;
- responsibilities: semantic groups;
- fallback sliding window: 384 tokens with 64-token overlap;
- hard maximum: model tokenizer limit minus prompt overhead.

Chunks never cross heading boundaries where avoidable. Store character spans, token count, field, and ordinal. Long JDs are not truncated to a single MiniLM window.

## 6. Canonicalization, taxonomy, and deduplication

### 6.1 Canonicalization

- URL: lowercase host, remove fragments and tracking parameters, normalize trailing slash, retain source job ID.
- Company: Unicode/case/whitespace normalize, strip legal suffix only for matching, preserve display name, apply curated alias table.
- Title: normalize abbreviations (`Sr` -> `Senior`, `DBA` -> `Database Administrator`) and map to `{role_family, level, specialization}`.
- Location: parse city/region/country, ISO country, remote mode, timezone; distinguish `remote-anywhere`, `remote-country`, `hybrid`, and `onsite`.
- Compensation: preserve currency/period/range; normalize to annual base only when units and exchange-rate date are known.
- Dates: store source date, inferred date, and confidence separately. Never turn “30+ days ago” into a precise date.

### 6.2 Skill taxonomy

`taxonomy.yaml` is a reviewed, versioned DAG:

```yaml
skill: azure_sql_database
display: Azure SQL Database
aliases: [Azure SQL, Azure SQL DB, SQL Azure]
parents: [relational_database, azure_data_platform]
relations:
  - {to: sql_server, type: adjacent, weight: 0.65}
  - {to: azure_sql_managed_instance, type: related, weight: 0.75}
```

Categories include database engines, cloud platforms, performance, HA/DR, migration, automation/IaC, SRE/operations, security, analytics, certifications, and soft skills. Exact aliases map to one canonical ID. Ambiguous aliases (for example `AG`, `MI`, `RCA`) require context. A parent or adjacent skill is never equivalent to direct evidence.

Evidence labels:

- `DIRECT`: exact skill and activity explicitly supported.
- `PARTIAL`: same skill but insufficient scope/depth or only a subset of the requirement.
- `ADJACENT`: transferable related skill; not claimable as direct experience.
- `NONE`: no support.
- `CONFLICTING`: evidence contradicts the proposed claim.

Taxonomy changes run migration tests: alias collision, DAG cycle, changed canonical IDs, and score drift.

### 6.3 Duplicate detection

Use staged detection:

1. Exact source identity: `(source, source_job_id)`.
2. Canonical URL hash.
3. Exact content fingerprint over normalized company, title, location, and clean description.
4. Fuzzy candidate generation by company/title/date blocks.
5. Near-duplicate score:

```text
dup = 0.35*title_token_set
    + 0.20*company_similarity
    + 0.30*description_cosine
    + 0.10*location_similarity
    + 0.05*posted_date_proximity
```

`dup >= 0.92` merges into one cluster; `0.82-0.92` is review/cluster-only; below `0.82` remains distinct. Never merge different requisition IDs solely from similar boilerplate. Select the canonical cluster representative by source quality, full-description availability, newest source observation, and valid application URL. Preserve every source record.

## 7. Hybrid retrieval and cross-encoder reranking

### 7.1 Query construction

Build a structured query from `CandidateProfile`, verified `ResumeFact`, and target direction. Expand only reviewed taxonomy aliases. Separate:

- lexical query: exact technologies/acronyms, title families, certifications;
- semantic query: concise verified experience summary;
- filters: age window, already applied, language, employment type.

Do not concatenate the entire resume. Weight recent, deep, direct evidence more than old keyword mentions.

### 7.2 BM25

Use `bm25s`; SQL rows remain authoritative. Whoosh is not part of the canonical MVP dependency set. Index fields independently:

```text
lexical_score = 2.0*BM25(title)
              + 1.5*BM25(mandatory_requirements)
              + 1.2*BM25(preferred_requirements)
              + 1.0*BM25(responsibilities)
              + 0.3*BM25(company)
```

Retrieve top 300 unique jobs. Analyzer preserves technical tokens such as `T-SQL`, `SQL Server`, `HA/DR`, `Always On`, `CI/CD`, and version numbers. Synonyms come from the taxonomy, not unrestricted stemming.

### 7.3 Dense retrieval

- CPU profile: Nomic Embed Text v1.5, 768 dimensions.
- GPU profiles: BGE-M3, 1024 dimensions.
- L2 normalize embeddings and use cosine distance.
- Embed atomic requirements/chunks and a document summary.
- Job dense score is the maximum relevant chunk score with a small document-score blend:

```text
dense_job = 0.75*max(requirement_chunk_similarity)
          + 0.25*document_similarity
```

Retrieve top 300 jobs. Cache by `(content_hash, embedding_version)`.

### 7.4 Reciprocal Rank Fusion

Raw BM25 and cosine scores are not comparable. Fuse ranks:

```text
RRF(job) = sum_retrievers weight_r / (k + rank_r(job)), k = 60
```

V1 uses equal weights. Keep the union, sort by RRF, and retain up to 500. If only one retriever is healthy, continue in degraded mode and mark `retrieval_degraded=true`.

### 7.5 Cross-encoder

Apply after hard eligibility gates to the best 100 RRF candidates:

- Tier 1: BGE reranker base.
- Tiers 2-3: Qwen3-Reranker-0.6B.
- Tier 4: BGE-Reranker-v2-M3 or validated larger reranker.

Input is a bounded pair: verified candidate summary plus canonical job title and classified requirements, not raw full documents. Output is a numeric relevance score in `[0,1]`. Batch by token length. A timeout or OOM falls back to RRF order; it must not stop daily ranking. Cross-encoder scores influence relevance but cannot overturn a hard `FAIL`.

## 8. Constraints and V1 top-10 formula

### 8.1 Hard gates

Each gate records status, source, and reason:

- work authorization/explicit sponsorship incompatibility;
- location/remote policy;
- employment type;
- compensation floor only when comparable compensation is explicit;
- already applied;
- closed/expired posting;
- explicit mandatory clearance/license/certification;
- explicit role disqualifier.

`UNKNOWN` survives with a small uncertainty penalty and is shown to the user. Central mandatory skills are not generally hard eligibility gates: a missing central skill receives a large fit penalty and recommendation `SKIP`, unless user policy designates it as a knockout.

### 8.2 Feature definitions

All features are `[0,1]`:

- `Req`: weighted mandatory requirement coverage, direct=1.0, partial=0.45, adjacent=0.15, none=0.
- `Pref`: preferred requirement coverage using the same mapping.
- `Title`, `Seniority`, `Domain`: taxonomy similarity with explicit mismatch handling.
- `Evidence`: requirement-weighted evidence strength.
- `Retrieval`: percentile-normalized RRF score within the run.
- `Rerank`: calibrated cross-encoder score; use neutral 0.5 when unavailable and set degraded flag.
- `Callback`: calibrated model probability only after gates; otherwise conservative heuristic band converted to fixed values `{low:.25, medium:.5, high:.75}` and labeled heuristic.
- `Company`: source quality and user preference, excluding protected attributes.
- `Fresh`: exponential decay, `exp(-age_days/14)`, capped for unknown dates at 0.4.
- `Referral`: verified reachable referral/recruiter opportunity.
- `Strategic`: alignment to configured career direction.

Per-evidence strength:

```text
E = 0.35*directness + 0.25*depth + 0.20*recency
  + 0.10*quantified + 0.10*confidence
```

### 8.3 Formula

The normalized V1 score is:

```text
Base = 100 * (
    0.23*Req       + 0.07*Pref      + 0.07*Title
  + 0.07*Seniority + 0.09*Domain    + 0.12*Evidence
  + 0.07*Retrieval + 0.07*Rerank    + 0.06*Callback
  + 0.04*Company   + 0.05*Fresh     + 0.03*Referral
  + 0.03*Strategic
)

Final = clamp(Base - Penalties, 0, 100)
```

Penalties are additive points and capped at 60:

| Condition | V1 penalty |
|---|---:|
| each unsupported central mandatory skill | 18, max 36 |
| explicit seniority mismatch | 15 |
| irrelevant role family/domain | 20 |
| eligibility unknown | 3 per field, max 9 |
| low fact confidence for claimed coverage | 8 |
| stale/possibly closed posting | 8 |
| exact duplicate | hard fail |
| near duplicate in same cluster | 5 before diversification |
| already applied | hard fail unless user requests reconsideration |

Store the complete feature vector and reasons. Tie-break in order: required coverage, evidence, freshness, cross-encoder, stable `JobID`.

## 9. Dedupe and MMR diversification

Take the best 25 scored candidates after cluster collapse. Select ten iteratively:

```text
MMR(j) = lambda * normalized_final_score(j)
       - (1-lambda) * max_similarity(j, selected)
lambda = 0.70
```

Similarity blends description embedding (0.6), same company (0.2), role family (0.15), and location (0.05). Enforce at most two jobs per company and two per role family, unless fewer than ten eligible jobs exist; then relax role-family, then company caps while recording the relaxation. Duplicate-cluster members are mutually exclusive.

## 10. Explanations

Explanations are generated deterministically from stored features and evidence, with optional SLM phrasing that cannot add facts. JSON contract:

```json
{
  "job_id": 123,
  "rank": 1,
  "decision": "APPLY",
  "score": 88.4,
  "score_version": "top10-v1.0.0",
  "callback": {"band": "HIGH", "calibrated": false},
  "covered": [{"requirement_id": 9, "fact_ids": [41], "label": "DIRECT"}],
  "partial": [],
  "missing": [],
  "constraints": [{"name": "work_authorization", "status": "UNKNOWN"}],
  "top_contributors": [],
  "penalties": [],
  "retrieval": {"bm25_rank": 8, "dense_rank": 3, "rrf_rank": 2},
  "risks": [],
  "resume_strategy": []
}
```

Every statement cites requirement and fact IDs. Show why an adjacent skill did not count as direct. Never explain uncalibrated callback bands as probabilities.

## 11. Candidate fact base

### 11.1 Build

Parse DOCX/TXT/PDF into immutable source documents. DOCX uses paragraph/list/table traversal in document order; PDF uses text extraction and flags scanned/OCR content. Split facts into atomic clauses rather than whole paragraphs.

For each fact:

- preserve original text and source offsets;
- extract employer, role, project, dates, skills, action, scope, and metrics;
- store each numeric/entity mention in an allowlist;
- attach document hash and parser version;
- require user verification for ambiguous dates, merged bullets, inferred employers, or OCR uncertainty.

Only `VERIFIED` facts can support generated claims. `INFERRED` relations are separate objects and cannot be emitted as experience.

### 11.2 Evidence resolution

Retrieve fact candidates with BM25+dense+RRF per requirement, then classify `DIRECT/PARTIAL/ADJACENT/NONE/CONFLICTING`. A deterministic resolver checks skill IDs, dates, entities, and minimum years. An SLM may explain ambiguity but cannot upgrade evidence without rule support or user verification.

Edits create new fact revisions; prior facts remain immutable. Deleting a source retires dependent facts and invalidates affected resume variants.

## 12. Resume generation and verification

### 12.1 Selection

For a selected job:

1. Load classified requirements.
2. Retrieve verified facts for each requirement.
3. Produce covered/partial/unsupported/conflicting gap report.
4. Block or request policy choice for unsupported central mandatory requirements.
5. Select summary, skills, and bullets with:

```text
bullet_utility = 0.40*requirement_relevance
               + 0.25*impact
               + 0.20*recency
               + 0.15*evidence_confidence
```

Use a diversity penalty for repeated facts, technologies, and metrics. Preserve real employer/title/date chronology.

### 12.2 Constrained rewrite

The local generator receives only selected source facts, exact target requirement language, an entity/number allowlist, and a JSON Schema. It may reorder or compress supported concepts but may not introduce entities, numbers, technologies, ownership, causality, or superlatives. Return:

```json
{"text":"...", "source_fact_ids":[41,42], "used_requirement_ids":[9]}
```

Recommended bullet target is 20-35 words; allow longer only when readability tests pass. The older claim that 80-120 words per bullet is optimal is not adopted without evaluation because it conflicts with recruiter scanability.

### 12.3 Verification gates

For every sentence:

1. `NumericEntityChecker`: every number, date, employer, title, certification, product, and technology must occur in the cited fact allowlist or an approved canonical alias.
2. Provenance check: at least one valid verified FactID; source spans exist and hashes match.
3. NLI/semantic check: `ENTAILED | PARTIAL | UNSUPPORTED | CONTRADICTED`, with unsupported spans. Calibrate thresholds on domain data.
4. Contradiction checks across employer/title/date chronology.
5. Keyword check: supported target keywords only.
6. User approval: show source-to-draft diff, evidence, and all flags.

`UNSUPPORTED` or `CONTRADICTED` blocks export. `PARTIAL` requires edit/removal or explicit policy-approved wording such as “adjacent experience”; it cannot state direct experience.

## 13. ATS simulation and recruiter checks

Generate a single-column DOCX with standard headings, normal paragraphs, simple bullets, no headers/footers for critical data, no text boxes, graphics, or ATS-critical tables.

Simulation:

1. Build DOCX.
2. Parse the DOCX back through an independent extractor.
3. Compare extracted contact, headings, employers, titles, dates, bullets, skills, and order to the source representation.
4. Scan prohibited Unicode and control characters.
5. Validate chronology, required sections, page/word limits, supported keyword coverage, repetition, and density.
6. Optionally render to PDF only after DOCX passes; never treat PDF success as DOCX success.

Hard export gates:

- round-trip text recall >= 0.98;
- section recognition = 1.00 for required sections;
- employer/title/date extraction >= 0.95;
- unsupported claims = 0;
- prohibited critical characters = 0;
- no chronology contradiction;
- user approval present.

Soft warnings include low top-third relevance, repeated phrases, excessive density, weak action-impact structure, reading grade, overlong bullets, and page count. Market-specific personal fields must be opt-in configuration reviewed for legal/privacy appropriateness; they are not universal ATS requirements.

## 14. Local SLM routing and hardware profiles

`models.yaml` selects models by capability and measured available RAM/VRAM. Code never hardcodes names.

| Profile | Hardware | Extraction/generation | Embedding | Rerank | Verification |
|---|---|---|---|---|---|
| T1 | CPU, 8 GB RAM | Phi-4-mini Q4 or Qwen3-4B Q4 | Nomic v1.5 | BGE base | DeBERTa-v3-small |
| T2 | NVIDIA 8 GB | Qwen3-4B extraction; Qwen3-8B Q4 rewrite | BGE-M3 | Qwen3-Reranker-0.6B | DeBERTa-v3-base |
| T3 | NVIDIA 12-16 GB | Qwen3-8B/14B Q4 | BGE-M3 or validated Qwen embedding | Qwen3-Reranker-0.6B | DeBERTa-v3-large |
| T4 | NVIDIA 24 GB | Qwen3-14B/32B Q4 | Qwen embedding 4B or BGE-M3 | BGE v2-M3/larger validated model | DeBERTa-v3-large plus optional Qwen check |

Routing order:

1. deterministic implementation if possible;
2. smallest validated local model for schema extraction;
3. stronger local model for constrained rewriting/complex critique;
4. deterministic fallback and human review on failure;
5. cloud fallback disabled by default and never receives resume data without explicit consent.

Preflight checks Ollama health, model availability, RAM/VRAM headroom, and context length. On OOM, halve batch size, unload unrelated models, route down one tier, then use deterministic fallback. Limit concurrency to one generator plus one lightweight embedding/rerank worker on <=8 GB VRAM.

## 15. Prompt and model version management

Each prompt is a directory artifact:

```text
prompts/templates/job_requirement_extract/v1.2.0.jinja2
prompts/schemas/job_requirement_extract/v1.2.0.json
prompts/tests/job_requirement_extract/*.json
```

`PromptVersion` records semantic version, content SHA-256, schema SHA-256, task, compatible models, decoding parameters, author/reason, evaluation run, approval, and activation dates.

Rules:

- prompts are immutable after activation;
- exact system/user prompt, model digest, tokenizer, temperature, seed where supported, and schema version are logged;
- temperature is 0-0.2 for extraction/verification and <=0.3 for rewrite;
- JSON grammar/schema-constrained decoding is preferred;
- prompt activation is blocked unless the golden regression suite passes;
- rollback changes a config pointer; old artifacts remain reproducible;
- secrets and unnecessary PII are redacted from logs;
- `RAG_MASTER_PROMPT.md` supplies zero-fabrication rules, but is split into task-specific prompts rather than copied into every request.

## 16. Evaluation datasets, metrics, and release gates

### 16.1 Datasets

Maintain local, versioned JSONL datasets with source hashes:

1. `jobs_parse_gold`: >=200 diverse JDs; human-labeled spans, requirement class, title, seniority, location, and constraints.
2. `retrieval_gold`: >=100 candidate-query snapshots with pooled relevance judgments across lexical/dense results.
3. `ranking_gold`: >=100 daily candidate sets, graded 0-3 by the user; include difficult mandatory mismatches.
4. `dedupe_gold`: >=250 job pairs across exact, repost, agency mirror, boilerplate-similar, and genuinely distinct cases.
5. `facts_gold`: >=150 resume sentences with atomic facts, entities, metrics, chronology, and provenance.
6. `claims_adversarial`: unsupported metric, adjacent-as-direct skill, employer/date swap, inflated ownership, causality, certification, and negation.
7. `ats_gold`: clean and deliberately broken DOCX fixtures: tables, columns, text boxes, Unicode, headers, missing dates, scanned PDF.
8. `outcomes`: temporally split closed applications; no-response remains censored until its window closes.

Exclude generated variants of the same job/resume from both train and test. Split by company and time to reduce leakage. Every labeling change creates a new dataset version.

### 16.2 Metrics

- Parsing: exact/span F1, per-class macro F1, mandatory recall, schema validity, expected calibration error.
- Canonicalization: canonical-ID accuracy, alias ambiguity rate, location/title accuracy.
- Dedupe: pair precision/recall/F1, cluster B-cubed F1; track false merges separately.
- Retrieval: Recall@100/300, MRR, NDCG@10, lexical-only vs dense-only vs fusion ablation.
- Rerank/ranking: NDCG@10, Precision@10, Recall@10 of 3-rated jobs, mandatory mismatch rate, duplicate rate, diversity, acceptance rate.
- Explanation: requirement/fact citation precision, feature-value fidelity, unsupported statement rate.
- Generation: truthfulness ratio, unsupported count, entity/number preservation, bullet relevance, user edit distance.
- ATS: parse success, text/order recall, section/employer/title/date extraction.
- Operations: p50/p95 stage latency, model failure/fallback rate, ingestion freshness, DLQ rate, credit usage.
- Outcome model after enough data: Brier score, log loss, ROC-AUC, ECE, calibration slope/intercept, callback rate by score band.

### 16.3 V1 release gates

| Area | Blocking gate |
|---|---|
| Requirement parsing | mandatory recall >=0.95; macro F1 >=0.85; schema validity >=0.995 |
| Canonicalization | skill/title/location accuracy >=0.95 |
| Dedupe | precision >=0.98; recall >=0.90; zero known cross-requisition false merge |
| Retrieval | Recall@300 >=0.95 and RRF NDCG@10 not worse than best single retriever |
| Ranking | Precision@10 >=0.80; mandatory mismatch <=0.02; duplicate top-10 rate = 0 |
| Explanations | citation precision = 1.00; numeric feature fidelity = 1.00 |
| Resume | unsupported claim count = 0 on all golden and adversarial cases |
| ATS | round-trip recall >=0.98; required-section success = 1.00 |
| Regression | no critical gate regression; NDCG decline <=0.02 absolute |
| Performance | daily CPU profile <=30 minutes; GPU profile <=10 minutes, excluding network fetch |

Weights/prompts/models ship through shadow evaluation first. Callback optimization is not a release gate before sufficient outcomes.

## 17. Reference pseudocode

### 17.1 Daily ingestion

```python
def ingest_daily(run):
    preflight(sql=True, ollama=True, credits=True)
    for request in scheduler.requests_for_today():
        try:
            envelope = source.fetch(request)
            raw_store.put(envelope)
            for raw in envelope.jobs:
                parsed = parser.clean_and_parse(raw)
                canonical = canonicalizer.apply(parsed)
                decision = deduplicator.classify(canonical)
                if decision.exact_duplicate:
                    repository.observe_duplicate(decision.cluster_id, envelope)
                    continue
                chunks = chunker.split(canonical)
                vectors = embedder.embed_cached(chunks)
                with repository.transaction():
                    job_id = repository.upsert_job(canonical, decision)
                    repository.replace_chunks(job_id, chunks, vectors)
                    repository.replace_requirements(job_id, parsed.requirements)
                bm25_index.stage(job_id, chunks)
        except RetryableError as error:
            dlq.write(request, error)
        finally:
            credit_ledger.record(request)
    bm25_index.atomic_commit()
```

### 17.2 Ranking

```python
def rank_top10(candidate_id, as_of):
    profile, facts = repo.load_candidate(candidate_id)
    query = query_builder.build(profile, facts)
    bm25, dense = parallel(
        lambda: bm25_retriever.top(query.lexical, 300),
        lambda: dense_retriever.top(query.vector, 300),
    )
    fused = rrf(bm25, dense, k=60)[:500]
    gated = [j for j in fused if constraints.evaluate(profile, j) != FAIL]
    reranked = cross_encoder.rerank(query.summary, gated[:100])
    scored = []
    for job in reranked:
        evidence = evidence_resolver.resolve(job.requirements, facts)
        scored.append(fit_scorer.score(profile, job, evidence))
    representatives = collapse_duplicate_clusters(scored)
    selected = mmr(representatives[:25], count=10, lambda_=0.70)
    return [explainer.build(item) for item in selected]
```

### 17.3 Resume generation

```python
def generate_resume(job_id, candidate_id):
    requirements = repo.requirements(job_id)
    facts = repo.verified_facts(candidate_id)
    mapping = evidence_resolver.resolve(requirements, facts)
    gaps = gap_detector.classify(mapping)
    approval_gate.require_gap_policy(gaps.central_unsupported)
    selected = bullet_selector.select(mapping)
    drafts = []
    for source in selected:
        draft = rewriter.rewrite(source, schema=BulletSchema)
        entity_result = entity_checker.check(draft, source.allowlist)
        nli_result = claim_verifier.verify(draft.text, source.facts)
        if not entity_result.pass_ or nli_result.label in {"UNSUPPORTED", "CONTRADICTED"}:
            drafts.append(flagged(draft, entity_result, nli_result))
        else:
            drafts.append(verified(draft, nli_result))
    document = assembler.assemble(drafts)
    ats = ats_simulator.round_trip(document)
    readability = readability_scorer.score(document)
    decision = approval_gate.present(document, drafts, ats, readability)
    if decision.approved and export_gates_pass(drafts, ats):
        path = docx_builder.build(document)
        provenance.write(path, drafts, decision)
        return path
    raise ExportBlocked(decision.reasons)
```

## 18. Edge cases and failure handling

| Case | Required behavior |
|---|---|
| API 429/5xx | Retry with jitter/`Retry-After`; continue partial run; record credit uncertainty. |
| API schema drift | Preserve raw payload, fail schema validation, DLQ, alert; do not write partial canonical rows. |
| Missing/empty JD | Store observation as incomplete; exclude from ranking or use title-only with explicit low confidence. |
| Same job, different URLs | Cluster; preserve sources; choose canonical representative. |
| Same boilerplate, different requisitions | Do not merge without title/location/requisition support. |
| Missing posted date | Freshness=0.4, status unknown; never invent date. |
| Ambiguous acronym | Contextual taxonomy resolution or `UNKNOWN`; no direct evidence credit. |
| Conflicting mandatory/preferred language | Mandatory wins only with explicit rule evidence; otherwise SLM plus human-review flag. |
| Missing sponsorship/salary | Gate `UNKNOWN`, not `FAIL`; explain uncertainty. |
| Non-English JD | Preserve and flag; optional separate translation with provenance. |
| Very long JD/resume | Atomic field chunks; no head-only truncation; token-aware batching. |
| Embedding model change | Build parallel index; evaluate; atomic activation; keep old version. |
| BM25 index corrupt | Rebuild from SQL; dense-only degraded run; alert. |
| Dense/vector service unavailable | BM25-only degraded run; do not fabricate neutral dense ranks. |
| Reranker timeout/OOM | Reduce batch, route lower tier, then use RRF order. |
| Invalid model JSON | Grammar/schema retry up to three; deterministic fallback; human flag. |
| SLM adds metric/entity | Deterministic checker blocks sentence before NLI. |
| NLI uncertain | Treat as partial/unsupported according to calibrated threshold; require review. |
| User edits generated bullet | Re-run entity, provenance, NLI, and ATS checks on edited content. |
| Scanned PDF resume | Flag OCR requirement/low confidence; no automatic verified facts. |
| DOCX parser order differs | Block export; eliminate table/column/text-box construct and rebuild. |
| SQL deadlock/timeout | Transaction retry up to three; idempotent key prevents duplication. |
| SQL constraint/schema error | No retry; DLQ sanitized record and alert. |
| Credit exhaustion | Stop fetch; continue parsing/ranking existing jobs and notify renewal state. |
| Crash mid-run | Resume from processing states/idempotency keys; atomic index commits. |
| Fewer than ten eligible jobs | Return fewer than ten before relaxing eligibility; only diversity caps may relax. |
| No verified facts | Disable generation; direct user to fact-base verification. |
| Outcome not yet observed | Keep censored, exclude from negative training until 21-30-day window closes. |

Operational events are structured JSON with `run_id`, `stage`, `record_id`, versions, duration, retry count, degraded flags, and sanitized error. PII and prompt bodies are not written to normal logs.

## 19. Existing script reuse/refactor map

| Existing artifact | Action | Target | Required changes |
|---|---|---|---|
| `google_jobs_scraper_FIXED.py` | Refactor | `scraper/serpapi_fetcher.py` | remove/rotate embedded secret; inject client/config; remove globals; retries; typed output |
| `google_jobs_scraper_beast_mode.py` | Extract only | `scraper/utils.py` | reuse dual-key dedupe and region ideas; case/Unicode normalize; replace runner |
| `debug_serpapi.py` | Refactor | integration tests | env key, assertions, sanitized fixtures, no raw response leakage |
| `smart_scheduler.py` | Refactor | `scheduler/credit_ledger.py` | fix `json.dump(tracker, f, indent=2)`; file lock; configurable plans; atomic writes |
| `comprehensive_ats_validation_all_platforms.py` | Refactor | `validators/ats_rules.py`, `ats_simulator.py` | preserve broad Unicode/format checks; parameterize; return typed report |
| `ats_comprehensive_validator.py` | Extract | `validators/ats_rules.py` | Unicode map and quantity regex only; remove personal/hardcoded tests |
| `ats_validator.py` | Refactor, not truth gate | `validators/llm_validator.py` | local router; schema validation; remove f-string comment leak; implement real cache or remove claim; PDF handling |
| `ats_score_calculator.py` | Extract | `validators/keyword_scorer.py` | retain pure keyword matcher; remove person-specific checks |
| `keyword_density_analysis.py` | Refactor | `validators/keyword_density.py` | parameterize role, path, thresholds; treat old thresholds as unvalidated |
| `extract_all_resumes.py` | Refactor | `factbase/resume_parser.py` | no runtime package installation; use `pypdf`; provenance spans and OCR flags |
| `extract_keywords_and_search.py` | Split | taxonomy/parser modules | reuse extraction ideas; separate search execution |
| `legacy_resume_builder.py` | Extract helpers | `docx_builder/helpers.py` | margins, headings, bullets; remove embedded resume content |
| `create_final_resume_v2.py` | Refactor | `docx_builder/docx_builder.py` | typed content model; deterministic layout; round-trip tests |
| `RAG_MASTER_PROMPT.md` | Source material | task prompt library | split/version; retain zero-fabrication and factuality policy |
| `MASTER_ATS_VALIDATION_PROMPT.md` | Source material | ATS prompt tests/templates | separate deterministic rules from model critique |
| `RAG_JOB_SEARCH_ARCHITECTURE_REVIEW.md` | Design input | migrations and ADRs | parameterized SQL; reconcile schema; do not execute snippets directly |
| Other scraper/generator/patch/validator variants | Archive | `archive/` | no production imports |
| `requirements.txt` | Replace | locked project dependencies | add actual runtime/test dependencies; pin and audit |

Immediate blockers inherited from the audit:

1. Rotate exposed SerpAPI credentials and remove all literals.
2. Fix the scheduler `json.dump` call.
3. Build the canonical schema and fact base before resume generation.
4. Add tests and dependency management; current scripts have no shared library or reliable test suite.

## 20. Implementation sequence and definition of done

1. **Security/foundation:** rotate secrets, package skeleton, config, logging, migrations, typed contracts.
2. **Fact base:** source ingestion, atomic facts, verification UI, provenance tests.
3. **Job ingestion:** connector, raw store, parsing, canonicalization, exact/fuzzy dedupe, credit ledger.
4. **Retrieval:** taxonomy, BM25, embeddings, cache, RRF, retrieval gold set.
5. **Ranking:** gates, evidence resolver, cross-encoder, formula, MMR, deterministic explanations.
6. **Generation:** selection, constrained local rewrite, deterministic entity checks, NLI, approval.
7. **ATS:** DOCX builder, independent round-trip parser, readability and export gates.
8. **Evaluation/operations:** golden suites, regression CLI, Task Scheduler, DLQ recovery, health reports.
9. **Feedback:** application tracking and descriptive analytics; calibrated callback model only after data gate.

The pipeline is V1-ready only when all Section 16 blocking gates pass on frozen local datasets, a complete daily run is reproducible from version records, and no resume can be exported without verified facts, zero unsupported claims, ATS round-trip success, and explicit approval.



