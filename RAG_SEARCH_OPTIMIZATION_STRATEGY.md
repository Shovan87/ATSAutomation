# RAG SEARCH OPTIMIZATION - 250 API CALLS/MONTH STRATEGY

## PROBLEM STATEMENT

**SerpAPI Free Tier Limit**: 250 searches/month
**Desired Execution**: Daily pipeline runs (30 days/month)
**Available Budget**: 250 ÷ 30 = **8.3 searches per day**

**Goal**: Maximize job coverage while staying within API limits using intelligent search rotation and deduplication.

---

## SOLUTION ARCHITECTURE

### Strategy Overview

```
┌─────────────────────────────────────────────────────────────┐
│ DAILY EXECUTION LOGIC                                       │
├─────────────────────────────────────────────────────────────┤
│ 1. Check API usage counter (must be < 250 for month)       │
│ 2. Execute 8 searches using ROTATION STRATEGY               │
│ 3. Deduplicate jobs (skip if already in database)          │
│ 4. Store only NEW jobs in SQL Server                       │
│ 5. Update API usage counter                                │
│ 6. Reset counter on 1st of each month                      │
└─────────────────────────────────────────────────────────────┘
```

---

## DATABASE SCHEMA UPDATES

### 1. API Usage Tracking Table

```sql
CREATE TABLE dbo.APIUsageTracking (
    UsageID INT IDENTITY(1,1) PRIMARY KEY,
    APIProvider NVARCHAR(50) NOT NULL,  -- 'SerpAPI', 'JSearch', etc.
    SearchDate DATE NOT NULL,
    SearchQuery NVARCHAR(500) NOT NULL,
    ResultsReturned INT DEFAULT 0,
    NewJobsAdded INT DEFAULT 0,
    APICallTimestamp DATETIME2 DEFAULT GETDATE(),
    MonthYear AS FORMAT(SearchDate, 'yyyy-MM') PERSISTED,  -- For monthly grouping
    CONSTRAINT UQ_APICall UNIQUE (APIProvider, SearchDate, SearchQuery)
);

-- Index for monthly usage queries
CREATE INDEX IX_APIUsage_MonthYear ON dbo.APIUsageTracking(APIProvider, MonthYear);
```

### 2. Search Rotation Schedule Table

```sql
CREATE TABLE dbo.SearchRotationSchedule (
    ScheduleID INT IDENTITY(1,1) PRIMARY KEY,
    DayOfMonth INT NOT NULL CHECK (DayOfMonth BETWEEN 1 AND 31),
    SearchQuery NVARCHAR(500) NOT NULL,
    TargetLocation NVARCHAR(100) NOT NULL,  -- 'Australia', 'Remote', 'Sydney', etc.
    Priority INT DEFAULT 1,  -- 1=High, 2=Medium, 3=Low
    IsActive BIT DEFAULT 1,
    CONSTRAINT UQ_DayQuery UNIQUE (DayOfMonth, SearchQuery, TargetLocation)
);
```

### 3. Job Deduplication Table (Update existing Jobs table)

```sql
-- Add columns to existing dbo.Jobs table
ALTER TABLE dbo.Jobs ADD JobHash AS CAST(HASHBYTES('SHA2_256',
    CONCAT(JobTitle, Company, CAST(DatePosted AS NVARCHAR(50)))) AS NVARCHAR(64)) PERSISTED;

-- Unique constraint to prevent duplicate jobs
CREATE UNIQUE INDEX UQ_Jobs_Hash ON dbo.Jobs(JobHash);
```

---

## SEARCH ROTATION STRATEGY

### Monthly Search Plan (250 searches ÷ 30 days = 8/day)

**Priority 1 Searches** (Run more frequently):
- Principal Database Engineer
- Staff Database Engineer
- Senior Database Platform Engineer
- Azure SQL Architect

**Priority 2 Searches** (Moderate frequency):
- Database Reliability Engineer
- Data Platform Engineer
- Cloud Database Engineer
- Database DevOps Engineer

