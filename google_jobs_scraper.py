import os
"""
Google Jobs Scraper using SerpAPI
Searches for Database Administrator positions posted in last 24 hours in UAE/Middle East
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

# Job titles to search (Tier 1 from resume analysis)
JOB_TITLES = [
    "Senior Database Administrator",
    "Senior SQL Server DBA",
    "Azure SQL Database Administrator",
    "Cloud Database Administrator",
    "Database Platform Engineer"
]

# Target locations
LOCATIONS = [
    "Dubai, UAE",
    "Abu Dhabi, UAE",
    "United Arab Emirates",
    "Saudi Arabia",
    "Qatar",
    "Kuwait"
]

# Output CSV file
OUTPUT_FILE = DATA_DIR / "jobs_last_24_hours.csv"

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
    params = {
        "engine": "google_jobs",
        "q": query,
        "location": location,
        "google_domain": "google.ae",  # UAE Google domain
        "gl": "ae",  # Country code for UAE
        "hl": "en",  # Language
        "chips": f"date_posted:{date_posted}",  # Filter by posting date
        "api_key": API_KEY
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()

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

        # Handle pagination if next_page_token exists
        if "serpapi_pagination" in results and "next_page_token" in results["serpapi_pagination"]:
            print(f"  Found pagination token, fetching next page...")
            time.sleep(2)  # Rate limiting
            params["next_page_token"] = results["serpapi_pagination"]["next_page_token"]
            search = GoogleSearch(params)
            next_results = search.get_dict()

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
    print("=" * 80)
    print("Google Jobs Scraper - Last 24 Hours")
    print("=" * 80)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("SerpAPI key loaded from environment.")
    print(f"Output file: {OUTPUT_FILE}")
    print()

    all_jobs = []

    # Search for each job title in each location
    for job_title in JOB_TITLES:
        for location in LOCATIONS:
            print(f"Searching: '{job_title}' in '{location}'...")
            jobs = search_google_jobs(job_title, location, date_posted="today")

            if jobs:
                print(f"  Found {len(jobs)} jobs")
                all_jobs.extend(jobs)
            else:
                print(f"  No jobs found")

            # Rate limiting to avoid hitting API limits
            time.sleep(1)

    print()
    print("=" * 80)
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
        print("Try adjusting the date_posted filter to '3days' or 'week' in the script")

    print("=" * 80)
    print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

if __name__ == "__main__":
    main()

