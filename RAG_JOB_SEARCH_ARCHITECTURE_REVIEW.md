# RAG JOB SEARCH SYSTEM - ARCHITECTURE REVIEW & IMPLEMENTATION PLAN

---

## EXECUTIVE SUMMARY

**Your Architecture: 9/10** - Exceptionally well-designed for a learning project with real business value.

**Key Strengths:**
- ✅ Local-first (no cloud dependencies, cost-effective)
- ✅ SQL Server 2025 native vectors (cutting-edge, no separate vector DB needed)
- ✅ Legal data sources (JSearch API avoids LinkedIn ToS violations)
- ✅ Hybrid approach (local embeddings + cloud LLM for analysis)
- ✅ Clear business outcome (automated job search + skill gap identification)

**Timeline: 2 months - Realistic** ✓

---

## ARCHITECTURE VALIDATION

### ✅ **1. DATA INGESTION LAYER (Python ETL)**

**Your Design:**
```
Python 3.10+ → requests, feedparser, beautifulsoup4
Sources: ATS APIs (Greenhouse, Lever), RSS feeds, JSearch API
```

**Assessment: EXCELLENT**

**Strengths:**
- Legal data sources (avoids scraping violations)
- Multiple source diversity (reduces single-point failure)
- JSearch API is the RIGHT choice for LinkedIn/Indeed access

**Recommendations:**

#### **Add Rate Limiting & Error Handling:**
```python
import time
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Robust session with retries
def create_session():
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Rate limiting
def rate_limited_fetch(url, delay=1):
    response = session.get(url)
    time.sleep(delay)  # Respect API limits
    return response
```

#### **Data Source Priority:**

| Source | Priority | Jobs/Day | Cost | Reliability |
|--------|----------|----------|------|-------------|
| **JSearch API (RapidAPI)** | HIGH | 1,000+ | $9.99/mo | High |
| **Greenhouse/Lever APIs** | HIGH | 500+ | Free | High |
| **RSS Feeds (WWR, Remotive)** | MEDIUM | 200+ | Free | Medium |

**Recommended JSearch API Plan:**
- **Basic Plan**: $9.99/month, 500 requests/month
- **Pro Plan**: $29.99/month, 2,500 requests/month ← Recommended for 2-month project

**JSearch API Sample:**
```python
import requests

url = "https://jsearch.p.rapidapi.com/search"
headers = {
    "X-RapidAPI-Key": "YOUR_API_KEY",
    "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
}
params = {
    "query": "Principal Database Engineer",
    "page": "1",
    "num_pages": "1",
    "date_posted": "week"  # Last 7 days
}

response = requests.get(url, headers=headers, params=params)
jobs = response.json()['data']
```

---

### ✅ **2. STORAGE & RETRIEVAL LAYER (SQL Server 2025)**

**Your Design:**
```
SQL Server 2025 → VECTOR(384) data type → VECTOR_DISTANCE function
Embeddings: sentence-transformers (all-MiniLM-L6-v2)
```

**Assessment: CUTTING-EDGE**

**This is brilliant.** SQL Server 2025's native vector support eliminates the need for Pinecone, Weaviate, or Chroma.

**Key Features:**
- `VECTOR(384)` data type (matches all-MiniLM-L6-v2 output dimensions)
- `VECTOR_DISTANCE()` function (cosine similarity)
- T-SQL for vector search (no need to learn separate vector DB query language)

**Schema Recommendation:**