**Priority 3 Searches** (Lower frequency):
- Lead Database Engineer
- Database Infrastructure Engineer
- SQL Server Architect
- Data Infrastructure Architect

### Rotation Schedule (8 searches/day)

**Week 1** (Days 1-7):
```
Day 1:  Principal Database Engineer + Australia (4 locations) = 4 searches
        Staff Database Engineer + Remote = 2 searches
        Azure SQL Architect + Sydney = 1 search
        Database Reliability Engineer + Remote = 1 search
        TOTAL: 8 searches

Day 2:  Principal Database Engineer + Remote = 2 searches
        Senior Database Platform Engineer + Australia (3 locations) = 3 searches
        Cloud Database Engineer + Sydney = 1 search
        Database DevOps Engineer + Remote = 1 search
        Database Infrastructure Engineer + Melbourne = 1 search
        TOTAL: 8 searches

Day 3:  Staff Database Engineer + Australia (4 locations) = 4 searches
        Azure SQL Architect + Remote = 2 searches
        Data Platform Engineer + Sydney = 1 search
        SQL Server Architect + Remote = 1 search
        TOTAL: 8 searches

Day 4:  Principal Database Engineer + Sydney,Melbourne = 2 searches
        Database Reliability Engineer + Australia = 2 searches
        Senior Database Platform Engineer + Remote = 2 searches
        Cloud Database Engineer + Australia = 2 searches
        TOTAL: 8 searches

Day 5:  Staff Database Engineer + Remote = 2 searches
        Azure SQL Architect + Australia (3 locations) = 3 searches
        Database DevOps Engineer + Sydney = 1 search
        Data Infrastructure Architect + Remote = 1 search
        Lead Database Engineer + Sydney = 1 search
        TOTAL: 8 searches

Day 6:  Principal Database Engineer + Remote,Brisbane = 2 searches
        Senior Database Platform Engineer + Sydney,Melbourne = 2 searches
        Database Reliability Engineer + Remote = 2 searches
        Data Platform Engineer + Australia = 2 searches
        TOTAL: 8 searches

Day 7:  Staff Database Engineer + Sydney,Melbourne,Brisbane = 3 searches
        Azure SQL Architect + Remote = 2 searches
        Cloud Database Engineer + Remote = 2 searches
        Database Infrastructure Engineer + Sydney = 1 search
        TOTAL: 8 searches
```

**Week 2-4**: Repeat with variations (alternate locations, add new search terms)

**Optimization**: Skip weekends if job posting volume is low
- Run 10 searches/day on weekdays (Mon-Fri = 22 days)
- 10 × 22 = 220 searches (leaves 30 buffer for ad-hoc searches)

---

## PYTHON IMPLEMENTATION

### 1. API Usage Counter Function

```python
import pyodbc
from datetime import datetime, date

def get_monthly_api_usage(api_provider='SerpAPI'):
    """
    Get current month's API usage count

    Returns:
        dict: {
            'total_calls': int,
            'remaining': int,
            'month_year': str,
            'can_execute': bool
        }
    """
    conn = pyodbc.connect(CONNECTION_STRING)
    cursor = conn.cursor()

    current_month = datetime.now().strftime('%Y-%m')

    query = """
    SELECT COUNT(*) AS TotalCalls
    FROM dbo.APIUsageTracking
    WHERE APIProvider = ? AND MonthYear = ?
    """

    cursor.execute(query, (api_provider, current_month))
    result = cursor.fetchone()
    total_calls = result[0] if result else 0

    conn.close()

    return {
        'total_calls': total_calls,
        'remaining': 250 - total_calls,
        'month_year': current_month,
        'can_execute': total_calls < 250
    }

def log_api_call(api_provider, search_query, results_returned, new_jobs_added):
    """Log API call to tracking table"""
    conn = pyodbc.connect(CONNECTION_STRING)
    cursor = conn.cursor()

    query = """
    INSERT INTO dbo.APIUsageTracking
    (APIProvider, SearchDate, SearchQuery, ResultsReturned, NewJobsAdded)
    VALUES (?, CAST(GETDATE() AS DATE), ?, ?, ?)
    """

    try:
        cursor.execute(query, (api_provider, search_query, results_returned, new_jobs_added))
        conn.commit()
    except pyodbc.IntegrityError:
        # Duplicate search today - skip
        print(f"SKIP: Already searched '{search_query}' today")
    finally:
        conn.close()
```

