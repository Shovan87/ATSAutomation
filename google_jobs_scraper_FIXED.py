"""
Google Jobs Scraper - FIXED VERSION
Based on debugging analysis - uses strategies that actually work with Google Jobs API
Hybrid approach: 2 queries × 10 locations = 20 searches
"""

import csv
from datetime import datetime
from pathlib import Path
from serpapi import GoogleSearch
import time
import os

# SerpAPI Configuration
API_KEY = os.environ["SERPAPI_API_KEY"]
DATA_DIR = Path(os.environ.get("ATS_DATA_DIR", Path(__file__).resolve().parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# FIXED: Simple queries that work (tested and verified)
WORKING_QUERIES = [
    "SQL Server DBA",
    "Azure SQL Database Administrator"
]

# FIXED: Individual locations (OR operators don't work in location field)
PRIORITY_LOCATIONS = [
    "Dubai, UAE",
    "Abu Dhabi, UAE",
    "Singapore",
    "Bangalore, India",
    "Sydney, Australia",
    "London, United Kingdom",
    "Amsterdam, Netherlands",
    "Riyadh, Saudi Arabia",
    "Kuala Lumpur, Malaysia",
    "Zurich, Switzerland"
]

# Output file
OUTPUT_FILE = DATA_DIR / "jobs_global_sql_server_dba.csv"
PROGRESS_FILE = DATA_DIR / "search_progress_fixed.txt"

# Track search credits
search_count = 0
total_jobs_found = 0

def log_progress(message):
    """Log progress to file"""
    with open(PROGRESS_FILE, 'a', encoding='utf-8') as f:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        f.write(f"[{timestamp}] {message}\n")

def is_sql_server_job(job):
    """
    Filter to keep only SQL Server/Azure SQL jobs
    Post-processing filter since exclusion in query doesn't work
    """
    title = job.get('title', '').lower()
    description = job.get('description', '').lower()

    # Must have SQL Server keywords
    sql_server_keywords = ['sql server', 'mssql', 'azure sql', 't-sql', 'tsql', 'microsoft sql']
    has_sql_server = any(kw in title or kw in description for kw in sql_server_keywords)

    if not has_sql_server:
        return False

    # Exclude if other database is the PRIMARY focus (in title)
    other_db_primary_titles = [
        'oracle dba', 'oracle database administrator',
        'postgresql dba', 'postgres dba',
        'mysql dba', 'mysql database administrator',
        'mongodb', 'cassandra', 'nosql dba'
    ]
    is_other_primary = any(kw in title.lower() for kw in other_db_primary_titles)

    if is_other_primary:
        return False

    return True

def search_google_jobs(query, location, date_posted="month"):
    """
    Search Google Jobs - FIXED VERSION
    Uses simple queries that actually work
    """
    global search_count, total_jobs_found

    params = {
        "engine": "google_jobs",
        "q": query,
        "location": location,
        "google_domain": "google.com",
        "hl": "en",
        "chips": f"date_posted:{date_posted}",
        "api_key": API_KEY
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        search_count += 1

        jobs = []
        if "jobs_results" in results:
            for job in results["jobs_results"]:
                job_data = {
                    "title": job.get("title", "N/A"),
                    "company": job.get("company_name", "N/A"),
                    "location": job.get("location", "N/A"),
                    "description": job.get("description", "N/A"),
                    "job_link": job.get("share_url", job.get("apply_options", [{}])[0].get("link", "N/A") if job.get("apply_options") else "N/A"),
                    "posted_at": job.get("detected_extensions", {}).get("posted_at", "N/A"),
                    "salary": job.get("detected_extensions", {}).get("salary", "N/A"),
                    "job_type": job.get("detected_extensions", {}).get("schedule_type", "N/A"),
                    "search_query": query,
                    "search_location": location
                }

                # FIXED: Filter in post-processing instead of query
                if is_sql_server_job(job_data):
                    jobs.append(job_data)

        total_jobs_found += len(jobs)
        return jobs

    except Exception as e:
        log_progress(f"ERROR searching '{query}' in '{location}': {str(e)}")
        return []

def remove_duplicates(jobs):
    """Remove duplicate jobs"""
    unique_jobs = []
    seen_links = set()
    seen_titles_companies = set()

    for job in jobs:
        link = job.get("job_link", "")
        title_company = (job.get("title", ""), job.get("company", ""))

        if link and link != "N/A" and link not in seen_links:
            if title_company not in seen_titles_companies:
                seen_links.add(link)
                seen_titles_companies.add(title_company)
                unique_jobs.append(job)

    return unique_jobs

def analyze_jobs_by_region(jobs):
    """Analyze job distribution by region"""
    regions = {
        "Middle East": 0,
        "India": 0,
        "Southeast Asia": 0,
        "Australia/NZ": 0,
        "Europe": 0,
        "Other": 0
    }

    for job in jobs:
        loc = job.get("location", "").lower()

        if any(x in loc for x in ["uae", "dubai", "abu dhabi", "saudi", "riyadh", "qatar", "kuwait", "bahrain", "oman"]):
            regions["Middle East"] += 1
        elif "india" in loc or any(x in loc for x in ["bangalore", "hyderabad", "mumbai", "pune", "chennai", "delhi"]):
            regions["India"] += 1
        elif any(x in loc for x in ["singapore", "malaysia", "kuala lumpur", "bangkok", "thailand", "manila", "jakarta"]):
            regions["Southeast Asia"] += 1
        elif any(x in loc for x in ["australia", "sydney", "melbourne", "auckland", "new zealand"]):
            regions["Australia/NZ"] += 1
        elif any(x in loc for x in ["uk", "united kingdom", "ireland", "netherlands", "germany", "switzerland", "london", "amsterdam", "zurich"]):
            regions["Europe"] += 1
        else:
            regions["Other"] += 1

    return regions

def main():
    """FIXED execution"""
    global search_count, total_jobs_found

    # Clear previous progress log
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

    print("=" * 90)
    print("GOOGLE JOBS SCRAPER - FIXED VERSION")
    print("=" * 90)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print("FIXED APPROACH:")
    print("  [+] Simple queries that work (tested)")
    print("  [+] Individual locations (no OR operators)")
    print("  [+] Post-processing filter for SQL Server jobs only")
    print("  [+] Date range: Last 30 days")
    print()
    print(f"SEARCH PLAN:")
    print(f"  Queries: {len(WORKING_QUERIES)}")
    print(f"  Locations: {len(PRIORITY_LOCATIONS)}")
    print(f"  Total searches: {len(WORKING_QUERIES) * len(PRIORITY_LOCATIONS)}")
    print(f"  Credits to use: {len(WORKING_QUERIES) * len(PRIORITY_LOCATIONS)} of 250")
    print()
    print(f"REGIONS COVERED:")
    print(f"  Middle East: Dubai, Abu Dhabi, Riyadh")
    print(f"  Asia: Singapore, Bangalore, Kuala Lumpur")
    print(f"  Australia: Sydney")
    print(f"  Europe: London, Amsterdam, Zurich")
    print()
    print("=" * 90)

    log_progress("FIXED search started")

    all_jobs = []

    print("\nSEARCHING...")
    print("-" * 90)

    for i, query in enumerate(WORKING_QUERIES, 1):
        print(f"\n[Query {i}/{len(WORKING_QUERIES)}] {query}")
        print("-" * 90)

        for j, location in enumerate(PRIORITY_LOCATIONS, 1):
            print(f"  [{j}/{len(PRIORITY_LOCATIONS)}] {location}...", end=" ")

            jobs = search_google_jobs(query, location, date_posted="month")

            if jobs:
                print(f"[+] {len(jobs)} SQL Server jobs found")
                all_jobs.extend(jobs)
                log_progress(f"{query} in {location}: {len(jobs)} jobs")
            else:
                print(f"[-] No jobs")
                log_progress(f"{query} in {location}: No jobs")

            # Rate limiting
            time.sleep(1)

    print()
    print("=" * 90)
    print(f"SEARCH COMPLETE")
    print("=" * 90)
    print(f"Search credits used: {search_count}")
    print(f"Remaining credits: {250 - search_count}")
    print(f"Total jobs found (before dedup): {len(all_jobs)}")
    print()

    # Remove duplicates
    print("Removing duplicates...")
    unique_jobs = remove_duplicates(all_jobs)
    duplicates_removed = len(all_jobs) - len(unique_jobs)
    print(f"  Duplicates removed: {duplicates_removed}")
    print(f"  Unique jobs: {len(unique_jobs)}")
    print()

    if unique_jobs:
        # Analyze by region
        print("JOBS BY REGION:")
        print("-" * 50)
        regions = analyze_jobs_by_region(unique_jobs)
        for region, count in regions.items():
            if count > 0:
                percentage = (count / len(unique_jobs)) * 100
                print(f"  {region:20s}: {count:4d} ({percentage:5.1f}%)")
        print()

        # Write to CSV
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'title', 'company', 'location', 'posted_at', 'salary',
                'job_type', 'job_link', 'description', 'search_query', 'search_location'
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for job in unique_jobs:
                writer.writerow(job)

        print(f"[OK] Results saved to: {OUTPUT_FILE}")
        print()

        # Show sample jobs
        print("SAMPLE JOBS FOUND:")
        print("-" * 90)
        for i, job in enumerate(unique_jobs[:10], 1):
            title = job['title'][:60]
            company = job['company'][:25]
            location = job['location'][:30]
            posted = job['posted_at'][:15]
            print(f"{i:2d}. {title:60s}")
            print(f"    {company:25s} | {location:30s} | {posted}")
            print()
    else:
        print("[WARN] No jobs found.")
        print()
        print("Possible reasons:")
        print("  - SQL Server DBA is very specialized")
        print("  - These specific locations have limited openings")
        print("  - Try expanding date range or adding more locations")

    print()
    print("=" * 90)
    print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total search credits used: {search_count} of 250")
    print(f"Remaining credits: {250 - search_count}")
    print()
    print(f"Progress log saved to: {PROGRESS_FILE}")
    print("=" * 90)

    log_progress(f"Search completed: {search_count} credits used, {len(unique_jobs)} unique jobs found")

if __name__ == "__main__":
    main()