```sql
-- Jobs table with native vector support
CREATE TABLE dbo.Jobs (
    JobID INT IDENTITY(1,1) PRIMARY KEY,
    JobTitle NVARCHAR(255) NOT NULL,
    Company NVARCHAR(255) NOT NULL,
    Location NVARCHAR(255),
    Salary NVARCHAR(100),
    JobDescription NVARCHAR(MAX) NOT NULL,
    JobURL NVARCHAR(500),
    Source NVARCHAR(50),  -- 'JSearch', 'Greenhouse', 'RSS'
    DatePosted DATETIME2 DEFAULT GETDATE(),
    DateIngested DATETIME2 DEFAULT GETDATE(),

    -- Vector embedding (384 dimensions for all-MiniLM-L6-v2)
    DescriptionVector VECTOR(384),

    -- Metadata
    IsActive BIT DEFAULT 1,
    LastProcessed DATETIME2
);

-- Index for vector similarity search
CREATE INDEX IDX_Jobs_DescriptionVector
ON dbo.Jobs(DescriptionVector);

-- Master resume vector (single row)
CREATE TABLE dbo.MasterResume (
    ResumeID INT IDENTITY(1,1) PRIMARY KEY,
    ResumeText NVARCHAR(MAX) NOT NULL,
    ResumeVector VECTOR(384),
    LastUpdated DATETIME2 DEFAULT GETDATE()
);

-- Job matches with similarity scores
CREATE TABLE dbo.JobMatches (
    MatchID INT IDENTITY(1,1) PRIMARY KEY,
    JobID INT FOREIGN KEY REFERENCES dbo.Jobs(JobID),
    SimilarityScore FLOAT,  -- Cosine similarity (0-1)
    MatchDate DATETIME2 DEFAULT GETDATE(),
    LLMAnalyzed BIT DEFAULT 0,
    FitScore INT,  -- 0-100 from Gemini
    MatchingSkills NVARCHAR(MAX),  -- JSON array
    MissingSkills NVARCHAR(MAX)   -- JSON array
);
```

**Vector Similarity Query:**

```sql
-- Find top 50 jobs matching master resume
DECLARE @ResumeVector VECTOR(384);

-- Get master resume vector
SELECT @ResumeVector = ResumeVector
FROM dbo.MasterResume
WHERE ResumeID = 1;

-- Semantic search using VECTOR_DISTANCE
INSERT INTO dbo.JobMatches (JobID, SimilarityScore)
SELECT TOP 50
    JobID,
    1 - VECTOR_DISTANCE('cosine', DescriptionVector, @ResumeVector) AS SimilarityScore
FROM dbo.Jobs
WHERE IsActive = 1
  AND DatePosted >= DATEADD(day, -7, GETDATE())  -- Last 7 days
  AND LLMAnalyzed = 0  -- Not yet analyzed
ORDER BY SimilarityScore DESC;

-- Retrieve for LLM analysis
SELECT
    j.JobID,
    j.JobTitle,
    j.Company,
    j.Location,
    j.Salary,
    j.JobDescription,
    j.JobURL,
    jm.SimilarityScore
FROM dbo.JobMatches jm
INNER JOIN dbo.Jobs j ON jm.JobID = j.JobID
WHERE jm.LLMAnalyzed = 0
ORDER BY jm.SimilarityScore DESC;
```

**Why This Works:**
- ✅ No external vector database needed
- ✅ T-SQL skills transfer directly
- ✅ Native SQL Server performance optimizations
- ✅ Familiar tooling (SSMS, Azure Data Studio)
- ✅ Transactional consistency (ACID properties)

---

### ⚠️ **POTENTIAL CHALLENGE: SQL Server 2025 Availability**

**Issue:** SQL Server 2025 is in **preview** (RC0 released Dec 2024).

**Solutions:**

**Option 1: Use SQL Server 2025 Preview (Recommended for Learning)**
- Download: https://www.microsoft.com/en-us/sql-server/sql-server-2025
- Install on local Windows 11 machine
- Feature complete, production-ready in H1 2025

**Option 2: Use SQL Server 2022 + pgvector-style Workaround**
```sql
-- Store vectors as VARBINARY or NVARCHAR(JSON)
CREATE TABLE dbo.Jobs (
    ...
    DescriptionVector VARBINARY(MAX),  -- Binary representation
    ...
);

-- Calculate cosine similarity in Python, not T-SQL
-- Less efficient but works with SQL Server 2022
```

**Option 3: Use Azure SQL Database (Preview Features)**
- Azure SQL Database often gets features before on-prem
- Check if VECTOR type available in preview tier