### 2. Smart Search Rotation Function

```python
def get_todays_search_queries():
    """
    Get optimized search queries for today based on rotation schedule

    Returns:
        list: [
            {'query': 'Principal Database Engineer', 'location': 'Sydney, Australia'},
            {'query': 'Staff Database Engineer', 'location': 'Remote'},
            ...
        ]
    """
    conn = pyodbc.connect(CONNECTION_STRING)
    cursor = conn.cursor()

    day_of_month = datetime.now().day

    query = """
    SELECT TOP 8 SearchQuery, TargetLocation, Priority
    FROM dbo.SearchRotationSchedule
    WHERE DayOfMonth = ? AND IsActive = 1
    ORDER BY Priority ASC, ScheduleID ASC
    """

    cursor.execute(query, (day_of_month,))
    results = cursor.fetchall()

    conn.close()

    if not results:
        # Fallback to default high-priority searches
        return [
            {'query': 'Principal Database Engineer', 'location': 'Australia'},
            {'query': 'Staff Database Engineer', 'location': 'Australia'},
            {'query': 'Azure SQL Architect', 'location': 'Remote'},
            {'query': 'Database Reliability Engineer', 'location': 'Sydney, Australia'},
            {'query': 'Senior Database Platform Engineer', 'location': 'Melbourne, Australia'},
            {'query': 'Cloud Database Engineer', 'location': 'Remote'},
            {'query': 'Data Platform Engineer', 'location': 'Australia'},
            {'query': 'Database DevOps Engineer', 'location': 'Remote'}
        ]

    return [
        {'query': row[0], 'location': row[1], 'priority': row[2]}
        for row in results
    ]
```

### 3. Deduplication Function

```python
import hashlib

def generate_job_hash(job_title, company, date_posted):
    """
    Generate SHA-256 hash for job deduplication

    Args:
        job_title (str): Job title
        company (str): Company name
        date_posted (str): Date posted (YYYY-MM-DD format)

    Returns:
        str: 64-character hex hash
    """
    hash_input = f"{job_title}{company}{date_posted}".encode('utf-8')
    return hashlib.sha256(hash_input).hexdigest()

def is_duplicate_job(job_hash):
    """
    Check if job already exists in database

    Returns:
        bool: True if duplicate, False if new
    """
    conn = pyodbc.connect(CONNECTION_STRING)
    cursor = conn.cursor()

    query = "SELECT COUNT(*) FROM dbo.Jobs WHERE JobHash = ?"
    cursor.execute(query, (job_hash,))

    count = cursor.fetchone()[0]
    conn.close()

    return count > 0

def insert_job_if_new(job_data):
    """
    Insert job only if it doesn't already exist

    Args:
        job_data (dict): Job information

    Returns:
        bool: True if inserted, False if duplicate
    """
    job_hash = generate_job_hash(
        job_data['job_title'],
        job_data['company'],
        job_data['date_posted']
    )

    if is_duplicate_job(job_hash):
        print(f"SKIP: Duplicate job - {job_data['job_title']} at {job_data['company']}")
        return False

    # Insert new job
    conn = pyodbc.connect(CONNECTION_STRING)
    cursor = conn.cursor()

    query = """
    INSERT INTO dbo.Jobs
    (JobTitle, Company, JobDescription, DatePosted, Location, JobURL, Source)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """

    cursor.execute(query, (
        job_data['job_title'],
        job_data['company'],
        job_data['description'],
        job_data['date_posted'],
        job_data['location'],
        job_data['url'],
        'SerpAPI'
    ))

    conn.commit()
    conn.close()

    print(f"NEW JOB: {job_data['job_title']} at {job_data['company']}")
    return True
```

### 4. Main Daily Pipeline (Rate-Limited)

