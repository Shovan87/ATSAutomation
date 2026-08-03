import os
"""
Google Jobs Scraper using SerpAPI - OPTIMIZED VERSION
Minimizes API search credits by using combined queries and strategic location targeting
Searches for Database Administrator positions posted in last 24 hours globally
Target regions: Middle East, India, South Asia, Australia, Europe
Outputs results to CSV file with job links and descriptions
"""

import csv
from datetime import datetime
from pathlib import Path
from serpapi import GoogleSearch
import time

# SerpAPI Configuration
API_KEY = os.environ["SERPAPI_API_KEY"]
DATA_DIR = Path(os.environ.get("ATS_DATA_DIR", Path(__file__).resolve().parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# OPTIMIZATION 1: Combine similar job titles into broader searches
# Focused ONLY on SQL Server and Azure SQL (excludes Oracle, PostgreSQL, MySQL, etc.)
OPTIMIZED_QUERIES = [
    # Query 1: SQL Server DBA roles
    '"SQL Server DBA" OR "SQL Server Database Administrator" -Oracle -PostgreSQL -MySQL -MongoDB',

    # Query 2: Azure SQL specific roles
    '"Azure SQL" OR "Azure SQL Database" OR "Azure SQL Managed Instance" -Oracle -Postgres',

    # Query 3: Microsoft database platform roles
    '"Microsoft Database" OR "SQL Server Platform" OR "MSSQL" -Oracle -MySQL'
]

# OPTIMIZATION 2: Strategic global locations covering all target regions
# Balanced approach: broad enough to cover regions, specific enough for relevance
OPTIMIZED_LOCATIONS = [
    # Middle East (3 searches)
    "United Arab Emirates",           # UAE (Dubai, Abu Dhabi, etc.)
    "Saudi Arabia",                   # KSA
    "Qatar OR Kuwait OR Bahrain",     # Other GCC countries combined

    # South Asia (2 searches)
    "India",                          # All India
    "Singapore OR Malaysia",          # Southeast Asia hubs combined

    # Australia & NZ (1 search)
    "Australia OR New Zealand",       # ANZ region combined

    # Europe (3 searches)
    "Germany OR Netherlands",         # Western Europe tech hubs
    "Ireland OR United Kingdom",      # UK/Ireland tech hubs
    "Switzerland OR Sweden OR Denmark" # Nordic/Swiss tech hubs
]

# ALTERNATIVE CONFIGURATIONS:

# Option A: Maximum coverage (12 locations) - uses 36 credits per run
# OPTIMIZED_LOCATIONS = [
#     "United Arab Emirates", "Saudi Arabia", "Qatar", "Kuwait", "Bahrain", "Oman",
#     "India", "Singapore", "Malaysia", "Australia", "Germany", "United Kingdom"
# ]

# Option B: Minimal credits (5 locations) - uses 15 credits per run
# OPTIMIZED_LOCATIONS = [
#     "United Arab Emirates", "India", "Singapore", "Australia", "Germany"
# ]

# Option C: Middle East + India only (4 locations) - uses 12 credits per run
# OPTIMIZED_LOCATIONS = [
#     "United Arab Emirates", "Saudi Arabia", "India", "Singapore"
# ]

# Output CSV file
OUTPUT_FILE = DATA_DIR / "jobs_last_24_hours.csv"

# Track search credits used
search_count = 0

def search_google_jobs(query, location, date_posted="today", fetch_all_pages=False):
    """
    Search Google Jobs using SerpAPI

    Args:
        query: Job title to search
        location: Geographic location
        date_posted: Date filter ("today", "3days", "week", "month")
        fetch_all_pages: If True, fetch all pages (uses more credits). If False, only first page.

    Returns:
        List of job results
    """
    global search_count

    params = {
        "engine": "google_jobs",
        "q": query,
        "location": location,
        "google_domain": "google.com",  # Global Google domain
        "hl": "en",  # Language
        "chips": f"date_posted:{date_posted}",  # Filter by posting date
        "api_key": API_KEY
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        search_count += 1  # Increment search counter

        jobs = []
        if "jobs_results" in results:
            for job in results["jobs_results"]:
                jobs.append({
                    "title": job.get("title", "N/A"),
                    "company": job.get("company_name", "N/A"),
                    "location": job.get("location", "N/A"),
                    "description": job.get("description", "N/A"),
                    "job_link": job.get("share_url", job.get("apply_options", [{}])[0].get("link", "N/A") if job.get("apply_options") else "N/A"),
                    "posted_at": job.get("detected_extensions", {}).get("posted_at", "N/A"),
                    "search_query": query,
                    "search_location": location
                })

        # OPTIMIZATION 3: Only fetch pagination if explicitly enabled
        # By default, skip pagination to save credits (first page usually has most relevant results)
        if fetch_all_pages and "serpapi_pagination" in results and "next_page_token" in results["serpapi_pagination"]:
            print(f"  Found pagination token, fetching next page...")
            time.sleep(2)  # Rate limiting
            params["next_page_token"] = results["serpapi_pagination"]["next_page_token"]
            search = GoogleSearch(params)
            next_results = search.get_dict()
            search_count += 1  # Increment for pagination

            if "jobs_results" in next_results:
                for job in next_results["jobs_results"]:
                    jobs.append({
                        "title": job.get("title", "N/A"),
                        "company": job.get("company_name", "N/A"),
                        "location": job.get("location", "N/A"),
                        "description": job.get("description", "N/A"),
                        "job_link": job.get("share_url", job.get("apply_options", [{}])[0].get("link", "N/A") if job.get("apply_options") else "N/A"),
                        "posted_at": job.get("detected_extensions", {}).get("posted_at", "N/A"),
                        "search_query": query,
                        "search_location": location
                    })

        return jobs

    except Exception as e:
        print(f"  Error searching for '{query}' in '{location}': {str(e)}")
        return []

def main():
    """Main execution function"""
    global search_count

    print("=" * 80)
    print("Google Jobs Scraper - OPTIMIZED VERSION - Last 24 Hours")
    print("=" * 80)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("SerpAPI key loaded from environment.")
    print(f"Output file: {OUTPUT_FILE}")
    print()
    print("OPTIMIZATION SETTINGS:")
    print(f"  - Combined job titles: {len(OPTIMIZED_QUERIES)} queries (instead of 5)")
    print(f"  - Global locations: {len(OPTIMIZED_LOCATIONS)} locations")
    print(f"  - Regions covered: Middle East, India, South Asia, Australia, Europe")
    print(f"  - Pagination: DISABLED (first page only to save credits)")
    print(f"  - Maximum searches: {len(OPTIMIZED_QUERIES) * len(OPTIMIZED_LOCATIONS)}")
    print()

    all_jobs = []

    # Search for each optimized query in each location
    for query in OPTIMIZED_QUERIES:
        for location in OPTIMIZED_LOCATIONS:
            print(f"Searching: '{query}' in '{location}'...")

            # fetch_all_pages=False means only first page (saves credits)
            # Change to True if you want all results but will use more credits
            jobs = search_google_jobs(query, location, date_posted="today", fetch_all_pages=False)

            if jobs:
                print(f"  Found {len(jobs)} jobs")
                all_jobs.extend(jobs)
            else:
                print(f"  No jobs found")

            # Rate limiting to avoid hitting API limits
            time.sleep(1)

    print()
    print("=" * 80)
    print(f"Search credits used: {search_count}")
    print(f"Remaining credits: {250 - search_count}")
    print(f"Total jobs found: {len(all_jobs)}")
    print("=" * 80)
    print()

    # Remove duplicates based on job_link
    unique_jobs = []
    seen_links = set()

    for job in all_jobs:
        link = job.get("job_link", "")
        if link and link != "N/A" and link not in seen_links:
            seen_links.add(link)
            unique_jobs.append(job)

    print(f"Unique jobs after deduplication: {len(unique_jobs)}")
    print()

    # Write to CSV
    if unique_jobs:
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'title',
                'company',
                'location',
                'posted_at',
                'job_link',
                'description',
                'search_query',
                'search_location'
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for job in unique_jobs:
                writer.writerow(job)

        print(f"✓ Results saved to: {OUTPUT_FILE}")
        print()
        print("Sample jobs found:")
        print("-" * 80)

        for i, job in enumerate(unique_jobs[:5], 1):
            print(f"{i}. {job['title']} at {job['company']}")
            print(f"   Location: {job['location']}")
            print(f"   Posted: {job['posted_at']}")
            print(f"   Link: {job['job_link'][:80]}...")
            print()
    else:
        print("No jobs found. This could mean:")
        print("  - No jobs posted in last 24 hours for these titles/locations")
        print("  - API key issue")
        print("  - Network connectivity issue")
        print()
        print("SUGGESTIONS:")
        print("  1. Try adjusting date_posted to '3days' or 'week' in the script")
        print("  2. Enable pagination: set fetch_all_pages=True (uses more credits)")
        print("  3. Run during weekdays (more jobs posted Mon-Fri)")

    print()
    print("=" * 80)
    print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total search credits used: {search_count}")
    print("=" * 80)

if __name__ == "__main__":
    main()

