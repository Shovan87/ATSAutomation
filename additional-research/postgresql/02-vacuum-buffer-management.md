# PostgreSQL Internals - Part 2: VACUUM, Buffer Management, and Interview Scenarios

> **Publication and applicability note (reviewed 2026-08-03):** This is independently reviewed, supplemental research, not canonical ATS/RAG implementation documentation. All operational scenarios and examples are hypothetical. PostgreSQL internals, defaults, statistics behavior, extensions, and monitoring views vary by major/minor version and build; verify against the documentation and source for the exact target version. Numeric settings are lab illustrations, not universal production recommendations.


## Table of Contents
4. [VACUUM System](#4-vacuum-system)
5. [Buffer Management](#5-buffer-management)
6. [Scenario-Based Interview Questions](#6-scenario-based-interview-questions)

---

## 4. VACUUM System

VACUUM is PostgreSQL's critical maintenance process for reclaiming space, updating statistics, preventing transaction ID wraparound, and maintaining optimal database performance.

### 4.1 How VACUUM Works Internally

#### Core Functions

VACUUM performs four essential operations:

```
┌────────────────────────────────────────────────────┐
│              VACUUM RESPONSIBILITIES                │
├────────────────────────────────────────────────────┤
│ 1. Remove dead tuples (reclaim space)              │
│ 2. Update planner statistics                       │
│ 3. Update Visibility Map (VM)                      │
│ 4. Freeze old transaction IDs (prevent wraparound) │
└────────────────────────────────────────────────────┘
```

#### VACUUM Algorithm (Detailed)

```pseudocode
function vacuum_relation(relation, options):
    # Phase 1: Scan heap and collect dead tuple TIDs
    dead_tuples = allocate_array(maintenance_work_mem)
    dead_tuple_count = 0
    oldest_xmin = get_oldest_xmin()  # Global visibility horizon

    for each page in relation:
        acquire_buffer_lock(page, SHARED)

        all_visible = true
        all_frozen = true

        for each tuple in page:
            # Check tuple visibility
            if tuple.t_xmax != 0:
                if transaction_committed(tuple.t_xmax):
                    if tuple.t_xmax < oldest_xmin:
                        # Dead tuple - invisible to all transactions
                        dead_tuples[dead_tuple_count++] = tuple.tid
                        all_visible = false
                        all_frozen = false

                        # Mark line pointer as dead (LP_DEAD)
                        if options.truncate:
                            mark_line_pointer_dead(page, tuple)
                    else:
                        # Recently deleted, still visible to some
                        all_visible = false
                        all_frozen = false

            # Check if tuple needs freezing
            if tuple.t_xmin < freeze_limit:
                if not frozen(tuple.t_xmin):
                    # Freeze this tuple
                    freeze_tuple(tuple)
                    mark_page_dirty(page)
            else:
                all_frozen = false

        # Update visibility map
        if all_visible:
            set_vm_bit(page, VM_ALL_VISIBLE)
        if all_frozen:
            set_vm_bit(page, VM_ALL_FROZEN)

        release_buffer_lock(page)

        # Check if dead tuple array is full
        if dead_tuple_count >= max_dead_tuples:
            # Phase 2: Vacuum indexes and remove dead tuples
            vacuum_indexes_and_heap(relation, dead_tuples, dead_tuple_count)
            dead_tuple_count = 0  # Reset for next batch

    # Phase 2: Final vacuum of indexes and heap
    if dead_tuple_count > 0:
        vacuum_indexes_and_heap(relation, dead_tuples, dead_tuple_count)

    # Phase 3: Truncate empty pages at end (if possible)
    if options.truncate:
        truncate_empty_pages(relation)

    # Phase 4: Update statistics
    update_relstats(relation)

    # Phase 5: Update FSM
    update_free_space_map(relation)
```

#### Index Vacuuming

```pseudocode
function vacuum_indexes_and_heap(relation, dead_tuples, count):
    # Sort dead tuple TIDs for efficient processing
    sort_tids(dead_tuples, count)

    # Phase 2a: Vacuum all indexes
    for each index on relation:
        vacuum_index(index, dead_tuples, count)

    # Phase 2b: Remove dead tuples from heap
    for each page containing dead tuples:
        acquire_buffer_lock(page, EXCLUSIVE)

        for each dead_tid in dead_tuples for this page:
            line_pointer = get_line_pointer(page, dead_tid.item_id)

            if line_pointer.flags == LP_DEAD:
                # Mark as unused, space can be reused
                line_pointer.flags = LP_UNUSED
                compact_page_if_needed(page)

        # Update FSM with new free space
        free_space = calculate_free_space(page)
        fsm_set_free_space(relation, page_num, free_space)

        mark_page_dirty(page)
        release_buffer_lock(page)
```

#### Page Compaction (Defragmentation)

```pseudocode
function compact_page_if_needed(page):
    # Check if page has fragmentation
    if page_has_fragmented_space(page):
        # Collect all live tuples
        live_tuples = []

        for each item_id in page:
            lp = get_line_pointer(page, item_id)
            if lp.flags == LP_NORMAL or lp.flags == LP_REDIRECT:
                tuple = get_tuple(page, lp.offset)
                live_tuples.append(tuple, item_id)

        # Rebuild page from end
        offset = page_size - special_space_size

        for each (tuple, item_id) in live_tuples:
            offset -= tuple.size
            copy_tuple_to_offset(page, tuple, offset)

            # Update line pointer
            lp = get_line_pointer(page, item_id)
            lp.offset = offset
            lp.length = tuple.size

        # Update page header
        page.pd_upper = offset

        # All space between pd_lower and pd_upper is now contiguous!
```

#### Freeze Limit Calculation

```pseudocode
function calculate_freeze_limits(relation):
    # Minimum XID age before freezing
    freeze_min_age = vacuum_freeze_min_age  # Default: 50 million

    # Age threshold for aggressive vacuum
    freeze_table_age = vacuum_freeze_table_age  # Default: 150 million

    # Maximum age before forced vacuum
    freeze_max_age = autovacuum_freeze_max_age  # Default: 200 million

    # Calculate freeze limit for this vacuum
    oldest_xmin = get_oldest_xmin()
    current_xid = get_current_transaction_id()

    freeze_limit = current_xid - freeze_min_age

    # Aggressive vacuum mode
    if age(relation.relfrozenxid) > freeze_table_age:
        # More aggressive freezing
        freeze_limit = current_xid - freeze_table_age
        aggressive_mode = true
        # Scan all pages, ignore visibility map

    return freeze_limit, aggressive_mode
```

---

### 4.2 VACUUM FREEZE and Transaction Wraparound

#### Transaction ID Wraparound Problem

```
32-bit XID counter: 0 to 4,294,967,295

XID Comparison uses modulo-2^32 arithmetic:
┌──────────────────────────────────────────┐
│   Current XID: 1,000,000,000             │
├──────────────────────────────────────────┤
│   "Past" XIDs: 1 to 999,999,999         │
│   "Future" XIDs: 2,000,000,001 to 2^32  │
└──────────────────────────────────────────┘

After 2 billion more transactions:
┌──────────────────────────────────────────┐
│   Current XID: 3,000,000,000             │
├──────────────────────────────────────────┤
│   "Past" XIDs: 1,000,000,001 to 3B      │
│   "Future" XIDs: 1 to 999,999,999       │  ← Old XIDs now appear "future"!
└──────────────────────────────────────────┘

DATA LOSS: Old tuples suddenly invisible!
```

#### Freezing Mechanism

**Special Transaction ID:**
```c
#define FrozenTransactionId  2

Frozen tuples are treated as if inserted in the infinite past.
Always visible regardless of wraparound.
```

**Freezing Process (PostgreSQL 9.4+):**
```pseudocode
function freeze_tuple(tuple):
    # Modern approach: Set hint bits instead of changing t_xmin
    # (More efficient, preserves forensic information)

    if tuple.t_xmin < freeze_limit:
        # Set frozen hint bit
        tuple.t_infomask |= HEAP_XMIN_FROZEN

        # Mark page dirty
        mark_buffer_dirty(buffer)

        # WAL log the freeze operation
        log_heap_freeze(relation, block, tuple_offset)
```

**Old approach (PostgreSQL 9.3 and earlier):**
```c
// Physically replaced t_xmin with FrozenTransactionId
tuple.t_xmin = FrozenTransactionId;
```

#### Freezing Thresholds

```sql
-- Configuration parameters
vacuum_freeze_min_age = 50000000          -- 50 million (min XID age to freeze)
vacuum_freeze_table_age = 150000000       -- 150 million (aggressive vacuum trigger)
autovacuum_freeze_max_age = 200000000     -- 200 million (forced vacuum)

-- Actual freeze limit calculation
freeze_limit = current_xid - vacuum_freeze_min_age

-- Example:
-- current_xid = 1,500,000,000
-- freeze_limit = 1,500,000,000 - 50,000,000 = 1,450,000,000
-- Any tuple with xmin < 1,450,000,000 will be frozen
```

#### relfrozenxid and datfrozenxid

**Table-level tracking (pg_class.relfrozenxid):**
```sql
SELECT
    c.oid::regclass AS table_name,
    c.relfrozenxid,
    age(c.relfrozenxid) AS xid_age,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS size
FROM pg_class c
WHERE c.relkind IN ('r', 'm')  -- Regular tables and materialized views
ORDER BY age(c.relfrozenxid) DESC
LIMIT 10;

/*
 table_name     | relfrozenxid | xid_age    | size
----------------+--------------+------------+---------
 old_table      | 1000000      | 199000000  | 5 GB     ← Urgent!
 archive_data   | 1500000      | 198500000  | 10 GB
 logs_2020      | 2000000      | 198000000  | 2 GB
*/
```

**Database-level tracking (pg_database.datfrozenxid):**
```sql
SELECT
    datname,
    datfrozenxid,
    age(datfrozenxid) AS xid_age,
    CASE
        WHEN age(datfrozenxid) > 1800000000 THEN 'CRITICAL'
        WHEN age(datfrozenxid) > 1500000000 THEN 'WARNING'
        ELSE 'OK'
    END AS status
FROM pg_database
ORDER BY age(datfrozenxid) DESC;

/*
 datname    | datfrozenxid | xid_age    | status
------------+--------------+------------+----------
 mydb       | 500000       | 199500000  | WARNING
 postgres   | 1000000      | 199000000  | WARNING
 template1  | 2000000      | 198000000  | OK
*/
```

**datfrozenxid = MIN(relfrozenxid) of all tables in database**

#### Wraparound Protection States

```pseudocode
function check_wraparound_protection():
    current_xid = get_current_transaction_id()

    for each database:
        age = current_xid - database.datfrozenxid

        if age > 2_000_000_000:  # 2 billion
            # CRITICAL: Emergency shutdown imminent
            LOG "ERROR: database is not accepting commands"
            REJECT all new transactions except VACUUM

        elif age > 1_960_000_000:  # ~40 million from wraparound
            # WARNING: Very close to wraparound
            LOG "WARNING: database must be vacuumed within N transactions"
            ALLOW transactions but warn aggressively

        elif age > autovacuum_freeze_max_age:  # Default: 200 million
            # FORCE autovacuum to run (ignores autovacuum=off)
            trigger_anti_wraparound_autovacuum(database)
```

#### VACUUM FREEZE Command

```sql
-- Manual freeze (aggressive)
VACUUM FREEZE mytable;

-- What it does:
-- 1. Scans ALL pages (ignores visibility map)
-- 2. Freezes all tuples regardless of age
-- 3. Updates relfrozenxid to current XID
-- 4. Much more I/O intensive than regular VACUUM

-- Equivalent to:
VACUUM (FREEZE, VERBOSE) mytable;

-- Check progress
SELECT
    phase,
    heap_blks_total,
    heap_blks_scanned,
    heap_blks_vacuumed,
    index_vacuum_count,
    max_dead_tuples,
    num_dead_tuples
FROM pg_stat_progress_vacuum
WHERE relid = 'mytable'::regclass;
```

---

### 4.3 Autovacuum Triggering Logic

#### Autovacuum Daemon Architecture

```
                    ┌────────────────────────┐
                    │  Autovacuum Launcher   │
                    │  (persistent process)  │
                    └───────────┬────────────┘
                                │
                Every autovacuum_naptime (default: 1 min)
                                │
            ┌───────────────────┼───────────────────┐
            │                   │                   │
    ┌───────▼────────┐ ┌────────▼───────┐ ┌────────▼───────┐
    │  AV Worker 1   │ │  AV Worker 2   │ │  AV Worker 3   │
    │  (database A)  │ │  (database B)  │ │  (database C)  │
    └────────────────┘ └────────────────┘ └────────────────┘

Max workers: autovacuum_max_workers (default: 3)
One worker per database at a time
```

#### Vacuum Threshold Formula

```pseudocode
function should_vacuum_table(table):
    # Get table statistics
    reltuples = table.reltuples          # Estimated row count
    n_dead_tup = get_dead_tuple_count(table)  # From pg_stat_all_tables

    # Calculate vacuum threshold
    vacuum_threshold = autovacuum_vacuum_threshold +
                       (autovacuum_vacuum_scale_factor * reltuples)

    # Cap at max threshold (PostgreSQL 14+)
    vacuum_threshold = min(vacuum_threshold, autovacuum_vacuum_max_threshold)

    # Check if vacuum needed
    if n_dead_tup >= vacuum_threshold:
        return true

    # Additional check: insert-only threshold (PostgreSQL 13+)
    insert_threshold = autovacuum_vacuum_insert_threshold +
                       (autovacuum_vacuum_insert_scale_factor * reltuples *
                        (1 - table.relallfrozen / table.relpages))

    n_ins_since_vacuum = get_inserts_since_vacuum(table)

    if n_ins_since_vacuum >= insert_threshold:
        return true  # Vacuum for VM/FSM updates even without dead tuples

    return false
```

#### Default Parameters

```sql
-- Vacuum triggering (per-table overridable)
autovacuum_vacuum_threshold = 50           -- Minimum dead tuples
autovacuum_vacuum_scale_factor = 0.1       -- 10% of table
autovacuum_vacuum_max_threshold = 40000    -- Maximum threshold (PG 14+)

-- Insert-only triggering (PG 13+)
autovacuum_vacuum_insert_threshold = 1000
autovacuum_vacuum_insert_scale_factor = 0.2  -- 20% of unfrozen pages

-- Analyze triggering
autovacuum_analyze_threshold = 50
autovacuum_analyze_scale_factor = 0.1

-- Freeze thresholds
autovacuum_freeze_max_age = 200000000      -- 200 million XIDs
autovacuum_multixact_freeze_max_age = 400000000

-- Daemon settings
autovacuum_naptime = 60s                   -- Check interval
autovacuum_max_workers = 3                 -- Max concurrent workers
```

#### Example Calculations

```sql
-- Table with 1 million rows
reltuples = 1,000,000
autovacuum_vacuum_threshold = 50
autovacuum_vacuum_scale_factor = 0.1

vacuum_threshold = 50 + (0.1 * 1,000,000) = 100,050

-- Vacuum triggers when n_dead_tup >= 100,050

-- Table with 100 rows (small table)
reltuples = 100
vacuum_threshold = 50 + (0.1 * 100) = 60

-- Vacuum triggers when n_dead_tup >= 60

-- Table with 10 billion rows (very large)
reltuples = 10,000,000,000
vacuum_threshold = 50 + (0.1 * 10,000,000,000) = 1,000,000,050
-- But capped at autovacuum_vacuum_max_threshold = 40,000

vacuum_threshold = min(1,000,000,050, 40,000) = 40,000

-- Vacuum triggers when n_dead_tup >= 40,000 (not 1 billion!)
```

#### Per-Table Tuning

```sql
-- Increase threshold for high-churn table
ALTER TABLE logs SET (
    autovacuum_vacuum_threshold = 5000,
    autovacuum_vacuum_scale_factor = 0.05  -- 5% instead of 10%
);

-- Disable autovacuum for static table
ALTER TABLE reference_data SET (
    autovacuum_enabled = false
);

-- More aggressive vacuuming for critical table
ALTER TABLE accounts SET (
    autovacuum_vacuum_threshold = 10,
    autovacuum_vacuum_scale_factor = 0.01,  -- 1%
    autovacuum_vacuum_cost_delay = 5        -- Faster vacuum
);
```

#### Monitoring Autovacuum Activity

```sql
-- Check current autovacuum activity
SELECT
    pid,
    datname,
    usename,
    state,
    query,
    query_start,
    now() - query_start AS duration
FROM pg_stat_activity
WHERE query LIKE 'autovacuum:%'
ORDER BY query_start;

-- Check when tables were last vacuumed
SELECT
    schemaname,
    relname,
    n_tup_ins,
    n_tup_upd,
    n_tup_del,
    n_dead_tup,
    last_vacuum,
    last_autovacuum,
    vacuum_count,
    autovacuum_count
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY n_dead_tup DESC
LIMIT 20;

-- Identify tables needing vacuum
SELECT
    schemaname,
    relname,
    n_dead_tup,
    n_live_tup,
    ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_pct,
    last_autovacuum
FROM pg_stat_all_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC;
```

---

### 4.4 Cost-Based Vacuum Delay

VACUUM throttles I/O to avoid overwhelming the storage system during maintenance.

#### Cost Accounting Model

```pseudocode
function vacuum_with_cost_delay(relation):
    vacuum_cost = 0
    vacuum_cost_limit = vacuum_cost_limit  # Default: 200

    for each page in relation:
        # Read page
        if page in shared_buffers:
            vacuum_cost += vacuum_cost_page_hit     # Default: 1
        else:
            vacuum_cost += vacuum_cost_page_miss    # Default: 2

        # Process page (vacuum dead tuples)
        process_page(page)

        # Write page if modified
        if page_is_dirty(page):
            vacuum_cost += vacuum_cost_page_dirty   # Default: 20

        # Check if cost limit exceeded
        if vacuum_cost >= vacuum_cost_limit:
            # Sleep to throttle I/O
            sleep(vacuum_cost_delay)  # Default: 0ms (disabled)

            # Reset cost counter
            vacuum_cost = 0

    return
```

#### Configuration Parameters

```sql
-- Cost-based vacuum delay settings
vacuum_cost_delay = 0              -- 0 = disabled, >0 = milliseconds to sleep
vacuum_cost_page_hit = 1           -- Cost for buffer hit
vacuum_cost_page_miss = 2          -- Cost for disk read (2x hit)
vacuum_cost_page_dirty = 20        -- Cost for dirty page (20x hit)
vacuum_cost_limit = 200            -- Accumulated cost before delay

-- Example: Enable throttling
vacuum_cost_delay = 10             -- Sleep 10ms after every 200 cost points

-- Per-operation costs:
-- Buffer hit: 1 point
-- Disk read: 2 points
-- Dirty write: 20 points

-- Scenario: Process 200 pages
-- - 150 in buffer (150 * 1 = 150 points)
-- - 50 from disk (50 * 2 = 100 points)
-- - 50 dirtied (50 * 20 = 1000 points)
-- Total: 1250 points

-- Sleep intervals:
-- 1250 / 200 = 6.25 → Sleep 6 times (60ms total delay)
```

#### Load Balancing Across Workers

```pseudocode
function calculate_worker_delay(vacuum_cost_delay, num_workers):
    # Autovacuum balances delay across workers
    # Total I/O impact remains constant

    if num_workers > 1:
        # Each worker sleeps proportionally longer
        effective_delay = vacuum_cost_delay * num_workers
    else:
        effective_delay = vacuum_cost_delay

    return effective_delay

# Example:
# 1 worker: delay = 10ms per limit
# 3 workers: delay = 30ms per limit per worker
# Net effect: Same total I/O rate
```

#### Tuning Guidelines

```sql
-- Scenario 1: Fast vacuum (low-traffic system)
ALTER TABLE mytable SET (
    autovacuum_vacuum_cost_delay = 0,      -- No delay
    autovacuum_vacuum_cost_limit = 10000   -- High limit (ignored if delay=0)
);

-- Scenario 2: Slow vacuum (production OLTP)
ALTER TABLE mytable SET (
    autovacuum_vacuum_cost_delay = 20,     -- 20ms sleep
    autovacuum_vacuum_cost_limit = 200     -- Default limit
);

-- Scenario 3: Very slow vacuum (critical production)
ALTER TABLE mytable SET (
    autovacuum_vacuum_cost_delay = 50,     -- 50ms sleep
    autovacuum_vacuum_cost_limit = 100     -- Lower limit (sleep more often)
);

-- Monitor vacuum I/O impact
SELECT
    relname,
    heap_blks_read,
    heap_blks_hit,
    idx_blks_read,
    idx_blks_hit
FROM pg_statio_all_tables
WHERE schemaname = 'public'
ORDER BY heap_blks_read DESC;
```

---

### SQL Server Comparison: VACUUM vs. Auto-Cleanup

| Feature | PostgreSQL VACUUM | SQL Server |
|---------|-------------------|------------|
| **Dead tuple storage** | In-place (heap table) | Version store (tempdb) |
| **Cleanup mechanism** | VACUUM (manual/auto) | Automatic background cleanup |
| **Space reclamation** | VACUUM + FSM | Auto (version store cleaner) |
| **Wraparound issue** | Yes (32-bit XID) | No (64-bit version) |
| **Freezing** | Required (VACUUM FREEZE) | Not needed |
| **Statistics update** | ANALYZE (with VACUUM) | Auto-update statistics |
| **Cost-based throttling** | Yes (configurable) | No equivalent |
| **Blocking** | Minimal (ShareUpdateExclusive) | Version cleanup non-blocking |
| **Bloat potential** | High (without regular VACUUM) | Low (tempdb auto-shrinks) |
| **Manual intervention** | Often needed for tuning | Rarely needed |

---

## 5. Buffer Management

PostgreSQL's buffer manager coordinates access to shared memory buffers, implementing a sophisticated caching layer between disk and SQL executor.

### 5.1 Buffer Pool Architecture

#### Structure

```
┌────────────────────────────────────────────────────────┐
│              Shared Buffers (shared_buffers)           │
│                   Default: 128MB                       │
│            Recommended: 25% of RAM (up to 40%)         │
├────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────┐     │
│  │  Buffer Descriptors (metadata)               │     │
│  │  ┌──────────┬──────────┬──────────┬────┐    │     │
│  │  │ Desc 0   │ Desc 1   │ Desc 2   │... │    │     │
│  │  └──────────┴──────────┴──────────┴────┘    │     │
│  └──────────────────────────────────────────────┘     │
│  ┌──────────────────────────────────────────────┐     │
│  │  Buffer Data (8KB pages)                     │     │
│  │  ┌──────────┬──────────┬──────────┬────┐    │     │
│  │  │  Page 0  │  Page 1  │  Page 2  │... │    │     │
│  │  └──────────┴──────────┴──────────┴────┘    │     │
│  └──────────────────────────────────────────────┘     │
│  ┌──────────────────────────────────────────────┐     │
│  │  Buffer Hash Table (fast lookup)             │     │
│  │  Key: (tablespace, database, relation, block)│     │
│  │  Value: Buffer ID                            │     │
│  └──────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────┘
```

#### Buffer Descriptor Structure

```c
typedef struct BufferDesc {
    BufferTag   tag;              /* Identifies page (rel, fork, block) */
    int         buf_id;           /* Buffer pool index */

    /* State flags (atomic operations) */
    uint32      state;            /* Lock bits, dirty, valid, usage_count */
    int         wait_backend_pid; /* Backend waiting for I/O */

    /* Reference counting (atomic) */
    pg_atomic_uint32 refcount;    /* Pin count */

    /* Content lock (lightweight lock) */
    LWLock      content_lock;     /* Protects page data */

    /* Free list link */
    int         freeNext;         /* Next buffer in free list */
} BufferDesc;
```

**BufferTag (identifies a specific page):**
```c
typedef struct BufferTag {
    RelFileNode rnode;            /* Tablespace, database, relation */
    ForkNumber  forkNum;          /* Main, FSM, VM, or init fork */
    BlockNumber blockNum;         /* Block number within fork */
} BufferTag;
```

---

### 5.2 Clock Sweep Algorithm (Detailed)

PostgreSQL uses the **clock sweep** algorithm (variant of NFU - Not Frequently Used) for buffer replacement since version 8.1.

#### Algorithm Overview

```
Circular buffer pool (conceptual):
┌───┐   ┌───┐   ┌───┐   ┌───┐   ┌───┐
│ 0 │───│ 1 │───│ 2 │───│ 3 │───│ 4 │
└───┘   └───┘   └───┘   └───┘   └───┘
  │                               │
  └───────────────────────────────┘
           Circular list

nextVictimBuffer points to "clock hand"
Rotates clockwise searching for victim
```

#### Usage Count Mechanism

```c
#define BUF_USAGECOUNT_MAX  5  /* Maximum usage count */

/* State bits in BufferDesc.state */
#define BUF_USAGECOUNT_MASK  0x00003E00  /* 5 bits for usage count (0-5) */
#define BM_DIRTY             0x00000001  /* Page modified */
#define BM_VALID             0x00000002  /* Page contains valid data */
#define BM_TAG_VALID         0x00000004  /* Tag is valid */
#define BM_IO_IN_PROGRESS    0x00000008  /* I/O in progress */
#define BM_PERMANENT         0x00000010  /* Permanent buffer (system catalog) */
```

**Usage Count Incrementation:**
```pseudocode
function increment_usage_count(buffer):
    state = atomic_read(buffer.state)
    usage_count = (state & BUF_USAGECOUNT_MASK) >> BUF_USAGECOUNT_SHIFT

    if usage_count < BUF_USAGECOUNT_MAX:
        usage_count++
        new_state = (state & ~BUF_USAGECOUNT_MASK) |
                    (usage_count << BUF_USAGECOUNT_SHIFT)
        atomic_write(buffer.state, new_state)
```

#### Clock Sweep Implementation

```pseudocode
function get_victim_buffer():
    # Global variables
    # nextVictimBuffer: uint32 (circular index)
    # NBuffers: Total buffer count

    max_iterations = NBuffers * 2  # Safety limit

    for iteration in 1 to max_iterations:
        # Get current candidate
        buf_id = atomic_read_increment(nextVictimBuffer) % NBuffers
        buf_desc = &BufferDescriptors[buf_id]

        # Skip pinned buffers
        if atomic_read(buf_desc.refcount) > 0:
            continue  # In use, skip

        # Get usage count
        state = atomic_read(buf_desc.state)
        usage_count = (state & BUF_USAGECOUNT_MASK) >> BUF_USAGECOUNT_SHIFT

        # Found candidate with usage_count = 0
        if usage_count == 0:
            # Try to acquire this buffer
            if try_pin_buffer(buf_desc):
                return buf_id  # Success!
            else:
                continue  # Another process grabbed it, try next

        # Decrement usage count and continue
        new_usage_count = usage_count - 1
        new_state = (state & ~BUF_USAGECOUNT_MASK) |
                    (new_usage_count << BUF_USAGECOUNT_SHIFT)
        atomic_compare_exchange(buf_desc.state, state, new_state)

    # Should never reach here (safety)
    ERROR: "no unpinned buffers available"
```

#### Buffer Access Path

```pseudocode
function read_buffer(relation, block_num):
    # Phase 1: Check buffer hash table
    tag = make_buffer_tag(relation, block_num)

    acquire_lock(BufMappingLock, SHARED)
    buf_id = hash_lookup(BufferHashTable, tag)

    if buf_id != INVALID_BUFFER:
        # Buffer hit!
        release_lock(BufMappingLock)

        buf_desc = &BufferDescriptors[buf_id]

        # Pin buffer (increment refcount)
        pin_buffer(buf_desc)

        # Increment usage count
        increment_usage_count(buf_desc)

        # Acquire content lock for reading
        acquire_lock(buf_desc.content_lock, SHARED)

        return buf_desc

    # Phase 2: Buffer miss - must load from disk
    release_lock(BufMappingLock)

    # Get victim buffer via clock sweep
    buf_id = get_victim_buffer()
    buf_desc = &BufferDescriptors[buf_id]

    # Pin buffer (refcount = 1)
    pin_buffer(buf_desc)

    # Acquire exclusive content lock
    acquire_lock(buf_desc.content_lock, EXCLUSIVE)

    # If victim was dirty, flush to disk first
    if buffer_is_dirty(buf_desc):
        flush_buffer(buf_desc)

    # Remove old tag from hash table
    acquire_lock(BufMappingLock, EXCLUSIVE)
    hash_delete(BufferHashTable, buf_desc.tag)

    # Read new page from disk
    read_page_from_disk(relation, block_num, buf_desc.data)

    # Update tag and insert into hash table
    buf_desc.tag = tag
    hash_insert(BufferHashTable, tag, buf_id)
    release_lock(BufMappingLock)

    # Set buffer state
    set_buffer_valid(buf_desc)
    set_usage_count(buf_desc, 1)  # Initial usage count

    # Downgrade to shared lock
    downgrade_lock(buf_desc.content_lock, SHARED)

    return buf_desc
```

---

### 5.3 Buffer Replacement Policy

#### Ring Buffer Strategy (Sequential Scans)

**Problem:** Large sequential scans would flood buffer pool, evicting useful cached pages.

**Solution:** Use small ring buffer (256 KB) for sequential scans.

```pseudocode
function get_buffer_strategy(scan_type, table_size):
    if scan_type == SEQUENTIAL_SCAN:
        # Use ring buffer to avoid cache pollution
        ring_size = min(256KB / 8KB, table_size / 8KB)  # 32 buffers or table size
        strategy = allocate_ring_buffer(ring_size)
        return strategy

    elif scan_type == BULK_READ:
        # Larger ring for COPY operations
        ring_size = 16MB / 8KB  # 2048 buffers
        return allocate_ring_buffer(ring_size)

    elif scan_type == VACUUM:
        # Small ring for VACUUM
        ring_size = 256KB / 8KB  # 32 buffers
        return allocate_ring_buffer(ring_size)

    else:
        # Normal access: use main buffer pool
        return NULL
```

**Ring Buffer in Action:**
```sql
-- Sequential scan with ring buffer
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM large_table;  -- 10 GB table

/*
Seq Scan on large_table  (cost=0.00..180000.00 rows=10000000)
  Buffers: shared hit=32 read=1280000

Explanation:
- Table has 1,280,000 pages (10 GB / 8 KB)
- Only 32 buffers used (ring buffer)
- Doesn't pollute main buffer pool!
*/

-- Regular indexed access uses main buffer pool
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM large_table WHERE id = 12345;

/*
Index Scan using pk_large_table on large_table
  Buffers: shared hit=4 (uses main buffer pool)
*/
```

#### Free List

**Initial state:** All buffers on free list.

```pseudocode
function initialize_buffer_pool():
    freelist_lock = create_lock()
    freelist_head = 0

    for buf_id in 0 to NBuffers - 1:
        buf_desc = &BufferDescriptors[buf_id]
        buf_desc.refcount = 0
        buf_desc.freeNext = buf_id + 1
        buf_desc.state = 0  # Invalid, clean, usage_count = 0

    BufferDescriptors[NBuffers - 1].freeNext = INVALID_BUFFER

    return freelist_head
```

**Fast path for initial buffer allocation:**
```pseudocode
function get_buffer_fast_path():
    acquire_lock(freelist_lock)

    if freelist_head != INVALID_BUFFER:
        buf_id = freelist_head
        buf_desc = &BufferDescriptors[buf_id]
        freelist_head = buf_desc.freeNext

        release_lock(freelist_lock)

        pin_buffer(buf_desc)
        return buf_id

    release_lock(freelist_lock)

    # Free list exhausted, use clock sweep
    return get_victim_buffer()
```

---

### 5.4 Pin/Unpin Mechanism

The pin/unpin mechanism prevents buffer eviction while a backend is actively using a page.

#### Pin Operation (Increment Reference Count)

```pseudocode
function pin_buffer(buf_desc):
    # Atomically increment refcount
    old_refcount = atomic_fetch_add(buf_desc.refcount, 1)

    # If this is first pin, increment usage count
    if old_refcount == 0:
        increment_usage_count(buf_desc)

    return buf_desc
```

#### Unpin Operation (Decrement Reference Count)

```pseudocode
function unpin_buffer(buf_desc):
    # Atomically decrement refcount
    old_refcount = atomic_fetch_sub(buf_desc.refcount, 1)

    if old_refcount == 1:
        # Last pin removed, buffer eligible for eviction
        # Signal any waiters
        if buf_desc.wait_backend_pid != 0:
            signal_backend(buf_desc.wait_backend_pid)

    elif old_refcount < 1:
        ERROR: "buffer refcount underflow"

    return
```

#### Example: Query Execution with Pin/Unpin

```pseudocode
function execute_seq_scan(relation):
    block_num = 0

    while block_num < relation.num_blocks:
        # PIN buffer
        buf_desc = read_buffer(relation, block_num)
        # refcount++ (prevents eviction)

        page = buf_desc.data

        # Process all tuples on page
        for each tuple in page:
            if tuple_visible(tuple):
                yield tuple

        # UNPIN buffer
        unpin_buffer(buf_desc)
        # refcount-- (allows eviction)

        block_num++

    return
```

#### Pin Count Tracking

```sql
-- Monitor buffer pin counts (requires pg_buffercache extension)
CREATE EXTENSION pg_buffercache;

SELECT
    c.relname,
    count(*) AS buffers,
    sum(b.pinning_backends) AS total_pins,
    avg(b.usagecount) AS avg_usage
FROM pg_buffercache b
JOIN pg_class c ON b.relfilenode = pg_relation_filenode(c.oid)
WHERE b.reldatabase = (SELECT oid FROM pg_database WHERE datname = current_database())
GROUP BY c.relname
ORDER BY buffers DESC
LIMIT 20;

-- Check for stuck pins (debugging)
SELECT
    usagecount,
    pinning_backends,
    count(*) AS buffer_count
FROM pg_buffercache
WHERE pinning_backends > 0
GROUP BY usagecount, pinning_backends
ORDER BY pinning_backends DESC;
```

---

### 5.5 Lightweight Latches

PostgreSQL uses lightweight locks (LWLocks) for buffer management synchronization.

#### LWLock Types for Buffer Manager

```c
/* Buffer-related LWLocks */
typedef enum {
    BufMappingLock,        /* Protects buffer hash table */
    BufFreelistLock,       /* Protects free buffer list */
    /* Per-buffer content locks (one per buffer) */
    BufferContentLock_0,
    BufferContentLock_1,
    /* ... */
    BufferContentLock_N
} LWLockId;
```

#### LWLock States

```
Unlocked       → No holders
Shared         → Multiple readers (SELECT)
Exclusive      → Single writer (INSERT/UPDATE/DELETE)
```

#### Buffer Content Lock (Per-Buffer)

```pseudocode
function acquire_buffer_content_lock(buf_desc, mode):
    # Buffer content lock coordinates page reads/writes

    if mode == SHARED:
        # Multiple readers allowed
        lwlock_acquire(buf_desc.content_lock, LW_SHARED)
        # Can now read page data safely

    elif mode == EXCLUSIVE:
        # Exclusive writer
        lwlock_acquire(buf_desc.content_lock, LW_EXCLUSIVE)
        # Can now modify page data
        # Must mark buffer dirty when done

    return
```

#### Locking Protocol

```pseudocode
function modify_buffer(relation, block_num):
    # 1. Find/load buffer (pins it automatically)
    buf_desc = read_buffer(relation, block_num)

    # 2. Upgrade to exclusive content lock
    acquire_lock(buf_desc.content_lock, EXCLUSIVE)

    # 3. Modify page
    modify_page(buf_desc.data)

    # 4. Mark buffer dirty
    mark_buffer_dirty(buf_desc)

    # 5. Release content lock
    release_lock(buf_desc.content_lock)

    # 6. Unpin buffer
    unpin_buffer(buf_desc)

    return
```

#### BufMappingLock (Hash Table Protection)

```pseudocode
function buffer_hash_insert(tag, buf_id):
    # Protect hash table structure with BufMappingLock

    # Partition locking (128 partitions to reduce contention)
    partition = hash(tag) % NUM_BUFFER_PARTITIONS
    lock = &BufMappingLocks[partition]

    acquire_lock(lock, EXCLUSIVE)
    hash_insert(BufferHashTable, tag, buf_id)
    release_lock(lock)

function buffer_hash_lookup(tag):
    partition = hash(tag) % NUM_BUFFER_PARTITIONS
    lock = &BufMappingLocks[partition]

    acquire_lock(lock, SHARED)  # Shared: multiple lookups concurrently
    buf_id = hash_search(BufferHashTable, tag)
    release_lock(lock)

    return buf_id
```

#### Lock Contention Monitoring

```sql
-- Check LWLock contention
SELECT
    wait_event_type,
    wait_event,
    count(*) AS wait_count
FROM pg_stat_activity
WHERE wait_event_type = 'LWLock'
GROUP BY wait_event_type, wait_event
ORDER BY wait_count DESC;

/*
 wait_event_type | wait_event           | wait_count
-----------------+----------------------+------------
 LWLock          | buffer_content       | 45
 LWLock          | buffer_mapping       | 12
 LWLock          | wal_insert           | 8
*/

-- High buffer_content waits: Contention on hot pages
-- Solution: Increase shared_buffers, partition tables

-- High buffer_mapping waits: Hash table contention
-- Solution: Already partitioned (128 partitions), check for hotspots
```

---

### SQL Server Comparison: Buffer Management

| Feature | PostgreSQL | SQL Server |
|---------|------------|------------|
| **Algorithm** | Clock sweep (since 8.1) | Clock sweep (also called "clock algorithm") |
| **Usage count** | 0-5 (5 bits) | Similar concept |
| **Buffer pool name** | shared_buffers | Buffer pool |
| **Default size** | 128 MB | 90% of available memory (dynamic) |
| **Pin mechanism** | Refcount (atomic) | Latch count |
| **Content lock** | LWLock per buffer | Latch per buffer |
| **Hash table** | Partitioned (128) | Hash buckets |
| **Ring buffers** | Yes (SeqScan, VACUUM, COPY) | Not publicly documented |
| **Monitoring** | pg_buffercache extension | sys.dm_os_buffer_descriptors |
| **NUMA awareness** | No (single pool) | Yes (NUMA nodes) |

---

**End of Part 2 Section 4-5**

Next: Section 6 - Scenario-Based Interview Questions (20 comprehensive scenarios with solutions)