**Recommendation:**
**Go with SQL Server 2025 Preview.** You're on a 2-month timeline—by the time you finish, SQL Server 2025 will be GA (expected Q1-Q2 2025).

---

### ✅ **3. VECTORIZATION (sentence-transformers)**

**Your Design:**
```
sentence-transformers → all-MiniLM-L6-v2 model
Local embedding generation (no API costs)
```

**Assessment: PERFECT CHOICE**

**Why all-MiniLM-L6-v2 is ideal:**
- ✅ 384 dimensions (matches SQL Server VECTOR(384))
- ✅ 23MB model size (fast download/load)
- ✅ Optimized for semantic similarity tasks
- ✅ Fast inference (~0.1s per document on CPU)
- ✅ No API costs (fully local)

**Implementation:**

```python
from sentence_transformers import SentenceTransformer
import numpy as np

# Load model (downloads once, caches locally)
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

# Generate embedding for job description
def generate_embedding(text):
    """
    Generate 384-dimensional vector embedding
    """
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()  # Convert to list for SQL Server

# Example
job_description = """
Principal Database Engineer role managing large-scale Azure SQL deployments.
Requires expertise in Query Store, APRC, performance tuning, and HA/DR solutions.
Experience with AI/ML for database automation is a plus.
"""

vector = generate_embedding(job_description)
print(f"Vector dimensions: {len(vector)}")  # 384
print(f"First 5 values: {vector[:5]}")
```

**Insert into SQL Server:**

```python
import pyodbc
import json

# Connect to SQL Server
conn = pyodbc.connect(
    'DRIVER={ODBC Driver 18 for SQL Server};'
    'SERVER=localhost;'
    'DATABASE=JobSearchRAG;'
    'Trusted_Connection=yes;'
)

cursor = conn.cursor()

# Convert vector to SQL Server VECTOR format
vector_str = f"CAST('{json.dumps(vector)}' AS VECTOR(384))"

# Insert job with vector
query = f"""
INSERT INTO dbo.Jobs (JobTitle, Company, JobDescription, DescriptionVector)
VALUES (?, ?, ?, {vector_str})
"""

cursor.execute(query, (
    "Principal Database Engineer",
    "Atlassian",
    job_description
))

conn.commit()
```

**Performance Optimization:**

```python
# Batch embedding generation (faster for multiple jobs)
job_descriptions = [job1_text, job2_text, job3_text, ...]

# Generate embeddings in batches of 32
embeddings = model.encode(
    job_descriptions,
    batch_size=32,
    show_progress_bar=True,
    convert_to_numpy=True
)

# Bulk insert into SQL Server
for i, (job, embedding) in enumerate(zip(jobs, embeddings)):
    # Insert each job with its embedding
    ...
```

**Expected Performance:**
- **Single job embedding:** ~100ms on CPU
- **Batch (100 jobs):** ~3-4 seconds
- **1,000 jobs/day:** ~40 seconds total embedding time

---

### ✅ **4. AI EVALUATION LAYER (Gemini 2.5 Pro)**

**Your Design:**
```
Top 50 jobs → Gemini 2.5 Pro API → Structured JSON output
Skill gap analysis → Daily CSV report
```

**Assessment: EXCELLENT HYBRID APPROACH**

**Why Gemini 2.5 Pro is the right choice:**
- ✅ 1M token context window (can process all 50 jobs in one call)
- ✅ Native JSON structured output mode
- ✅ Cost-effective ($0.30 per 1M input tokens)
- ✅ Excellent at analytical tasks (skill gap analysis)
- ✅ Google AI Studio provides free tier (60 requests/minute)

**Structured Output Schema:**