```python
from serpapi import GoogleSearch
import time

def run_daily_job_search():
    """
    Main pipeline - executes daily with API rate limiting
    """
    print("=" * 60)
    print(f"RAG JOB SEARCH PIPELINE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Step 1: Check API usage
    usage = get_monthly_api_usage('SerpAPI')
    print(f"\nAPI Usage: {usage['total_calls']}/250 ({usage['remaining']} remaining)")

    if not usage['can_execute']:
        print("ERROR: Monthly API limit reached (250/250). Skipping execution.")
        return

    # Step 2: Get today's search queries
    search_queries = get_todays_search_queries()
    print(f"\nPlanned Searches: {len(search_queries)}")

    # Step 3: Execute searches with rate limiting
    total_results = 0
    total_new_jobs = 0

    for idx, search in enumerate(search_queries, 1):
        # Check if we still have API calls remaining
        current_usage = get_monthly_api_usage('SerpAPI')
        if current_usage['total_calls'] >= 250:
            print(f"\nAPI limit reached mid-execution. Stopping at search {idx}/{len(search_queries)}")
            break

        print(f"\n[{idx}/{len(search_queries)}] Searching: {search['query']} in {search['location']}")

        try:
            # SerpAPI search
            params = {
                "engine": "google_jobs",
                "q": search['query'],
                "location": search['location'],
                "api_key": SERPAPI_KEY,
                "num": 10  # Get top 10 results per search
            }

            search_result = GoogleSearch(params)
            results = search_result.get_dict()

            jobs_list = results.get("jobs_results", [])
            results_count = len(jobs_list)
            new_jobs_count = 0

            print(f"  Found: {results_count} jobs")

            # Step 4: Deduplicate and insert new jobs
            for job in jobs_list:
                job_data = {
                    'job_title': job.get('title', 'N/A'),
                    'company': job.get('company_name', 'N/A'),
                    'description': job.get('description', 'N/A'),
                    'date_posted': job.get('detected_extensions', {}).get('posted_at', datetime.now().strftime('%Y-%m-%d')),
                    'location': job.get('location', search['location']),
                    'url': job.get('share_url', 'N/A')
                }

                if insert_job_if_new(job_data):
                    new_jobs_count += 1

            total_results += results_count
            total_new_jobs += new_jobs_count

            # Step 5: Log API call
            log_api_call('SerpAPI', f"{search['query']} | {search['location']}",
                        results_count, new_jobs_count)

            print(f"  New Jobs: {new_jobs_count}/{results_count}")

            # Rate limiting: Wait 2 seconds between API calls
            if idx < len(search_queries):
                time.sleep(2)

        except Exception as e:
            print(f"  ERROR: {str(e)}")
            continue

    # Step 6: Summary
    print("\n" + "=" * 60)
    print("EXECUTION SUMMARY")
    print("=" * 60)
    print(f"Searches Executed: {idx}/{len(search_queries)}")
    print(f"Total Results: {total_results}")
    print(f"New Jobs Added: {total_new_jobs}")
    print(f"Duplicates Skipped: {total_results - total_new_jobs}")

    updated_usage = get_monthly_api_usage('SerpAPI')
    print(f"\nAPI Usage: {updated_usage['total_calls']}/250 ({updated_usage['remaining']} remaining)")
    print(f"Estimated Days Remaining: {updated_usage['remaining'] // 8}")
    print("=" * 60)

if __name__ == "__main__":
    run_daily_job_search()
```

---

## SEARCH ROTATION SCHEDULE (SQL INSERT SCRIPT)

