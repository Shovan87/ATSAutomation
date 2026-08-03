"""
Smart Job Search Scheduler - Maximizes 250 Credits
Automatically tracks credit usage and recommends optimal search schedule
Prevents overspending and maximizes job discovery
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(os.environ.get("ATS_DATA_DIR", Path(__file__).resolve().parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CREDIT_TRACKER_FILE = DATA_DIR / "credit_tracker.json"
BEAST_MODE_CREDITS_PER_RUN = 6
OPTIMIZED_CREDITS_PER_RUN = 27
COMPREHENSIVE_CREDITS_PER_RUN = 132
TOTAL_FREE_CREDITS = 250

def load_credit_tracker():
    """Load credit usage history"""
    if os.path.exists(CREDIT_TRACKER_FILE):
        with open(CREDIT_TRACKER_FILE, 'r') as f:
            return json.load(f)
    else:
        return {
            "total_credits_used": 0,
            "total_credits_available": TOTAL_FREE_CREDITS,
            "search_history": [],
            "start_date": datetime.now().strftime('%Y-%m-%d')
        }

def save_credit_tracker(tracker):
    """Save credit usage history"""
    with open(CREDIT_TRACKER_FILE, 'w') as f:
        json.dump(tracker, indent=2, fp=f)

def record_search(script_type, credits_used, jobs_found):
    """Record a search execution"""
    tracker = load_credit_tracker()

    tracker["total_credits_used"] += credits_used
    tracker["search_history"].append({
        "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "script": script_type,
        "credits": credits_used,
        "jobs_found": jobs_found
    })

    save_credit_tracker(tracker)
    return tracker

def get_recommendation():
    """Get smart recommendation for next search"""
    tracker = load_credit_tracker()

    credits_used = tracker["total_credits_used"]
    credits_remaining = TOTAL_FREE_CREDITS - credits_used

    print("=" * 80)
    print("📊 CREDIT USAGE DASHBOARD")
    print("=" * 80)
    print(f"Total credits available: {TOTAL_FREE_CREDITS}")
    print(f"Credits used: {credits_used}")
    print(f"Credits remaining: {credits_remaining}")
    print()

    if credits_remaining < BEAST_MODE_CREDITS_PER_RUN:
        print("⚠️  WARNING: Insufficient credits for any search!")
        print("   Consider upgrading to paid SerpAPI plan")
        return

    # Calculate possible runs
    beast_runs = credits_remaining // BEAST_MODE_CREDITS_PER_RUN
    optimized_runs = credits_remaining // OPTIMIZED_CREDITS_PER_RUN
    comprehensive_runs = credits_remaining // COMPREHENSIVE_CREDITS_PER_RUN

    print("📈 REMAINING SEARCH CAPACITY:")
    print("-" * 80)
    print(f"Beast Mode runs possible:        {beast_runs} ({BEAST_MODE_CREDITS_PER_RUN} credits each)")
    print(f"Optimized runs possible:         {optimized_runs} ({OPTIMIZED_CREDITS_PER_RUN} credits each)")
    print(f"Comprehensive runs possible:     {comprehensive_runs} ({COMPREHENSIVE_CREDITS_PER_RUN} credits each)")
    print()

    # Show search history
    if tracker["search_history"]:
        print("📜 SEARCH HISTORY (Last 10):")
        print("-" * 80)
        for search in tracker["search_history"][-10:]:
            print(f"   {search['date']} | {search['script']:20s} | "
                  f"{search['credits']:3d} credits | {search.get('jobs_found', 'N/A')} jobs")
        print()

    # Smart recommendations
    print("💡 RECOMMENDED STRATEGY:")
    print("-" * 80)

    if credits_remaining >= 200:
        print("   Status: Plenty of credits available")
        print("   ✓ Run BEAST MODE 3x per week (Mon/Wed/Fri)")
        print("   ✓ Weekly cost: 18 credits")
        print(f"   ✓ This strategy lasts: {credits_remaining // 18} weeks")
        print()
        print("   Alternative: Run COMPREHENSIVE once per week")
        print(f"   ✓ Weekly cost: {COMPREHENSIVE_CREDITS_PER_RUN} credits")
        print(f"   ✓ This strategy lasts: {credits_remaining // COMPREHENSIVE_CREDITS_PER_RUN} weeks")

    elif credits_remaining >= 100:
        print("   Status: Moderate credits remaining")
        print("   ✓ Run BEAST MODE 2x per week (Mon/Fri)")
        print("   ✓ Weekly cost: 12 credits")
        print(f"   ✓ This strategy lasts: {credits_remaining // 12} weeks")
        print()
        print("   ✓ Or run OPTIMIZED once per week")
        print(f"   ✓ This strategy lasts: {credits_remaining // OPTIMIZED_CREDITS_PER_RUN} weeks")

    elif credits_remaining >= 50:
        print("   Status: Low credits - conserve carefully")
        print("   ✓ Run BEAST MODE once per week")
        print("   ✓ Weekly cost: 6 credits")
        print(f"   ✓ This strategy lasts: {credits_remaining // 6} weeks")
        print()
        print("   ⚠️  Avoid COMPREHENSIVE (uses 132 credits)")

    else:
        print("   Status: Very low credits")
        print("   ✓ Run BEAST MODE only when needed")
        print(f"   ✓ Remaining runs: {beast_runs}")
        print()
        print("   💡 Consider upgrading to paid plan for continued access")

    print()
    print("=" * 80)

    # Calculate days until credits run out
    if tracker["search_history"]:
        start_date = datetime.strptime(tracker["start_date"], '%Y-%m-%d')
        days_elapsed = (datetime.now() - start_date).days

        if days_elapsed > 0:
            daily_burn_rate = credits_used / days_elapsed
            days_remaining = credits_remaining / daily_burn_rate if daily_burn_rate > 0 else float('inf')

            print(f"📅 USAGE ANALYTICS:")
            print(f"   Start date: {tracker['start_date']}")
            print(f"   Days elapsed: {days_elapsed}")
            print(f"   Average credits/day: {daily_burn_rate:.1f}")
            print(f"   Estimated days remaining: {days_remaining:.0f}")
            print("=" * 80)

def show_optimal_schedule():
    """Show optimal search schedules for different strategies"""
    print("\n" + "=" * 80)
    print("📅 OPTIMAL SEARCH SCHEDULES")
    print("=" * 80)
    print()

    strategies = [
        {
            "name": "BEAST MODE - Maximum Efficiency (RECOMMENDED)",
            "script": "beast_mode",
            "frequency": "3x per week (Mon/Wed/Fri)",
            "credits_per_run": 6,
            "runs_per_week": 3,
            "weeks_coverage": 250 // (6 * 3),
            "pros": ["Most credit efficient", "Daily coverage", "Global reach"],
            "cons": ["Requires consistent schedule"]
        },
        {
            "name": "OPTIMIZED - Balanced Approach",
            "script": "optimized",
            "frequency": "2x per week (Mon/Thu)",
            "credits_per_run": 27,
            "runs_per_week": 2,
            "weeks_coverage": 250 // (27 * 2),
            "pros": ["Good coverage", "Manageable schedule"],
            "cons": ["Higher credit usage than beast mode"]
        },
        {
            "name": "COMPREHENSIVE - Deep Dive",
            "script": "comprehensive",
            "frequency": "Every 2 weeks",
            "credits_per_run": 132,
            "runs_per_week": 0.5,
            "weeks_coverage": 250 // 132 * 2,
            "pros": ["Most thorough search", "City-specific"],
            "cons": ["High credit cost", "Infrequent runs"]
        },
        {
            "name": "HYBRID - Best of Both Worlds",
            "script": "beast + comprehensive",
            "frequency": "Beast 2x/week + Comprehensive monthly",
            "credits_per_run": "12 + 33/week",
            "runs_per_week": 2,
            "weeks_coverage": 250 // 45,
            "pros": ["Comprehensive + frequent updates", "Balanced cost"],
            "cons": ["Requires planning"]
        }
    ]

    for i, strategy in enumerate(strategies, 1):
        print(f"\n{i}. {strategy['name']}")
        print("-" * 80)
        print(f"   Script: {strategy['script']}")
        print(f"   Frequency: {strategy['frequency']}")
        print(f"   Credits per run: {strategy['credits_per_run']}")
        print(f"   Coverage: ~{strategy['weeks_coverage']} weeks on 250 credits")
        print(f"   Pros: {', '.join(strategy['pros'])}")
        print(f"   Cons: {', '.join(strategy['cons'])}")

    print()
    print("=" * 80)

def main():
    """Main dashboard"""
    get_recommendation()
    show_optimal_schedule()

    print("\n💡 USAGE:")
    print("   After each search, update tracker:")
    print("   >>> from smart_scheduler import record_search")
    print("   >>> record_search('beast_mode', 6, 45)  # script, credits, jobs_found")

if __name__ == "__main__":
    main()