```python
from google import genai
from google.genai import types

# Initialize Gemini client
client = genai.Client(api_key="YOUR_GOOGLE_AI_STUDIO_API_KEY")

# Define JSON schema for structured output
response_schema = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema={
        "type": "object",
        "properties": {
            "job_id": {"type": "integer"},
            "fit_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100
            },
            "matching_skills": {
                "type": "array",
                "items": {"type": "string"}
            },
            "missing_skills": {
                "type": "array",
                "items": {"type": "string"}
            },
            "skill_gap_priority": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "skill": {"type": "string"},
                        "importance": {"type": "string", "enum": ["Critical", "High", "Medium", "Low"]},
                        "learning_resources": {"type": "string"}
                    }
                }
            },
            "recommendation": {
                "type": "string",
                "enum": ["Apply Now", "Learn Skills First", "Not a Good Fit"]
            }
        },
        "required": ["job_id", "fit_score", "matching_skills", "missing_skills"]
    }
)

# Prompt template
prompt_template = """
You are an expert career advisor analyzing job fit for a database platform engineer.

CANDIDATE PROFILE:
{master_resume}

JOB POSTING #{job_id}:
Title: {job_title}
Company: {company}
Location: {location}
Salary: {salary}
Description:
{job_description}

SEMANTIC SIMILARITY SCORE: {similarity_score:.2f} (0.00-1.00)

ANALYSIS REQUIRED:
1. Calculate a FIT SCORE (0-100) based on:
   - Semantic similarity score (provided)
   - Exact skill matches
   - Experience level alignment
   - Domain expertise overlap

2. Identify MATCHING SKILLS from candidate profile that align with job requirements

3. Identify MISSING SKILLS required by job but not in candidate profile

4. Prioritize skill gaps by importance with learning resources

5. Provide RECOMMENDATION: "Apply Now", "Learn Skills First", or "Not a Good Fit"

Return ONLY valid JSON matching the schema. No additional text.
"""

# Analyze single job
def analyze_job_fit(job, master_resume):
    prompt = prompt_template.format(
        master_resume=master_resume,
        job_id=job['JobID'],
        job_title=job['JobTitle'],
        company=job['Company'],
        location=job['Location'],
        salary=job['Salary'],
        job_description=job['JobDescription'],
        similarity_score=job['SimilarityScore']
    )

    response = client.models.generate_content(
        model='gemini-2.0-flash-exp',  # Or gemini-2.5-pro when available
        contents=prompt,
        config=response_schema
    )

    return response.json()

# Batch analysis (all 50 jobs in one call)
def batch_analyze_jobs(top_50_jobs, master_resume):
    # Combine all 50 jobs into single prompt
    jobs_text = "\n\n".join([
        f"JOB #{job['JobID']}: {job['JobTitle']} at {job['Company']}\n{job['JobDescription'][:500]}..."
        for job in top_50_jobs
    ])

    batch_prompt = f"""
    Analyze these 50 jobs against the candidate profile.
    Return JSON array with analysis for each job.

    CANDIDATE PROFILE:
    {master_resume}

    JOBS TO ANALYZE:
    {jobs_text}
    """

    # Gemini 2.5 Pro can handle this in one call (1M token context)
    response = client.models.generate_content(
        model='gemini-2.0-flash-exp',
        contents=batch_prompt,
        config=response_schema
    )

    return response.json()
```

**Cost Estimation:**

| Usage | Tokens | Cost/Day | Cost/Month |
|-------|--------|----------|------------|
| **50 jobs/day analysis** | ~50K input + 10K output | $0.02 | $0.60 |
| **Master resume** | 5K tokens | $0.0015 | $0.045 |
| **Total** | ~65K tokens/day | **~$0.022/day** | **~$0.66/month** |

**Extremely cost-effective** (< $1/month for entire 2-month project)

**Daily CSV Report Generation:**

```python
import pandas as pd
from datetime import datetime

# Generate daily report
def generate_daily_report(analysis_results):
    df = pd.DataFrame(analysis_results)

    # Sort by fit score
    df = df.sort_values('fit_score', ascending=False)

    # Add recommendation colors for Excel
    def color_code(score):
        if score >= 80: return "🟢 Apply Now"
        elif score >= 60: return "🟡 Learn Skills First"
        else: return "🔴 Not a Good Fit"

    df['Action'] = df['fit_score'].apply(color_code)

    # Export to CSV
    date_str = datetime.now().strftime('%Y%m%d')
    filename = f"c:/ATS/daily_job_report_{date_str}.csv"
    df.to_csv(filename, index=False)

    print(f"Report saved: {filename}")
    print(f"Total jobs analyzed: {len(df)}")
    print(f"Apply Now (80+): {len(df[df['fit_score'] >= 80])}")
    print(f"Learn First (60-79): {len(df[(df['fit_score'] >= 60) & (df['fit_score'] < 80)])}")
    print(f"Not a Fit (<60): {len(df[df['fit_score'] < 60])}")
```

