# Additional research

This folder contains independently reviewed, publication-sanitized research that supplements the repository's canonical ATS/RAG documentation. It is **not part of the canonical ATS/RAG design or implementation baseline**; use [`../docs/00-START-HERE.md`](../docs/00-START-HERE.md) for canonical guidance.

## Scope

Only the requested PostgreSQL, SQL Server, migration, prompt-engineering, and March 2026 DBA-market research artifacts are included. No raw job exports, resumes, candidate records, contact lists, credentials, private endpoints, or generated binary documents are included.

## Provenance and review

The material was prepared from a separate local source workspace and copied into this package without modifying that workspace. Publication review on **2026-08-03** removed or rewrote private/local details, unsafe prescriptions, uncertain proprietary attribution, hardcoded secrets, and obvious technical inaccuracies. Public links were retained where relevant; retention is provenance, not independent factual verification.

All examples, interview questions, incidents, organizations, accounts, paths, and production scenarios are hypothetical unless a public source is explicitly cited.

## Date and version sensitivity

- PostgreSQL internals, statistics, defaults, extensions, and monitoring views vary by version; verify against the exact target release.
- SQL Server/Azure SQL features, DMVs, editions, compatibility levels, cumulative updates, and tooling vary by release and service tier.
- Migration tools, drivers, cloud services, and platform support change over time.
- AI model capabilities, context limits, pricing, benchmarks, safety guidance, and framework behavior are time-sensitive.
- All market findings, salaries, counts, forecasts, and aggregate CSV values are labeled **as of March 2026** and are directional rather than posting-level evidence.

## Contents

- [`postgresql/`](postgresql/README.md): storage, MVCC, vacuum, buffer management, query processing, and hypothetical Windows scenarios.
- [`migration/sql-server-to-postgresql.md`](migration/sql-server-to-postgresql.md): version-sensitive migration study guide.
- [`sql-server/l3-l4-scenario-guide.md`](sql-server/l3-l4-scenario-guide.md): hypothetical senior-level SQL Server scenarios.
- [`ai/prompt-engineering-study-guide.md`](ai/prompt-engineering-study-guide.md): time-sensitive prompt-engineering research.
- [`market/dba-2026/`](market/dba-2026/README.md): aggregate DBA market research as of March 2026.
