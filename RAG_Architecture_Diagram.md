# RAG ARCHITECTURE DIAGRAM - COMPLETE SYSTEM
**Intelligent Job Matching + Resume Generation + Career Development**

---

## FULL SYSTEM ARCHITECTURE (Mermaid)

```mermaid
graph TB
    subgraph "Data Ingestion Layer"
        A[SerpAPI/JSearch API] --> B[Job Scraper Service]
        B --> C[Deduplication Engine]
        C --> D[(Jobs Table<br/>SQL Server 2025)]
        D --> D1[Job Metadata]
        D --> D2[Job Description]
    end

    subgraph "Embedding & Vector Layer"
        D --> E[sentence-transformers<br/>all-MiniLM-L6-v2]
        E --> F[Vector Storage<br/>VECTOR 384]

        G[Master Resume<br/>100% ATS Compliant] --> H[Component Parser]
        H --> I[(MasterResumeComponents<br/>Table)]
        I --> E

        F --> J[Semantic Search<br/>Top-50 Jobs]
        J --> K{Cache Check}
    end

    subgraph "Token-Optimized Analysis Layer"
        K -->|Cache Hit 20%| L[Cached Analysis<br/>0 tokens]
        K -->|Cache Miss 80%| M[Gemini 2.5 Flash<br/>Batch Processing]

        M --> N[Context Compression<br/>70% reduction]
        N --> O[Batch Prompt<br/>50 jobs → 8K tokens]
        O --> P[LLM Response<br/>JSON Array]

        P --> Q[Skill Gap Extraction]
        Q --> R[(SkillGaps Table)]
        Q --> S[(JobSkillMatches Table)]

        L --> T[Analysis Results]
        P --> T
    end

    subgraph "Resume Generation Layer"
        U[Job Requirements] --> V{Resume Cache?}
        V -->|Hit 60%| W[Cached Resume<br/>0 tokens]
        V -->|Miss 40%| X[Vector Component Search<br/>0 tokens]

        X --> Y[Component Selection]
        I --> Y

        Y --> Z[Template Assembly<br/>0 tokens]
        Z --> AA[Gemini 2.5 Flash<br/>ATS Validation 500 tokens]

        AA --> AB[ATS Score Check]
        AB -->|Score ≥ 95| AC[Generate DOCX]
        AB -->|Score < 95| AD[Regenerate]

        AC --> AE[(GeneratedResumes Table)]
        AE --> AF[DOCX File Output]

        W --> AF
    end

    subgraph "Weekly Summary Layer"
        AG[Weekly Trigger] --> AH[SQL Aggregation<br/>0 tokens]

        R --> AH
        S --> AH
        D --> AH

        AH --> AI[Weekly Statistics]
        AI --> AJ[Top 10 Skill Gaps]
        AI --> AK[Job Fit Distribution]
        AI --> AL[Recommended Jobs]

        AJ --> AM[Gemini 2.5 Pro<br/>Summary Generation<br/>6K tokens]
        AK --> AM
        AL --> AM

        AM --> AN[(WeeklySummaries Table)]
    end

    subgraph "Upskilling Intelligence Layer"
        AN --> AO[Top 5 Skill Gaps]
        AO --> AP[(LearningResources DB<br/>Pre-populated)]

        AP --> AQ[Resource Lookup<br/>0 tokens]
        AQ --> AR[Gemini 2.5 Pro<br/>Path Generation<br/>4K tokens]

        AR --> AS[2-Month Learning Path]
        AS --> AT[(LearningPaths Table)]

        AT --> AU[Month 1 Plan]
        AT --> AV[Month 2 Plan]
        AT --> AW[Learning Resources]
    end

    subgraph "Output & Reporting Layer"
        AF --> AX[Resume Library]
        AN --> AY[Weekly Report PDF]
        AT --> AY

        AY --> AZ[Email Delivery]
        AX --> BA[Resume Download]
    end

    subgraph "Token Optimization System"
        BB[Prompt Cache Manager<br/>Gemini Feature]
        BC[Context Compression<br/>70% reduction]
        BD[Batch Queue<br/>50 jobs/batch]
        BE[Model Router<br/>Flash vs Pro]

        BB -.->|Cached prompts| M
        BC -.->|Compressed contexts| O
        BD -.->|Batched requests| M
        BE -.->|Cost optimization| M
        BE -.->|Cost optimization| AM
    end

    subgraph "Monitoring & Analytics"
        BF[(TokenUsageLog Table)]
        M --> BF
        AA --> BF
        AM --> BF
        AR --> BF

        BF --> BG[Cost Dashboard]
        BG --> BH[Monthly Budget: $0.78]
        BG --> BI[Cache Hit Rate: 60%]
        BG --> BJ[Avg Tokens/Job: 160]
    end

    style M fill:#e1f5ff
    style AA fill:#e1f5ff
    style AM fill:#ffe1e1
    style AR fill:#ffe1e1
    style BB fill:#fff4e1
    style BC fill:#fff4e1
    style BD fill:#fff4e1
    style BE fill:#fff4e1
```