---

## SYSTEM INFRASTRUCTURE REVIEW

### ✅ **Hardware Requirements**

**Your Spec:**
```
OS: Windows 11 / Windows Server 2025
CPU: 8-core
RAM: 16GB+
```

**Assessment: ADEQUATE**

**Recommendations:**

| Component | Minimum | Recommended | Your Spec | Status |
|-----------|---------|-------------|-----------|--------|
| **CPU** | 4-core | 8-core | 8-core | ✅ Perfect |
| **RAM** | 12GB | 16GB+ | 16GB+ | ✅ Perfect |
| **Storage** | 50GB SSD | 100GB SSD | - | ⚠️ Confirm |
| **OS** | Windows 11 | Windows 11/Server 2025 | ✅ | Good |

**Storage Breakdown:**
- SQL Server 2025: ~10GB
- sentence-transformers models: ~500MB
- Python environment: ~2GB
- Job data (1 year): ~5-10GB
- **Total:** ~20-25GB (50GB SSD minimum)

### ✅ **Software Requirements**

**Install Checklist:**

**1. SQL Server 2025 Preview**
```
Download: https://www.microsoft.com/en-us/sql-server/sql-server-2025
Install: Developer Edition (free)
Features needed: Database Engine, Full-Text Search
```

**2. Python 3.10+ Environment**
```bash
# Create virtual environment
python -m venv c:\ATS\venv

# Activate
c:\ATS\venv\Scripts\activate

# Install dependencies
pip install sentence-transformers
pip install google-generativeai
pip install pyodbc
pip install requests
pip install feedparser
pip install beautifulsoup4
pip install pandas
pip install numpy
```

**3. ODBC Driver 18 for SQL Server**
```
Download: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
Install: ODBC Driver 18 (latest)
```

**4. Google AI Studio API Key**
```
1. Go to: https://aistudio.google.com/
2. Create project
3. Generate API key
4. Free tier: 60 requests/minute
```

**5. JSearch API (RapidAPI)**
```
1. Go to: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
2. Subscribe to Basic plan ($9.99/month)
3. Get API key
4. Test endpoint
```

---

## POTENTIAL CHALLENGES & SOLUTIONS

### ⚠️ **Challenge 1: SQL Server 2025 is Preview**

**Issue:** Not production-ready, potential bugs

**Solutions:**
1. **Use Preview anyway** (recommended for learning)
   - Most features stable
   - GA expected Q1-Q2 2025
   - Perfect timing for 2-month project

2. **Fallback: Azure SQL Database**
   - Vector features often preview there first
   - Cloud-based, always updated
   - Free tier available

3. **Alternative: PostgreSQL + pgvector**
   - Mature vector extension
   - Free, open-source
   - Requires learning PostgreSQL instead of SQL Server

**Recommendation:** Stick with SQL Server 2025 Preview. Risk is low for personal project.

---

### ⚠️ **Challenge 2: JSearch API Rate Limits**

**Issue:** Basic plan = 500 requests/month (~16/day)

**Solutions:**

**Option 1: Optimize API usage**
```python
# Cache results, don't re-fetch same query
import hashlib
import json

def cached_api_call(query, location):
    cache_key = hashlib.md5(f"{query}_{location}".encode()).hexdigest()
    cache_file = f"c:/ATS/cache/{cache_key}.json"

    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            return json.load(f)

    # Make API call
    results = jsearch_api.search(query, location)

    # Cache results
    with open(cache_file, 'w') as f:
        json.dump(results, f)

    return results
```

**Option 2: Supplement with free sources**
- RSS feeds (unlimited)
- Greenhouse/Lever APIs (unlimited)
- Only use JSearch for LinkedIn/Indeed