```sql
-- Populate rotation schedule for 30-day cycle
-- 8 searches per day, rotating through high-priority queries

TRUNCATE TABLE dbo.SearchRotationSchedule;

-- Week 1 (Days 1-7)
INSERT INTO dbo.SearchRotationSchedule (DayOfMonth, SearchQuery, TargetLocation, Priority) VALUES
-- Day 1
(1, 'Principal Database Engineer', 'Sydney, Australia', 1),
(1, 'Principal Database Engineer', 'Melbourne, Australia', 1),
(1, 'Principal Database Engineer', 'Brisbane, Australia', 1),
(1, 'Principal Database Engineer', 'Remote', 1),
(1, 'Staff Database Engineer', 'Remote', 1),
(1, 'Azure SQL Architect', 'Sydney, Australia', 1),
(1, 'Database Reliability Engineer', 'Remote', 2),
(1, 'Senior Database Platform Engineer', 'Australia', 1),

-- Day 2
(2, 'Principal Database Engineer', 'Remote', 1),
(2, 'Senior Database Platform Engineer', 'Sydney, Australia', 1),
(2, 'Senior Database Platform Engineer', 'Melbourne, Australia', 1),
(2, 'Senior Database Platform Engineer', 'Brisbane, Australia', 1),
(2, 'Cloud Database Engineer', 'Sydney, Australia', 2),
(2, 'Database DevOps Engineer', 'Remote', 2),
(2, 'Database Infrastructure Engineer', 'Melbourne, Australia', 2),
(2, 'Staff Database Engineer', 'Australia', 1),

-- Day 3
(3, 'Staff Database Engineer', 'Sydney, Australia', 1),
(3, 'Staff Database Engineer', 'Melbourne, Australia', 1),
(3, 'Staff Database Engineer', 'Brisbane, Australia', 1),
(3, 'Staff Database Engineer', 'Remote', 1),
(3, 'Azure SQL Architect', 'Remote', 1),
(3, 'Azure SQL Architect', 'Australia', 1),
(3, 'Data Platform Engineer', 'Sydney, Australia', 2),
(3, 'SQL Server Architect', 'Remote', 2),

-- Day 4
(4, 'Principal Database Engineer', 'Sydney, Australia', 1),
(4, 'Principal Database Engineer', 'Melbourne, Australia', 1),
(4, 'Database Reliability Engineer', 'Australia', 2),
(4, 'Database Reliability Engineer', 'Remote', 2),
(4, 'Senior Database Platform Engineer', 'Remote', 1),
(4, 'Senior Database Platform Engineer', 'Australia', 1),
(4, 'Cloud Database Engineer', 'Australia', 2),
(4, 'Cloud Database Engineer', 'Remote', 2),

-- Day 5
(5, 'Staff Database Engineer', 'Remote', 1),
(5, 'Staff Database Engineer', 'Australia', 1),
(5, 'Azure SQL Architect', 'Sydney, Australia', 1),
(5, 'Azure SQL Architect', 'Melbourne, Australia', 1),
(5, 'Azure SQL Architect', 'Brisbane, Australia', 1),
(5, 'Database DevOps Engineer', 'Sydney, Australia', 2),
(5, 'Data Infrastructure Architect', 'Remote', 2),
(5, 'Lead Database Engineer', 'Sydney, Australia', 3),

-- Day 6
(6, 'Principal Database Engineer', 'Remote', 1),
(6, 'Principal Database Engineer', 'Brisbane, Australia', 1),
(6, 'Senior Database Platform Engineer', 'Sydney, Australia', 1),
(6, 'Senior Database Platform Engineer', 'Melbourne, Australia', 1),
(6, 'Database Reliability Engineer', 'Remote', 2),
(6, 'Database Reliability Engineer', 'Sydney, Australia', 2),
(6, 'Data Platform Engineer', 'Australia', 2),
(6, 'Data Platform Engineer', 'Remote', 2),

-- Day 7
(7, 'Staff Database Engineer', 'Sydney, Australia', 1),
(7, 'Staff Database Engineer', 'Melbourne, Australia', 1),
(7, 'Staff Database Engineer', 'Brisbane, Australia', 1),
(7, 'Azure SQL Architect', 'Remote', 1),
(7, 'Azure SQL Architect', 'Australia', 1),
(7, 'Cloud Database Engineer', 'Remote', 2),
(7, 'Cloud Database Engineer', 'Sydney, Australia', 2),
(7, 'Database Infrastructure Engineer', 'Sydney, Australia', 2);

-- Days 8-14 (repeat with variations)
INSERT INTO dbo.SearchRotationSchedule (DayOfMonth, SearchQuery, TargetLocation, Priority) VALUES
(8, 'Principal Database Engineer', 'Australia', 1),
(8, 'Principal Database Engineer', 'Remote', 1),
(8, 'Database Platform Lead', 'Sydney, Australia', 2),
(8, 'Staff Database Engineer', 'Melbourne, Australia', 1),
(8, 'Azure SQL Architect', 'Remote', 1),
(8, 'Database Reliability Engineer', 'Australia', 2),
(8, 'Senior Database Engineer', 'Sydney, Australia', 2),
(8, 'Cloud Database Architect', 'Remote', 2);

-- Continue pattern for days 9-30...
-- (Add remaining days following same rotation logic)
```

