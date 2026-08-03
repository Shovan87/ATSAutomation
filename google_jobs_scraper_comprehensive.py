import os
"""
Google Jobs Scraper using SerpAPI - COMPREHENSIVE GLOBAL VERSION
Maximum coverage across Middle East, India, South Asia, Australia, and Europe
Uses more credits but provides most thorough job search
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

# Comprehensive job title queries - SQL Server and Azure SQL ONLY
# Excludes Oracle, PostgreSQL, MySQL, MongoDB, and other database technologies
JOB_QUERIES = [
    # Senior SQL Server DBA roles
    '"Senior SQL Server DBA" OR "Senior SQL Server Database Administrator" -Oracle -PostgreSQL -MySQL',

    # Azure SQL specific roles
    '"Azure SQL DBA" OR "Azure SQL Database Administrator" OR "Azure SQL Managed Instance" -Oracle',

    # Microsoft SQL Server platform roles
    '"SQL Server Platform Engineer" OR "Microsoft Database Administrator" OR "MSSQL DBA" -Oracle -Postgres',

    # Cloud SQL Server roles
    '"Cloud SQL Server" OR "SQL Server Cloud" OR "Microsoft Cloud Database" -Oracle -MySQL -MongoDB'
]

# COMPREHENSIVE LOCATIONS - Maximum coverage
COMPREHENSIVE_LOCATIONS = [
    # Middle East - GCC Countries
    "Dubai, UAE",
    "Abu Dhabi, UAE",
    "Riyadh, Saudi Arabia",
    "Jeddah, Saudi Arabia",
    "Doha, Qatar",
    "Kuwait City, Kuwait",
    "Manama, Bahrain",
    "Muscat, Oman",

    # India - Major tech hubs
    "Bangalore, India",
    "Hyderabad, India",
    "Mumbai, India",
    "Pune, India",
    "Chennai, India",
    "Gurgaon, India",

    # South Asia & Southeast Asia
    "Singapore",
    "Kuala Lumpur, Malaysia",
    "Bangkok, Thailand",
    "Manila, Philippines",

    # Australia & New Zealand
    "Sydney, Australia",
    "Melbourne, Australia",
    "Brisbane, Australia",
    "Auckland, New Zealand",

    # Europe - Major tech hubs
    "London, United Kingdom",
    "Dublin, Ireland",
    "Amsterdam, Netherlands",
    "Berlin, Germany",
    "Munich, Germany",
    "Frankfurt, Germany",
    "Zurich, Switzerland",
    "Stockholm, Sweden",
    "Copenhagen, Denmark",
    "Paris, France",
    "Barcelona, Spain"
]

# Output CSV file
OUTPUT_FILE = DATA_DIR / "jobs_comprehensive_last_24_hours.csv"

# Track search credits used
search_count = 0

def search_google_jobs(query, location, date_posted="today"):
    """
    Search Google Jobs using SerpAPI

    Args:
        query: Job title to search
        location: Geographic location
        date_posted: Date filter ("today", "3days", "week", "month")

    Returns:
        List of job results
    """
    global search_count

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
                jobs.append({
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
                })

        return jobs

    except Exception as e:
        print(f"  Error: {str(e)}")
        return []

def main():
    """Main execution function"""
    global search_count

    print("=" * 80)
    print("Google Jobs Scraper - COMPREHENSIVE GLOBAL VERSION")
    print("=" * 80)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("SerpAPI key loaded from environment.")
    print(f"Output file: {OUTPUT_FILE}")
    print()
    print("COMPREHENSIVE SETTINGS:")
    print(f"  - Job queries: {len(JOB_QUERIES)}")
    print(f"  - Locations: {len(COMPREHENSIVE_LOCATIONS)}")
    print(f"  - Total searches: {len(JOB_QUERIES) * len(COMPREHENSIVE_LOCATIONS)}")
    print(f"  - Regions: Middle East (8), India (6), South/SE Asia (4), ANZ (4), Europe (11)")
    print(f"  - Date filter: Last 24 hours")
    print()
    print("⚠️  This will use approximately 132 search credits")
    print()

    response = input("Continue with comprehensive search? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Search cancelled.")
        return

    print()
    all_jobs = []

    for i, query in enumerate(JOB_QUERIES, 1):
        print(f"\n[Query {i}/{len(JOB_QUERIES)}] {query}")
        print("-" * 80)

        for location in COMPREHENSIVE_LOCATIONS:
            print(f"  Searching: {location}...", end=" ")
            jobs = search_google_jobs(query, location, date_posted="today")

            if jobs:
                print(f"✓ {len(jobs)} jobs")
                all_jobs.extend(jobs)
            else:
                print("✗ No jobs")

            time.sleep(0.5)  # Rate limiting

    print()
    print("=" * 80)
    print(f"Search credits used: {search_count}")
    print(f"Remaining credits: {250 - search_count}")
    print(f"Total jobs found: {len(all_jobs)}")
    print("=" * 80)
    print()

    # Remove duplicates
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
                'title', 'company', 'location', 'posted_at', 'salary',
                'job_type', 'job_link', 'description', 'search_query', 'search_location'
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for job in unique_jobs:
                writer.writerow(job)

        print(f"✓ Results saved to: {OUTPUT_FILE}")
        print()

        # Summary by region
        regions = {
            "Middle East": 0,
            "India": 0,
            "South/SE Asia": 0,
            "Australia/NZ": 0,
            "Europe": 0
        }

        for job in unique_jobs:
            loc = job.get("location", "").lower()
            if any(x in loc for x in ["uae", "dubai", "abu dhabi", "saudi", "qatar", "kuwait", "bahrain", "oman"]):
                regions["Middle East"] += 1
            elif "india" in loc:
                regions["India"] += 1
            elif any(x in loc for x in ["singapore", "malaysia", "thailand", "philippines"]):
                regions["South/SE Asia"] += 1
            elif any(x in loc for x in ["australia", "sydney", "melbourne", "auckland", "new zealand"]):
                regions["Australia/NZ"] += 1
            elif any(x in loc for x in ["uk", "ireland", "netherlands", "germany", "switzerland", "sweden", "denmark", "france", "spain", "london", "dublin", "amsterdam", "berlin"]):
                regions["Europe"] += 1

        print("Jobs by region:")
        print("-" * 40)
        for region, count in regions.items():
            print(f"  {region}: {count}")

    else:
        print("No jobs found in last 24 hours.")
        print("Try running with date_posted='3days' or 'week'")

    print()
    print("=" * 80)
    print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total search credits used: {search_count}")
    print("=" * 80)

if __name__ == "__main__":
    main()