**Option 3: Upgrade to Pro plan**
- $29.99/month → 2,500 requests (~83/day)
- Worth it for 2-month intensive project

**Recommendation:** Start with Basic plan + free sources. Upgrade to Pro if needed.

---

### ⚠️ **Challenge 3: Embedding Performance**

**Issue:** 1,000 jobs/day = 40 seconds embedding time (acceptable, but can be optimized)

**Solutions:**

**Option 1: GPU acceleration**
```python
# Use GPU if available (CUDA)
model = SentenceTransformer('all-MiniLM-L6-v2', device='cuda')

# 10x faster on GPU (4 seconds for 1,000 jobs)
```

**Option 2: Batch processing**
```python
# Already recommended in architecture
# Process in batches of 100
for i in range(0, len(jobs), 100):
    batch = jobs[i:i+100]
    embeddings = model.encode(batch, batch_size=32)
```

**Option 3: Parallel processing**
```python
from concurrent.futures import ThreadPoolExecutor

def embed_job(job):
    return model.encode(job['description'])

with ThreadPoolExecutor(max_workers=4) as executor:
    embeddings = list(executor.map(embed_job, jobs))
```

**Recommendation:** Batch processing is enough. GPU optional (4x speedup on NVIDIA GPU).

---

### ⚠️ **Challenge 4: Gemini API Rate Limits**

**Issue:** Free tier = 60 requests/minute (plenty for 50 jobs/day)

**Solutions:**

**Current usage:**
- 50 jobs/day in 1 batch call = 1 request
- Well under 60/minute limit

**If you hit limits:**
```python
import time

def rate_limited_gemini_call(prompt, delay=1):
    response = client.generate_content(prompt)
    time.sleep(delay)  # 1 second between calls
    return response

# Or use exponential backoff
from tenacity import retry, wait_exponential, stop_after_attempt

@retry(wait=wait_exponential(min=1, max=60), stop=stop_after_attempt(5))
def resilient_gemini_call(prompt):
    return client.generate_content(prompt)
```

**Recommendation:** Non-issue with current design. Free tier is plenty.

---

## 2-MONTH IMPLEMENTATION ROADMAP

### **Week 1-2: Foundation Setup**

**Week 1: Environment & Database**
- [ ] Day 1-2: Install SQL Server 2025 Preview
- [ ] Day 3: Set up Python 3.10 virtual environment
- [ ] Day 4: Install all dependencies (sentence-transformers, etc.)
- [ ] Day 5: Create database schema (Jobs, MasterResume, JobMatches tables)
- [ ] Day 6-7: Test VECTOR data type, insert sample embeddings

**Week 2: Data Ingestion Pipeline**
- [ ] Day 1-2: Build JSearch API connector
- [ ] Day 3: Build Greenhouse/Lever API connectors
- [ ] Day 4: Build RSS feed parser
- [ ] Day 5: Implement error handling & rate limiting
- [ ] Day 6-7: Test full ingestion pipeline (100 jobs)

**Deliverable:** Working ETL pipeline ingesting jobs into SQL Server

---

### **Week 3-4: Embedding & Vector Search**

**Week 3: Embedding Generation**
- [ ] Day 1-2: Implement sentence-transformers embedding function
- [ ] Day 3: Batch embedding generation for existing jobs
- [ ] Day 4: Create master resume vector
- [ ] Day 5: Test embedding insertion into SQL Server VECTOR column
- [ ] Day 6-7: Optimize batch processing (1,000 jobs test)

**Week 4: Vector Similarity Search**
- [ ] Day 1-2: Write T-SQL vector search queries (VECTOR_DISTANCE)
- [ ] Day 3: Implement top-50 job retrieval logic
- [ ] Day 4: Test similarity ranking accuracy
- [ ] Day 5-7: Tune similarity thresholds, performance optimization

**Deliverable:** Working semantic search retrieving top 50 matched jobs

---

### **Week 5-6: AI Analysis Integration**