---

## OPTIMIZATION STRATEGIES

### 1. Weekend Skip Strategy

**Observation**: Job postings are 60% lower on weekends

**Solution**: Run Monday-Friday only
```python
def should_run_today():
    """Skip weekends to save API calls"""
    today = datetime.now().weekday()  # 0=Monday, 6=Sunday

    if today >= 5:  # Saturday or Sunday
        print("SKIP: Weekend - low job posting volume")
        return False

    return True

# In main pipeline
if not should_run_today():
    exit(0)
```

**Benefit**:
- 22 weekdays/month × 11 searches/day = 242 searches (within 250 limit)
- 37% more searches per execution day

---

### 2. Adaptive Search Strategy

**Adjust searches based on results quality**

```python
def get_search_performance():
    """Analyze which searches yield most new jobs"""
    conn = pyodbc.connect(CONNECTION_STRING)
    cursor = conn.cursor()

    query = """
    SELECT
        SearchQuery,
        AVG(CAST(NewJobsAdded AS FLOAT) / NULLIF(ResultsReturned, 0)) AS AvgNewJobRate,
        SUM(NewJobsAdded) AS TotalNewJobs,
        COUNT(*) AS TimesSearched
    FROM dbo.APIUsageTracking
    WHERE MonthYear = FORMAT(GETDATE(), 'yyyy-MM')
    GROUP BY SearchQuery
    ORDER BY AvgNewJobRate DESC
    """

    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()

    return results

# Adjust rotation schedule mid-month based on performance
# Prioritize high-performing searches, reduce low-performing ones
```

---

### 3. Smart Location Targeting

**Focus on cities with highest job volume**

```sql
-- Track which locations yield most results
SELECT
    TargetLocation,
    SUM(NewJobsAdded) AS TotalNewJobs,
    AVG(CAST(NewJobsAdded AS FLOAT)) AS AvgNewJobsPerSearch
FROM dbo.APIUsageTracking
WHERE MonthYear = FORMAT(GETDATE(), 'yyyy-MM')
GROUP BY TargetLocation
ORDER BY TotalNewJobs DESC;
```

**Adjust rotation**:
- If Sydney yields 2× more jobs than Brisbane, allocate more searches to Sydney
- If "Remote" has 50% duplicate rate, reduce remote searches

---

## MONITORING DASHBOARD (SQL QUERIES)

### Daily Usage Report

```sql
-- Check today's API usage
SELECT
    CAST(APICallTimestamp AS DATE) AS SearchDate,
    COUNT(*) AS TotalSearches,
    SUM(ResultsReturned) AS TotalResults,
    SUM(NewJobsAdded) AS NewJobs,
    SUM(ResultsReturned - NewJobsAdded) AS Duplicates
FROM dbo.APIUsageTracking
WHERE APIProvider = 'SerpAPI'
  AND CAST(APICallTimestamp AS DATE) = CAST(GETDATE() AS DATE)
GROUP BY CAST(APICallTimestamp AS DATE);
```

### Monthly Projection