---

## DETAILED LAYER BREAKDOWN

### Layer 1: Data Ingestion (Traditional RAG)
**Components:**
- SerpAPI/JSearch for job scraping
- Deduplication engine (remove duplicates)
- Jobs table in SQL Server 2025

**Token Cost:** 0 (no LLM usage)

---

### Layer 2: Embedding & Vector Search
**Components:**
- sentence-transformers (all-MiniLM-L6-v2) for embeddings
- SQL Server 2025 VECTOR(384) storage
- Master resume component parser
- Semantic search for top-50 jobs

**Token Cost:** 0 (local embedding model)

**Cache Hit Rate:** 20% (jobs already analyzed)

---

### Layer 3: Token-Optimized Job Analysis
**Components:**
- Context compression (2,000 tokens → 100 tokens per job)
- Batch processing (50 jobs in single call)
- Gemini 2.5 Flash (cheaper model)
- Prompt caching (master resume cached)
- Skill gap extraction (parsed from JSON)

**Token Cost:** 8,000 tokens/batch
**Optimization:** 92% reduction (vs 100K individual calls)

---

### Layer 4: Resume Generation
**Components:**
- 3-tier caching:
  - Database cache (60% hit rate)
  - Vector similarity (20% hit rate)
  - Component assembly (15%)
  - LLM generation (5%)
- Template-based assembly (0 tokens)
- Gemini 2.5 Flash for ATS validation only

**Token Cost:** 500 tokens/resume (average 200 with caching)
**Optimization:** 88% reduction (vs 4K full generation)

---

### Layer 5: Weekly Summary
**Components:**
- SQL aggregation (0 tokens, pure database)
- Weekly statistics calculation
- Single Gemini 2.5 Pro call for narrative
- PDF report generation

**Token Cost:** 6,000 tokens/week
**Optimization:** 95% reduction (vs 125K daily individual summaries)

---

### Layer 6: Upskilling Intelligence
**Components:**
- Top 5 skill gaps from weekly analysis
- Pre-populated learning resources database (0 tokens)
- Single Gemini 2.5 Pro call for 2-month path
- Month 1 & Month 2 structured plans

**Token Cost:** 4,000 tokens/week
**Optimization:** Pre-populated resources eliminate lookup LLM calls

---

### Layer 7: Token Optimization System
**Components:**
1. **Prompt Cache Manager:** Cache master resume for 1 hour (700K tokens saved/month)
2. **Context Compression:** 70% token reduction per job
3. **Batch Queue:** Aggregate 50 jobs per call
4. **Model Router:** Flash for simple, Pro for complex (88% cost savings)

**Monthly Savings:** 2.75M tokens ($3.44/month)

---

### Layer 8: Monitoring & Analytics
**Components:**
- TokenUsageLog table (track all LLM calls)
- Cost dashboard
- Cache hit rate monitoring
- Budget alerts

**Metrics Tracked:**
- Monthly cost: $0.78 target
- Cache hit rate: 60% target
- Avg tokens/job: 160 target

---

## DATA FLOW EXAMPLES

### Example 1: New Job Posted

```
Job Posted: "Principal PostgreSQL DBA - AWS - Sydney"
    ↓
Vector Search: Similarity to master resume = 0.75
    ↓
Top 50 Jobs: Rank #8
    ↓
Cache Check: Not analyzed yet
    ↓
Batch Processing: Added to queue (wait for 50 jobs)
    ↓
Gemini Analysis (batched): Fit score 65%, Gaps: [PostgreSQL, AWS RDS]
    ↓
SkillGaps Table: INSERT PostgreSQL (CRITICAL), AWS RDS (HIGH)
    ↓
JobSkillMatches Table: INSERT TotalSkills=3, Matched=1, Missing=2, Match%=33%
```

**Tokens Used:** 160 (1/50th of 8K batch)

---

### Example 2: Generate Resume for Job

```
User Request: Generate resume for Job #12345
    ↓
Cache Check: No cached resume found
    ↓
Vector Search: Select relevant components
    Components: [Summary_Azure, Experience_Microsoft, Skills_Database]
    ↓
Template Assembly: Assemble from components (0 tokens)
    ↓
Gemini Flash Validation: "Validate ATS compliance for Principal DBA role"
    Response: {"ats_score": 97, "keyword_density": 88.5, "suggestions": []}
    ↓
DOCX Generation: Create Word file
    ↓
Save: Resume #789, ATS Score 97%, 500 tokens used
```

**Tokens Used:** 500 (vs 4,000 full generation)

---

### Example 3: Weekly Summary Generation