**Week 5: Gemini Integration**
- [ ] Day 1: Set up Google AI Studio, get API key
- [ ] Day 2-3: Implement Gemini API calls with structured output
- [ ] Day 4: Build skill gap analysis prompt template
- [ ] Day 5: Test single job analysis
- [ ] Day 6-7: Implement batch analysis (50 jobs)

**Week 6: Report Generation**
- [ ] Day 1-2: Build CSV report generator
- [ ] Day 3: Add skill gap prioritization logic
- [ ] Day 4: Implement learning resource recommendations
- [ ] Day 5-7: Test end-to-end pipeline (ingest → embed → search → analyze → report)

**Deliverable:** Daily CSV reports with fit scores and skill gaps

---

### **Week 7-8: Automation & Refinement**

**Week 7: Automation**
- [ ] Day 1-2: Create Windows Task Scheduler job (daily run)
- [ ] Day 3: Implement logging and monitoring
- [ ] Day 4: Build email notifications (optional)
- [ ] Day 5-7: Error recovery and retry logic

**Week 8: Testing & Optimization**
- [ ] Day 1-3: Run pipeline for 7 consecutive days
- [ ] Day 4: Analyze results, tune similarity thresholds
- [ ] Day 5: Optimize SQL queries (indexing, performance)
- [ ] Day 6-7: Documentation and final testing

**Deliverable:** Fully automated system running daily

---

## PROJECT STRUCTURE

```
c:\ATS\
│
├── config/
│   ├── config.yaml               # API keys, database connection strings
│   └── logging_config.yaml
│
├── data/
│   ├── raw/                      # Raw job JSON from APIs
│   ├── processed/                # Cleaned job data
│   ├── embeddings/               # Cached embeddings
│   └── reports/                  # Daily CSV reports
│       └── daily_job_report_YYYYMMDD.csv
│
├── database/
│   ├── schema.sql                # Database schema DDL
│   ├── stored_procedures.sql    # T-SQL stored procedures
│   └── migrations/               # Schema version control
│
├── src/
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── jsearch_connector.py
│   │   ├── greenhouse_connector.py
│   │   ├── lever_connector.py
│   │   └── rss_parser.py
│   │
│   ├── embedding/
│   │   ├── __init__.py
│   │   ├── vector_generator.py   # sentence-transformers logic
│   │   └── batch_processor.py
│   │
│   ├── search/
│   │   ├── __init__.py
│   │   └── semantic_search.py    # SQL Server vector queries
│   │
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── gemini_client.py
│   │   └── skill_gap_analyzer.py
│   │
│   ├── reporting/
│   │   ├── __init__.py
│   │   └── csv_generator.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── database.py           # SQL Server connection pool
│       ├── logging_utils.py
│       └── config_loader.py
│
├── tests/
│   ├── test_ingestion.py
│   ├── test_embedding.py
│   ├── test_search.py
│   └── test_analysis.py
│
├── scripts/
│   ├── run_daily_pipeline.py     # Main orchestration script
│   ├── setup_database.py         # One-time DB setup
│   └── update_master_resume.py   # Update resume vector
│
├── requirements.txt              # Python dependencies
├── README.md
└── .env                          # API keys (gitignored)
```

---

## ESTIMATED COSTS (2-MONTH PROJECT)

| Item | Cost |
|------|------|
| **SQL Server 2025 Preview** | Free (Developer Edition) |
| **Python & Libraries** | Free (open source) |
| **sentence-transformers model** | Free (open source) |
| **JSearch API** | $9.99/month × 2 = $19.98 |
| **Gemini 2.5 Pro API** | ~$1.32 (2 months @ $0.66/month) |
| **ODBC Driver** | Free |
| **Windows 11 License** | $0 (assuming owned) |
| **Hardware** | $0 (assuming owned) |
| **TOTAL** | **~$21.30 for entire 2-month project** |

**Extremely cost-effective for the value delivered.**

---

## SUCCESS METRICS

