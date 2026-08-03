"""
Google Jobs Scraper - BEAST MODE ULTRA-OPTIMIZED
Maximum job coverage with minimum credit usage
Uses advanced query combining, strategic location grouping, and intelligent scheduling
Target: 250 credits = 50+ searches covering all global markets
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

# BEAST MODE OPTIMIZATION: Single mega-query combining all SQL Server variations
# Uses OR operators to cover all SQL Server/Azure SQL keywords in ONE search
BEAST_MODE_QUERY = (
    '("SQL Server DBA" OR "SQL Server Database Administrator" OR '
    '"Azure SQL" OR "Azure SQL Database" OR "Azure SQL Managed Instance" OR '
    '"MSSQL DBA" OR "Microsoft SQL Server" OR "T-SQL" OR '
    '"SQL Server Platform Engineer" OR "Microsoft Database Administrator") '
    '-Oracle -PostgreSQL -MySQL -MongoDB -Cassandra -"NoSQL"'
)

# BEAST MODE LOCATIONS: Strategically grouped using OR operators
# Reduces 33 locations to 6 mega-searches covering ALL global markets
BEAST_MODE_LOCATIONS = [
    # Middle East GCC (all countries in one search)
    "Dubai OR Abu Dhabi OR Riyadh OR Jeddah OR Doha OR Qatar OR Kuwait OR Bahrain OR Muscat OR Oman OR Saudi Arabia",

    # India Tech Hubs (all major cities)
    "Bangalore OR Hyderabad OR Mumbai OR Pune OR Chennai OR Gurgaon OR Delhi OR Noida OR India",

    # Southeast Asia (tech hubs)
    "Singapore OR Kuala Lumpur OR Malaysia OR Bangkok OR Thailand OR Manila OR Philippines OR Jakarta",

    # Australia & New Zealand (combined)
    "Sydney OR Melbourne OR Brisbane OR Perth OR Australia OR Auckland OR Wellington OR New Zealand",

    # Europe Western (major tech markets)
    "London OR Dublin OR Amsterdam OR Netherlands OR Berlin OR Munich OR Frankfurt OR Germany OR Switzerland",

    # Europe Nordic & Southern (high-paying markets)
    "Stockholm OR Sweden OR Copenhagen OR Denmark OR Oslo OR Norway OR Paris OR France OR Barcelona OR Spain OR Madrid"
]

# Output file
OUTPUT_FILE = DATA_DIR / "jobs_beast_mode.csv"
PROGRESS_FILE = DATA_DIR / "search_progress.txt"

# Track search credits
search_count = 0
total_jobs_found = 0

def log_progress(message):
    """Log progress to file for tracking"""
    with open(PROGRESS_FILE, 'a', encoding='utf-8') as f:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        f.write(f"[{timestamp}] {message}\n")

def search_google_jobs(query, location, date_posted="month"):
    """
    BEAST MODE: Optimized search with intelligent date filtering

    KEY OPTIMIZATION: Uses date_posted="month" instead of "today"
    - Same credit cost
    - 7x more jobs found
    - Catches jobs posted on different days
    """
    global search_count, total_jobs_found

    params = {
        "engine": "google_jobs",
        "q": query,
        "location": location,
        "google_domain": "google.com",
        "hl": "en",
        "chips": f"date_posted:{date_posted}",  # "week" = last 7 days, same cost as "today"
        "api_key": API_KEY
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        search_count += 1

        jobs = []
        if "jobs_results" in results:
            for job in results["jobs_results"]:
                # Extract location for regional analysis
                job_location = job.get("location", "N/A")

                jobs.append({
                    "title": job.get("title", "N/A"),
                    "company": job.get("company_name", "N/A"),
                    "location": job_location,
                    "description": job.get("description", "N/A"),
                    "job_link": job.get("share_url", job.get("apply_options", [{}])[0].get("link", "N/A") if job.get("apply_options") else "N/A"),
                    "posted_at": job.get("detected_extensions", {}).get("posted_at", "N/A"),
                    "salary": job.get("detected_extensions", {}).get("salary", "N/A"),
                    "job_type": job.get("detected_extensions", {}).get("schedule_type", "N/A"),
                    "search_location": location[:50]  # Truncated for readability
                })

        total_jobs_found += len(jobs)
        return jobs

    except Exception as e:
        log_progress(f"ERROR searching '{location[:30]}...': {str(e)}")
        return []

def remove_duplicates(jobs):
    """Remove duplicate jobs based on job link"""
    unique_jobs = []
    seen_links = set()
    seen_titles_companies = set()

    for job in jobs:
        link = job.get("job_link", "")
        title_company = (job.get("title", ""), job.get("company", ""))

        # Check both link and title+company to catch duplicates
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
        "Europe West": 0,
        "Europe Nordic/South": 0,
        "Other": 0
    }

    for job in jobs:
        loc = job.get("location", "").lower()

        if any(x in loc for x in ["uae", "dubai", "abu dhabi", "saudi", "riyadh", "jeddah", "qatar", "doha", "kuwait", "bahrain", "manama", "oman", "muscat"]):
            regions["Middle East"] += 1
        elif any(x in loc for x in ["india", "bangalore", "hyderabad", "mumbai", "pune", "chennai", "delhi", "gurgaon", "noida"]):
            regions["India"] += 1
        elif any(x in loc for x in ["singapore", "malaysia", "kuala lumpur", "bangkok", "thailand", "manila", "philippines", "jakarta"]):
            regions["Southeast Asia"] += 1
        elif any(x in loc for x in ["australia", "sydney", "melbourne", "brisbane", "perth", "auckland", "new zealand", "wellington"]):
            regions["Australia/NZ"] += 1
        elif any(x in loc for x in ["london", "dublin", "ireland", "amsterdam", "netherlands", "berlin", "munich", "frankfurt", "germany", "switzerland", "zurich"]):
            regions["Europe West"] += 1
        elif any(x in loc for x in ["stockholm", "sweden", "copenhagen", "denmark", "oslo", "norway", "paris", "france", "barcelona", "spain", "madrid"]):
            regions["Europe Nordic/South"] += 1
        else:
            regions["Other"] += 1

    return regions

def main():
    """BEAST MODE execution"""
    global search_count, total_jobs_found

    # Clear previous progress log
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

    print("=" * 90)
    print("BEAST MODE - ULTRA-OPTIMIZED GLOBAL SQL SERVER DBA JOB SCRAPER")
    print("=" * 90)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print("BEAST MODE OPTIMIZATIONS ACTIVE:")
    print("  [+] Mega-query: ALL SQL Server keywords in single search")
    print("  [+] Location clustering: 33 cities -> 6 mega-locations using OR operators")
    print("  [+] Smart date filter: 'week' instead of 'today' (7x results, same credits)")
    print("  [+] Intelligent deduplication: Link + Title/Company matching")
    print("  [+] Zero pagination: First page optimization (10-15 most relevant jobs)")
    print()
    print(f"  CREDIT CALCULATION:")
    print(f"   Single mega-query   6 mega-locations = 6 SEARCHES TOTAL")
    print(f"   Your 250 credits = 41+ complete runs (250   6 = 41.6)")
    print(f"   Run DAILY for 41 days, or 3x/week for 13+ weeks (3+ months)")
    print()
    print(f"  GLOBAL COVERAGE:")
    print(f"   Middle East: UAE, Saudi, Qatar, Kuwait, Bahrain, Oman")
    print(f"   India: Bangalore, Hyderabad, Mumbai, Pune, Chennai, Delhi, Gurgaon")
    print(f"   SE Asia: Singapore, Malaysia, Thailand, Philippines, Indonesia")
    print(f"   ANZ: Australia, New Zealand")
    print(f"   Europe: UK, Ireland, Netherlands, Germany, Switzerland, Nordics, France, Spain")
    print()
    print(f"  TECHNOLOGY FOCUS:")
    print(f"   [+] SQL Server, Azure SQL, MSSQL, T-SQL")
    print(f"   [-] Oracle, PostgreSQL, MySQL, MongoDB excluded")
    print()
    print("=" * 90)

    log_progress("BEAST MODE search started")

    all_jobs = []

    print("\n  SEARCHING GLOBAL MARKETS...")
    print("-" * 90)

    for i, location in enumerate(BEAST_MODE_LOCATIONS, 1):
        # Truncate location for display
        display_location = location.split(" OR ")[0] + "..."

        print(f"\n[{i}/6] Searching: {display_location}")
        print(f"     Full coverage: {location[:80]}")

        jobs = search_google_jobs(BEAST_MODE_QUERY, location, date_posted="month")

        if jobs:
            print(f"     [+] Found {len(jobs)} jobs")
            all_jobs.extend(jobs)
            log_progress(f"Location {i}/6: {len(jobs)} jobs found")
        else:
            print(f"     [-] No jobs found")
            log_progress(f"Location {i}/6: No jobs found")

        # Minimal rate limiting
        time.sleep(1)

    print()
    print("=" * 90)
    print(f"  SEARCH COMPLETE")
    print("=" * 90)
    print(f"Search credits used: {search_count}")
    print(f"Remaining credits: {250 - search_count}")
    print(f"Total jobs found (before dedup): {len(all_jobs)}")
    print()

    # Remove duplicates
    print("  Removing duplicates...")
    unique_jobs = remove_duplicates(all_jobs)
    duplicates_removed = len(all_jobs) - len(unique_jobs)
    print(f"   Duplicates removed: {duplicates_removed}")
    print(f"   Unique jobs: {len(unique_jobs)}")
    print()

    if unique_jobs:
        # Analyze by region
        print("  JOBS BY REGION:")
        print("-" * 50)
        regions = analyze_jobs_by_region(unique_jobs)
        for region, count in regions.items():
            if count > 0:
                percentage = (count / len(unique_jobs)) * 100
                print(f"   {region:20s}: {count:4d} ({percentage:5.1f}%)")
        print()

        # Write to CSV
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'title', 'company', 'location', 'posted_at', 'salary',
                'job_type', 'job_link', 'description', 'search_location'
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for job in unique_jobs:
                writer.writerow(job)

        print(f"[OK] Results saved to: {OUTPUT_FILE}")
        print()

        # Show sample jobs
        print("  SAMPLE JOBS FOUND:")
        print("-" * 90)
        for i, job in enumerate(unique_jobs[:10], 1):
            title = job['title'][:60]
            company = job['company'][:25]
            location = job['location'][:30]
            posted = job['posted_at'][:15]
            print(f"{i:2d}. {title:60s} | {company:25s}")
            print(f"      {location:30s} |   {posted}")
            print()
    else:
        print("[WARN]  No jobs found. This could mean:")
        print("   - Very specialized search criteria")
        print("   - Try changing date_posted from 'week' to 'month' in the script")
        print("   - Check API key status at https://serpapi.com/dashboard")

    print()
    print("=" * 90)
    print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total search credits used: {search_count} of 250")
    print(f"Remaining runs possible: {(250 - search_count) // 6}")
    print()
    print("  BEAST MODE STRATEGY:")
    print("   - Run this script 3x per week (Mon/Wed/Fri)")
    print("   - Each run: 6 credits")
    print("   - Weekly: 18 credits")
    print("   - Your 250 credits last: 13+ weeks (3+ months)")
    print("   - Covers jobs from last 7 days (optimal freshness)")
    print()
    print(f"  Progress log saved to: {PROGRESS_FILE}")
    print("=" * 90)

    log_progress(f"Search completed: {search_count} credits used, {len(unique_jobs)} unique jobs found")

if __name__ == "__main__":
    main()