```
Sunday 11:59 PM: Weekly trigger fires
    ↓
SQL Aggregation:
    - Jobs analyzed: 42
    - High fit (80%+): 8 jobs
    - Medium fit: 18 jobs
    - Top gaps: [PostgreSQL, AWS RDS, Kubernetes, Terraform, Go]
    ↓
Gemini Pro Summary: "Generate executive summary for week 12..."
    Response: {
        "summary": "Strong week with 8 high-fit opportunities...",
        "insights": ["PostgreSQL appearing in 15/42 jobs", ...],
        "recommendations": ["Focus on PostgreSQL certification", ...]
    }
    ↓
Gemini Pro Upskilling: "Create 2-month path for [PostgreSQL, AWS RDS]..."
    Response: {
        "month_1": {
            "week_1": {"focus": "PostgreSQL Basics", "resources": [...], "project": "..."}
        }
    }
    ↓
PDF Generation: Weekly report with summary + upskilling path
    ↓
Email Delivery: Send to user
```

**Tokens Used:** 10,000 (6K summary + 4K upskilling)

---

## TOKEN BUDGET BREAKDOWN

| Operation | Daily | Weekly | Monthly | Cost/Month |
|-----------|-------|--------|---------|------------|
| Job Analysis (Gemini Flash) | 8K | 56K | 240K | $0.036 |
| Resume Generation (Flash) | 800 | 5.6K | 24K | $0.0036 |
| Weekly Summary (Pro) | - | 6K | 24K | $0.03 |
| Upskilling Path (Pro) | - | 4K | 16K | $0.02 |
| **TOTAL INPUT** | **8.8K** | **71.6K** | **304K** | **$0.090** |
| **Output Tokens** | - | - | ~80K | $0.048 |
| **GRAND TOTAL** | - | - | **384K** | **$0.138** |

**Note:** Actual cost is lower due to caching (60% hit rate on resume generation)

**Realistic Monthly Cost:** $0.078 (with caching optimizations)

---

## CACHE EFFICIENCY ANALYSIS

### Resume Generation Cache Layers

```
100 resume requests
    ├─ 60% Database cache hit → 0 tokens (60 requests)
    ├─ 20% Vector similarity → 0 tokens (20 requests)
    ├─ 15% Component assembly → 0 tokens (15 requests)
    └─ 5% LLM generation → 500 tokens each (5 requests)

Total tokens: (60×0) + (20×0) + (15×0) + (5×500) = 2,500 tokens
Average: 25 tokens/resume

Without cache: 100 × 4,000 = 400,000 tokens
Savings: 99.4% (397,500 tokens)
```

### Job Analysis Cache

```
50 jobs in daily batch
    ├─ 10 jobs already analyzed (cache hit) → 0 tokens
    └─ 40 jobs need analysis → 8,000 tokens (batched)

Without cache: 50 × 2,000 = 100,000 tokens
With cache + batch: 8,000 tokens
Savings: 92% (92,000 tokens)
```

---

## SYSTEM PERFORMANCE METRICS

### Response Times (Target)
- Job analysis: <5 seconds (batch of 50)
- Resume generation: <3 seconds (with cache)
- Weekly summary: <10 seconds
- Upskilling path: <8 seconds

### Accuracy Targets
- ATS score: ≥95% (generated resumes)
- Skill gap accuracy: ≥90%
- Learning resource relevance: ≥85%

### Scalability
- Jobs/day: 50 (expandable to 500 with same token budget)
- Resumes/week: 4-10 (expandable to 100)
- Users: Linear scaling ($0.78/user/month)

---

## TECHNOLOGY STACK

### Backend
- **Python 3.11+** - Core application logic
- **FastAPI** - REST API endpoints
- **SQL Server 2025** - Database with VECTOR support

### AI/ML
- **Gemini 2.5 Flash** - Cost-efficient analysis
- **Gemini 2.5 Pro** - Complex reasoning (summaries)
- **sentence-transformers** - Local embeddings (0 cost)

### Storage
- **SQL Server VECTOR(384)** - Embeddings
- **PostgreSQL** - Alternative if needed
- **Redis** - Prompt caching layer

### Frontend (Future)
- **React/Next.js** - Web dashboard
- **Tailwind CSS** - Styling
- **Chart.js** - Analytics visualization

---

## DEPLOYMENT ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────┐
│                     Production Environment                   │
│                                                               │
│  ┌──────────────┐      ┌──────────────┐      ┌───────────┐ │
│  │   FastAPI    │─────▶│  SQL Server  │◀─────│   Redis   │ │
│  │   (API)      │      │    2025      │      │  (Cache)  │ │
│  └──────┬───────┘      └──────┬───────┘      └───────────┘ │
│         │                     │                              │
│         ▼                     ▼                              │
│  ┌──────────────┐      ┌──────────────┐                    │
│  │   Gemini     │      │  sentence-   │                    │
│  │   API        │      │  transformers│                    │
│  └──────────────┘      └──────────────┘                    │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Monitoring & Logging                     │  │
│  │  - Token usage tracking                               │  │
│  │  - Cost monitoring                                    │  │
│  │  - Performance metrics                                │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

**Architecture Status:** ✅ COMPLETE

**Next Step:** Implement database schema and core pipelines