### **Technical Metrics:**
- ✅ 1,000+ jobs ingested daily
- ✅ Embedding generation: <1 minute for 1,000 jobs
- ✅ Vector search: <2 seconds for top 50 results
- ✅ LLM analysis: <30 seconds for 50 jobs
- ✅ End-to-end pipeline: <5 minutes daily
- ✅ 99% uptime (automated daily runs)

### **Business Metrics:**
- ✅ 10-20 high-fit jobs (80+ score) identified per week
- ✅ Clear skill gap priorities for upskilling
- ✅ Reduced manual job search time: 2 hours/day → 10 minutes/day
- ✅ Improved application quality (targeting best-fit roles)
- ✅ Measurable skill development roadmap

### **Learning Metrics:**
- ✅ Hands-on Python ETL experience
- ✅ SQL Server 2025 vector DB expertise
- ✅ RAG architecture implementation
- ✅ LLM integration (Gemini API)
- ✅ Production data pipeline development

---

## RISK MITIGATION

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| SQL Server 2025 bugs | High | Medium | Fallback to Azure SQL Database |
| JSearch API rate limits | Medium | Low | Supplement with free sources |
| Gemini API downtime | Medium | Low | Queue jobs, retry with backoff |
| Embedding model changes | Low | Low | Pin specific model version |
| Job data quality issues | Medium | Medium | Data validation pipeline |
| Insufficient hardware | Low | Low | Cloud VM fallback (Azure/AWS) |

---

## NEXT STEPS (START TODAY)

### **Immediate Actions (This Week):**

1. **Day 1: SQL Server Setup**
   ```
   - Download SQL Server 2025 Preview
   - Install Developer Edition
   - Verify VECTOR data type support
   ```

2. **Day 2: Python Environment**
   ```bash
   python -m venv c:\ATS\venv
   c:\ATS\venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Day 3: API Keys**
   ```
   - Sign up for Google AI Studio (Gemini API)
   - Subscribe to JSearch API (RapidAPI Basic plan)
   - Test both APIs
   ```

4. **Day 4: Database Schema**
   ```sql
   -- Create database
   CREATE DATABASE JobSearchRAG;

   -- Create tables (Jobs, MasterResume, JobMatches)
   -- Test VECTOR(384) data type
   ```

5. **Day 5: First Embedding**
   ```python
   # Test sentence-transformers
   from sentence_transformers import SentenceTransformer
   model = SentenceTransformer('all-MiniLM-L6-v2')
   vector = model.encode("Principal Database Engineer")
   print(len(vector))  # Should be 384
   ```

---

## FINAL ASSESSMENT

### **Architecture Score: 9.5/10**

**Strengths:**
- ✅ Cutting-edge (SQL Server 2025 vectors)
- ✅ Cost-effective (<$25 for 2 months)
- ✅ Local-first (privacy, control)
- ✅ Hybrid approach (local embedding + cloud LLM)
- ✅ Clear business value (automated job search)
- ✅ Excellent learning project (Python, RAG, SQL, LLMs)
- ✅ Realistic timeline (2 months)

**Minor Improvements:**
- Consider PostgreSQL + pgvector as SQL Server 2025 fallback
- Add monitoring/alerting for pipeline failures
- Implement A/B testing for prompt variations

**Overall: This is an exceptionally well-designed system. Execute it exactly as planned.**

---

## QUESTIONS TO CLARIFY

Before you start implementation:

1. **SQL Server 2025 Preview**: Are you comfortable using preview software, or prefer fallback to Azure SQL Database?

2. **Hardware**: Do you have the 8-core CPU + 16GB RAM machine ready, or need cloud VM recommendations?

3. **Candidate facts**: Which private resume or fact source will be imported at runtime? Candidate documents are intentionally stored outside this repository.

4. **Target Roles**: Are you focusing on "Principal Database Engineer" + "Staff Database Engineer" + "Azure SQL Architect" only, or broader?

5. **Geographic Focus**: Should we prioritize Australia (from earlier salary research), or global search?

6. **Timeline**: Confirm you have 10-15 hours/week for 2 months (realistic for working professional)?

---

**Your architecture is production-ready. Let's build this!** 🚀

Ready to start with Week 1 setup?