```sql
-- Project if we'll exceed 250 limit
DECLARE @DaysElapsed INT = DAY(GETDATE());
DECLARE @CurrentUsage INT = (
    SELECT COUNT(*)
    FROM dbo.APIUsageTracking
    WHERE MonthYear = FORMAT(GETDATE(), 'yyyy-MM')
);
DECLARE @DailyAvg FLOAT = CAST(@CurrentUsage AS FLOAT) / @DaysElapsed;
DECLARE @ProjectedTotal INT = CEILING(@DailyAvg * 30);

SELECT
    @CurrentUsage AS CurrentUsage,
    250 - @CurrentUsage AS Remaining,
    @DailyAvg AS DailyAverage,
    @ProjectedTotal AS ProjectedMonthlyTotal,
    CASE
        WHEN @ProjectedTotal > 250 THEN 'WARNING: Reduce daily searches'
        WHEN @ProjectedTotal BETWEEN 230 AND 250 THEN 'OK: On track'
        ELSE 'GOOD: Under budget'
    END AS Status;
```

### Top Performing Searches

```sql
-- Identify best ROI searches
SELECT TOP 10
    SearchQuery,
    TargetLocation,
    COUNT(*) AS TimesRun,
    SUM(NewJobsAdded) AS TotalNewJobs,
    AVG(CAST(NewJobsAdded AS FLOAT)) AS AvgNewJobsPerSearch,
    SUM(ResultsReturned - NewJobsAdded) AS TotalDuplicates
FROM dbo.APIUsageTracking
WHERE MonthYear = FORMAT(GETDATE(), 'yyyy-MM')
GROUP BY SearchQuery, TargetLocation
ORDER BY AvgNewJobsPerSearch DESC;
```

---

## IMPLEMENTATION CHECKLIST

### Phase 1: Database Setup (Day 1)
- [ ] Run `CREATE TABLE dbo.APIUsageTracking` script
- [ ] Run `CREATE TABLE dbo.SearchRotationSchedule` script
- [ ] Run `ALTER TABLE dbo.Jobs` to add JobHash column
- [ ] Run `INSERT INTO dbo.SearchRotationSchedule` rotation data

### Phase 2: Python Functions (Day 1-2)
- [ ] Implement `get_monthly_api_usage()`
- [ ] Implement `log_api_call()`
- [ ] Implement `get_todays_search_queries()`
- [ ] Implement `generate_job_hash()` and `is_duplicate_job()`
- [ ] Implement `insert_job_if_new()`

### Phase 3: Main Pipeline (Day 2-3)
- [ ] Implement `run_daily_job_search()` with rate limiting
- [ ] Add weekend skip logic
- [ ] Test with 3-5 manual searches
- [ ] Verify deduplication works correctly

### Phase 4: Scheduling (Day 3)
- [ ] Set up Windows Task Scheduler (daily 9 AM)
- [ ] Configure email alerts for API limit warnings
- [ ] Create monitoring dashboard (SQL queries above)

### Phase 5: Monitoring (Ongoing)
- [ ] Check daily usage report every Monday
- [ ] Review monthly projection on 15th of each month
- [ ] Adjust rotation schedule based on performance data

---

## COST COMPARISON

### Original Plan (No Rate Limiting)
- 30 days × unlimited searches = Paid API tier required
- SerpAPI Paid: $50/month for 5,000 searches

### Optimized Plan (250/month limit)
- 30 days × 8 searches/day = 240 searches
- SerpAPI Free: $0/month
- **Savings: $50/month = $600/year**

---

## FALLBACK STRATEGY

**If API limit reached mid-month**:

1. **Switch to JSearch API** (RapidAPI - $9.99/month for 1,000 searches)
2. **Manual scraping** (BeautifulSoup + Selenium for company career pages)
3. **RSS feeds** (free, no API limits)
4. **Greenhouse/Lever APIs** (free for public job boards)

**Cost**: $0-$10/month (vs $50/month for unlimited SerpAPI)

---

## EXPECTED OUTCOMES

**Job Coverage**:
- 240 searches/month × 10 results/search = 2,400 job listings
- Estimated 30% duplicates = 1,680 unique jobs/month
- Estimated 40% relevant (Principal/Staff level) = **672 quality matches/month**

**ROI**:
- Free API tier = $0 cost
- 672 relevant jobs/month = **22 relevant jobs/day**
- More than sufficient for daily application targets (3-5 jobs/day)

---

**END OF OPTIMIZATION STRATEGY**


