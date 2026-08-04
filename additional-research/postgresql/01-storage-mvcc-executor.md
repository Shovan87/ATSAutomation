# PostgreSQL Internals - Part 1: Storage, MVCC, and Executor

> **Publication and applicability note (reviewed 2026-08-03):** This is independently reviewed, supplemental research, not canonical ATS/RAG implementation documentation. All operational scenarios and examples are hypothetical. PostgreSQL internals, defaults, statistics behavior, extensions, and monitoring views vary by major/minor version and build; verify against the documentation and source for the exact target version. Numeric settings are lab illustrations, not universal production recommendations.


## Table of Contents
1. [Storage Layer - Complete Details](#1-storage-layer---complete-details)
2. [MVCC Implementation](#2-mvcc-implementation)
3. [Executor Physical Operators](#3-executor-physical-operators)

---

## 1. Storage Layer - Complete Details

### 1.1 Page Structure (8KB Pages)

PostgreSQL organizes all table and index data into fixed-size **pages** (also called blocks), typically **8 KB** (8192 bytes). This is the fundamental unit of I/O between disk and memory.

#### Page Layout Diagram

```
Byte Offset
0        ┌─────────────────────────────────────┐
         │   PageHeaderData (24 bytes)         │
24       ├─────────────────────────────────────┤
         │   ItemIdData Array                  │
         │   (4 bytes each, grows downward)    │
pd_lower ├─────────────────────────────────────┤
         │                                     │
         │   Free Space                        │
         │   (unallocated)                     │
         │                                     │
pd_upper ├─────────────────────────────────────┤
         │   Items (tuples)                    │
         │   (grows upward from end)           │
         │                                     │
pd_special├────────────────────────────────────┤
         │   Special Space                     │
         │   (index-specific, empty for heap)  │
8191     └─────────────────────────────────────┘
```

#### PageHeaderData Structure (24 bytes)

```c
typedef struct PageHeaderData {
    PageXLogRecPtr  pd_lsn;              /* 8 bytes: LSN of last WAL record */
    uint16          pd_checksum;         /* 2 bytes: Page checksum */
    uint16          pd_flags;            /* 2 bytes: Flag bits */
    LocationIndex   pd_lower;            /* 2 bytes: Offset to free space start */
    LocationIndex   pd_upper;            /* 2 bytes: Offset to free space end */
    LocationIndex   pd_special;          /* 2 bytes: Offset to special space */
    uint16          pd_pagesize_version; /* 2 bytes: Page size and version */
    TransactionId   pd_prune_xid;        /* 4 bytes: Oldest unpruned XMAX */
} PageHeaderData;                        /* Total: 24 bytes */
```

**Key Fields:**
- **pd_lsn**: Log Sequence Number - next byte after last WAL record affecting this page
- **pd_lower**: Points to end of item identifier array (grows downward)
- **pd_upper**: Points to start of newest item (grows upward)
- **pd_special**: Start of special space (= page size for ordinary tables)
- **pd_prune_xid**: Optimization for HOT pruning

**Free Space Calculation:**
```
Free Space = pd_upper - pd_lower
```

#### ItemIdData (Line Pointers) - 4 bytes each

```c
typedef struct ItemIdData {
    unsigned lp_off:15;      /* Offset to tuple (from page start) */
    unsigned lp_flags:2;     /* State: unused, normal, redirect, dead */
    unsigned lp_len:15;      /* Byte length of tuple */
} ItemIdData;
```

**States:**
- **LP_UNUSED (0)**: Item identifier not in use
- **LP_NORMAL (1)**: Points to actual tuple
- **LP_REDIRECT (2)**: Redirect to another item (HOT chains)
- **LP_DEAD (3)**: Dead item, can be removed

**CTID (Tuple Identifier):** `(page_number, item_index)`
- Item pointers are stable - never moved until freed
- Enables long-term references from indexes

---

### 1.2 Tuple Structure (HeapTupleHeader)

Each row in a table is stored as a tuple with a header containing MVCC metadata.

#### HeapTupleHeaderData Structure (23 bytes minimum)

```c
typedef struct HeapTupleHeaderData {
    union {
        HeapTupleFields t_heap;
        DatumTupleFields t_datum;
    } t_choice;

    ItemPointerData t_ctid;      /* 6 bytes: Current TID (self or updated version) */
    uint16 t_infomask2;          /* 2 bytes: Number of attributes + flags */
    uint16 t_infomask;           /* 2 bytes: Various flag bits */
    uint8  t_hoff;               /* 1 byte: Offset to user data */
    /* Optional fields follow */
    /* bits8 t_bits[FLEXIBLE_ARRAY_MEMBER]; - NULL bitmap */
} HeapTupleHeaderData;           /* 23 bytes on most platforms */
```

**HeapTupleFields (within t_choice):**
```c
typedef struct HeapTupleFields {
    TransactionId t_xmin;        /* 4 bytes: Inserting transaction ID */
    TransactionId t_xmax;        /* 4 bytes: Deleting/locking transaction ID */
    union {
        CommandId t_cid;         /* 4 bytes: Command ID (same txn) */
        TransactionId t_xvac;    /* 4 bytes: VACUUM XID */
    } t_field3;
} HeapTupleFields;               /* 12 bytes total */
```

#### Complete Tuple Layout

```
Offset
0      ┌─────────────────────────────────────┐
       │ t_xmin (4 bytes)                    │  Transaction that created tuple
4      ├─────────────────────────────────────┤
       │ t_xmax (4 bytes)                    │  Transaction that deleted/locked
8      ├─────────────────────────────────────┤
       │ t_cid / t_xvac (4 bytes)           │  Command ID or VACUUM XID
12     ├─────────────────────────────────────┤
       │ t_ctid (6 bytes)                    │  Self or pointer to new version
18     ├─────────────────────────────────────┤
       │ t_infomask2 (2 bytes)              │  # attributes + flags
20     ├─────────────────────────────────────┤
       │ t_infomask (2 bytes)               │  Flag bits (see below)
22     ├─────────────────────────────────────┤
       │ t_hoff (1 byte)                    │  Offset to actual data
23     ├─────────────────────────────────────┤
       │ NULL Bitmap (optional)              │  1 bit per column if HEAP_HASNULL
       ├─────────────────────────────────────┤
       │ OID (4 bytes, optional)            │  If HEAP_HASOID_OLD set
       ├─────────────────────────────────────┤
       │ Padding to MAXALIGN                 │  Alignment (typically 8 bytes)
t_hoff ├─────────────────────────────────────┤
       │ Column 1 data                       │
       │ Column 2 data                       │
       │ ...                                 │
       │ Column N data                       │
       └─────────────────────────────────────┘
```

#### t_infomask Flags (Key Bits)

```c
/* Visibility and MVCC flags */
#define HEAP_HASNULL            0x0001  /* Has NULL attribute values */
#define HEAP_HASVARWIDTH        0x0002  /* Has variable-width attributes */
#define HEAP_HASEXTERNAL        0x0004  /* Has external (TOAST) attributes */
#define HEAP_HASOID_OLD         0x0008  /* Has object ID (deprecated) */
#define HEAP_XMAX_KEYSHR_LOCK   0x0010  /* xmax is key-shared locker */
#define HEAP_COMBOCID           0x0020  /* t_cid is combo CID */
#define HEAP_XMAX_EXCL_LOCK     0x0040  /* xmax is exclusive locker */
#define HEAP_XMAX_LOCK_ONLY     0x0080  /* xmax is not deleter */

/* Transaction status hint bits */
#define HEAP_XMIN_COMMITTED     0x0100  /* t_xmin committed */
#define HEAP_XMIN_INVALID       0x0200  /* t_xmin aborted */
#define HEAP_XMAX_COMMITTED     0x0400  /* t_xmax committed */
#define HEAP_XMAX_INVALID       0x0800  /* t_xmax aborted */
#define HEAP_XMAX_IS_MULTI      0x1000  /* xmax is MultiXactId */
#define HEAP_UPDATED            0x2000  /* This is updated version */
#define HEAP_MOVED              0x4000  /* Tuple moved (old/new partitions) */
```

**Hint Bits Optimization:**
- Once a transaction's fate is known, hint bits are set
- Avoids repeated CLOG (commit log) lookups
- Dramatically improves visibility check performance

---

### 1.3 TOAST (The Oversized-Attribute Storage Technique)

TOAST handles storage of large field values exceeding the 8 KB page size.

#### Problem and Solution

**Problem:** PostgreSQL doesn't allow tuples to span multiple pages.

**Solution:**
1. Compress large values
2. Store out-of-line in separate TOAST table
3. Transparent to application code

#### Triggering TOAST

```c
#define TOAST_TUPLE_THRESHOLD   2048  /* Bytes - triggers TOAST */
#define TOAST_TUPLE_TARGET      2048  /* Bytes - target size after TOAST */
```

**Algorithm:**
1. If tuple size > TOAST_TUPLE_THRESHOLD (2 KB):
2. Compress/move columns out-of-line until:
   - Size < TOAST_TUPLE_TARGET, OR
   - No more gains possible

#### Storage Strategies

```sql
-- Set storage strategy per column
ALTER TABLE mytable ALTER COLUMN large_col SET STORAGE {PLAIN|EXTENDED|EXTERNAL|MAIN};

-- Set tuple target per table
ALTER TABLE mytable SET (toast_tuple_target = 4096);
```

| Strategy | Compress | Out-of-Line | Use Case |
|----------|----------|-------------|----------|
| **PLAIN** | No | No | Non-TOAST-able types (integers, etc.) |
| **EXTENDED** | Yes | Yes | Default for most types (text, bytea) |
| **EXTERNAL** | No | Yes | Fast substring ops (avoids decompression) |
| **MAIN** | Yes | Last resort | Keep in main table if possible |

#### TOAST Table Structure

For table with OID `12345`, TOAST table is `pg_toast.pg_toast_12345`:

```sql
CREATE TABLE pg_toast.pg_toast_12345 (
    chunk_id   OID,           -- Identifies the TOASTed value
    chunk_seq  INT,           -- Sequence number (0, 1, 2, ...)
    chunk_data BYTEA          -- Actual chunk (~2000 bytes max)
);

CREATE UNIQUE INDEX ON pg_toast_12345 (chunk_id, chunk_seq);
```

**Chunk Size:**
```c
#define TOAST_MAX_CHUNK_SIZE  (BLCKSZ / 4)  /* ~2000 bytes for 8KB pages */
```

#### TOAST Pointer (18 bytes)

When a value is TOASTed, the main table stores a pointer:

```c
typedef struct varatt_external {
    int32       va_rawsize;     /* Original uncompressed size */
    int32       va_extsize;     /* External saved size (compressed) */
    Oid         va_valueid;     /* Unique ID (chunk_id in TOAST table) */
    Oid         va_toastrelid;  /* TOAST table OID */
} varatt_external;              /* 16 bytes + 2 byte header = 18 bytes */
```

#### Performance Benefits

**Example:** Table storing HTML pages
- Raw data: 100% of storage
- With TOAST compression: ~50% of storage
- Main table: Only ~10% of total data
- **Result:** More rows fit in shared_buffers, faster queries

---

### 1.4 Free Space Map (FSM)

The FSM tracks available free space in heap and index pages for efficient INSERT/UPDATE placement.

#### Storage

- **Location:** `{filenode}_fsm` file (e.g., `12345_fsm`)
- **Granularity:** 1 byte per heap page (256 categories of free space)

#### Structure - Tree Organization

```
                    Root FSM Page
                  (Max free space)
                         |
         ┌───────────────┼───────────────┐
         │               │               │
    Upper FSM        Upper FSM       Upper FSM
    (Aggregated)    (Aggregated)    (Aggregated)
         |               |               |
    ┌────┼────┐     ┌────┼────┐     ┌────┼────┐
    │    │    │     │    │    │     │    │    │
Bottom FSM Pages  Bottom FSM Pages  Bottom FSM Pages
(1 byte per heap page)
    |    |    |     |    |    |     |    |    |
Heap Pages    Heap Pages    Heap Pages
```

**Each FSM Page:**
- Binary tree stored as array
- **Leaf nodes:** Represent heap pages
- **Internal nodes:** Store MAX of children
- **Root of FSM page:** Quickly identifies page with most free space

#### Free Space Categories (1 byte = 256 values)

```c
/* Maps page free space to category (0-255) */
Category = (FreeSpace * 255) / BLCKSZ;

/* Example for 8KB page:
   0-31 bytes free   -> Category 0-1   (nearly full)
   1KB free          -> Category 32
   4KB free          -> Category 128
   8KB free          -> Category 255   (completely empty)
*/
```

#### FSM Operations

**Finding a page with free space:**
```pseudocode
function find_page_with_space(required_space):
    category = calculate_category(required_space)
    fsm_page = read_root_fsm_page()

    while fsm_page is not bottom_level:
        # Traverse tree to find page with enough space
        child = find_child_with_max_space(fsm_page)
        fsm_page = read_fsm_page(child)

    return heap_page_with_space
```

**Updating FSM after INSERT/UPDATE:**
```pseudocode
function update_fsm(page_number, new_free_space):
    bottom_fsm = get_bottom_fsm_page(page_number)
    set_category(bottom_fsm, page_number, new_free_space)

    # Propagate changes up the tree
    propagate_max_to_parents(bottom_fsm)
```

#### Monitoring FSM

```sql
-- Install pg_freespacemap extension
CREATE EXTENSION pg_freespacemap;

-- Check free space in a table
SELECT blkno, avail FROM pg_freespace('mytable');

-- Summary statistics
SELECT avg(avail), max(avail), count(*)
FROM pg_freespace('mytable')
WHERE avail > 0;
```

---

### 1.5 Visibility Map (VM)

The VM tracks tuple visibility information at the page level to optimize VACUUM and enable index-only scans.

#### Storage

- **Location:** `{filenode}_vm` file (e.g., `12345_vm`)
- **Granularity:** 2 bits per heap page

#### Two-Bit Structure

```
Bit 1: All-Visible Flag
├─ SET: All tuples on page visible to all transactions
├─ Used for: Index-only scans
└─ VACUUM can skip this page (no dead tuples)

Bit 2: All-Frozen Flag
├─ SET: All tuples on page are frozen
├─ Used for: Anti-wraparound VACUUM
└─ VACUUM FREEZE can skip this page
```

#### Visibility Map Layout

```
For 1 GB relation (131,072 pages):
VM size = 131,072 pages * 2 bits / 8 bits/byte = 32,768 bytes = 32 KB

VM Page for 8KB blocks (each VM page covers many heap pages):
┌──────────────────────────────────────┐
│ Heap Page 0:  [All-Vis][All-Frozen] │ = 2 bits
│ Heap Page 1:  [All-Vis][All-Frozen] │ = 2 bits
│ Heap Page 2:  [All-Vis][All-Frozen] │ = 2 bits
│ ...                                  │
│ Heap Page N:  [All-Vis][All-Frozen] │ = 2 bits
└──────────────────────────────────────┘
```

**Coverage:** 1 VM page can track visibility for thousands of heap pages.

#### Index-Only Scans

**Without VM:**
```sql
SELECT id FROM users WHERE id BETWEEN 1000 AND 2000;
```
1. Index scan finds matching tuples
2. **Heap access required** to check visibility
3. Slower due to random I/O

**With VM (all-visible bit set):**
```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id FROM users WHERE id BETWEEN 1000 AND 2000;
```
```
Index Only Scan using users_pkey on users
  Heap Fetches: 0          <-- No heap access!
  Buffers: shared hit=5    <-- Only index + VM pages
```

1. Index scan finds matching tuples
2. **VM consulted** - all-visible bit is set
3. **Heap access skipped** - tuple visibility guaranteed
4. Much faster!

#### VM Maintenance

**Setting Bits (VACUUM only):**
```pseudocode
function vacuum_page(page):
    for each tuple in page:
        if tuple is dead:
            mark_as_dead(tuple)
            all_visible = false

    if all_visible and all_tuples_visible_to_all:
        set_vm_bit(page, ALL_VISIBLE)

    if all_visible and all_tuples_frozen:
        set_vm_bit(page, ALL_FROZEN)
```

**Clearing Bits (Any write operation):**
```pseudocode
function insert_or_update_or_delete(page, tuple):
    # Clear VM bits before modifying page
    clear_vm_bits(page)

    # Perform modification
    modify_tuple(page, tuple)

    # VACUUM will re-set bits later
```

**Conservative Design:**
- Bits SET = Condition **guaranteed** true
- Bits NOT SET = Condition **may or may not** be true (safe assumption)

#### Monitoring Visibility Map

```sql
-- Install pg_visibility extension
CREATE EXTENSION pg_visibility;

-- Check VM status for a table
SELECT blkno, all_visible, all_frozen
FROM pg_visibility_map('mytable');

-- Summary
SELECT
    count(*) as total_pages,
    sum(all_visible::int) as all_visible_pages,
    sum(all_frozen::int) as all_frozen_pages,
    round(100.0 * sum(all_visible::int) / count(*), 2) as pct_visible,
    round(100.0 * sum(all_frozen::int) / count(*), 2) as pct_frozen
FROM pg_visibility_map('mytable');
```

---

### 1.6 Heap File Organization

PostgreSQL stores each table and index as a set of files in the data directory.

#### File Naming and Segmentation

**Main file:**
```
{PGDATA}/base/{database_oid}/{relfilenode}
```

**Example:**
```
/var/lib/postgresql/data/base/16384/24601
                              ↑      ↑
                         Database  Table OID
```

**Segmentation (files > 1 GB):**
```
24601      -- Segment 0 (first 1 GB)
24601.1    -- Segment 1 (second 1 GB)
24601.2    -- Segment 2 (third 1 GB)
...
```

**Related Files:**
```
24601       -- Main heap file
24601_fsm   -- Free Space Map
24601_vm    -- Visibility Map
24601_init  -- Initialization fork (unlogged tables only)
```

#### Finding Table Files

```sql
-- Get file path for a table
SELECT pg_relation_filepath('mytable');
-- Result: base/16384/24601

-- Get file size
SELECT pg_relation_size('mytable');           -- Main fork only
SELECT pg_total_relation_size('mytable');     -- Including TOAST and indexes
SELECT pg_table_size('mytable');              -- Main + TOAST, no indexes

-- Get detailed size breakdown
SELECT
    pg_size_pretty(pg_relation_size('mytable')) as table_size,
    pg_size_pretty(pg_relation_size('mytable', 'fsm')) as fsm_size,
    pg_size_pretty(pg_relation_size('mytable', 'vm')) as vm_size,
    pg_size_pretty(pg_indexes_size('mytable')) as indexes_size,
    pg_size_pretty(pg_total_relation_size('mytable')) as total_size;
```

#### Relation Forks

PostgreSQL uses multiple "forks" for different purposes:

| Fork | Suffix | Purpose |
|------|--------|---------|
| **main** | (none) | Actual table/index data |
| **fsm** | _fsm | Free Space Map |
| **vm** | _vm | Visibility Map |
| **init** | _init | Initialization fork (unlogged tables) |

#### Tablespaces

```sql
-- Create tablespace on different storage
CREATE TABLESPACE fast_storage LOCATION '/mnt/ssd';

-- Create table in tablespace
CREATE TABLE important_data (...) TABLESPACE fast_storage;

-- File location:
-- /mnt/ssd/PG_16_202307071/{database_oid}/{relfilenode}
```

#### System Catalogs

```sql
-- Find relfilenode for a table
SELECT relfilenode, reltablespace
FROM pg_class
WHERE relname = 'mytable';

-- CAVEAT: relfilenode can change after VACUUM FULL, CLUSTER, or REINDEX
-- Always use pg_relation_filepath() for current path
```

---

### SQL Server Comparison: Storage Layer

| Feature | PostgreSQL | SQL Server |
|---------|------------|------------|
| **Page Size** | 8 KB (fixed) | 8 KB (fixed) |
| **Page Header** | 24 bytes | 96 bytes (more metadata) |
| **Tuple Header** | 23 bytes minimum | 4 bytes (no MVCC overhead) |
| **MVCC Storage** | In-place with xmin/xmax | Separate version store (tempdb) |
| **Large Objects** | TOAST (compressed/out-of-line) | LOB pages, ROW_OVERFLOW |
| **Free Space Tracking** | FSM (1 byte/page, separate file) | PFS (Page Free Space, in data file) |
| **Visibility Tracking** | VM (2 bits/page, separate file) | None (no MVCC) |
| **File Organization** | Heap tables only | Heap or clustered index (default) |
| **Clustering** | Manual (CLUSTER command) | Automatic (clustered index) |

**Key Differences:**
1. **PostgreSQL**: MVCC data stored in-heap → more bloat, requires VACUUM
2. **SQL Server**: Versions in tempdb → less bloat, automatic cleanup
3. **PostgreSQL**: Heap-only tables by default → no inherent order
4. **SQL Server**: Clustered index by default → inherent physical order

---

## 2. MVCC Implementation

### 2.1 Snapshot Isolation Implementation

PostgreSQL implements **Multiversion Concurrency Control (MVCC)** using snapshot isolation.

#### Core Concept

**Snapshot:** Metadata structure capturing transaction state at a point in time.

```c
typedef struct SnapshotData {
    TransactionId xmin;        /* All XIDs < xmin are committed/aborted */
    TransactionId xmax;        /* All XIDs >= xmax are in-progress/future */
    TransactionId *xip;        /* Array of in-progress XIDs (xmin <= XID < xmax) */
    uint32        xcnt;        /* Number of XIDs in xip[] */
    /* ... other fields ... */
} SnapshotData;
```

**Example Snapshot:**
```
Timeline of transactions:
100 101 102 103 104 105 106 107 108
 C   C   A   R   R   R   C   ?   ?

Legend: C=Committed, A=Aborted, R=Running, ?=Not started

Snapshot taken at time T:
┌─────────────────────────────────┐
│ xmin = 103                      │  All XIDs < 103 are done
│ xmax = 108                      │  All XIDs >= 108 haven't started
│ xip = [104, 105, 106]          │  In-progress transactions
│ xcnt = 3                        │  Count of in-progress
└─────────────────────────────────┘
```

#### Snapshot Timing by Isolation Level

```sql
-- READ COMMITTED: New snapshot per statement
BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED;
SELECT * FROM accounts WHERE id = 1;  -- Snapshot 1 at T1
-- Another transaction commits changes
SELECT * FROM accounts WHERE id = 1;  -- Snapshot 2 at T2 (sees new changes)
COMMIT;

-- REPEATABLE READ: One snapshot for entire transaction
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SELECT * FROM accounts WHERE id = 1;  -- Snapshot taken at transaction start
-- Another transaction commits changes
SELECT * FROM accounts WHERE id = 1;  -- Same snapshot (doesn't see changes)
COMMIT;
```

#### Snapshot Acquisition Pseudocode

```pseudocode
function get_snapshot():
    snapshot = allocate_snapshot()

    # Acquire shared lock on ProcArray
    acquire_lock(ProcArrayLock, SHARED)

    # Set xmin to oldest running transaction
    snapshot.xmin = get_oldest_xmin()

    # Set xmax to next XID to be assigned
    snapshot.xmax = get_next_xid()

    # Copy list of in-progress transactions
    snapshot.xip = []
    snapshot.xcnt = 0

    for each proc in proc_array:
        if proc.xid >= snapshot.xmin and proc.xid < snapshot.xmax:
            snapshot.xip[snapshot.xcnt++] = proc.xid

    release_lock(ProcArrayLock)

    return snapshot
```

---

### 2.2 Transaction ID (XID) Management

#### XID Architecture

```c
typedef uint32 TransactionId;  /* 32-bit counter */

Special XIDs:
#define InvalidTransactionId    0      /* Invalid/bootstrap XID */
#define BootstrapTransactionId  1      /* Bootstrap XID */
#define FrozenTransactionId     2      /* Frozen tuples */
#define FirstNormalTransactionId 3     /* First normal XID */
```

**XID Lifecycle:**
```
Counter: 3 → 4 → 5 → ... → 4,294,967,295 → 3 (wraparound!)
         ↑                                  ↑
    FirstNormal                      MaxTransactionId

Every transaction consumes one XID when it first writes.
```

#### XID Assignment

```pseudocode
function get_current_transaction_id():
    if MyProc.xid != InvalidTransactionId:
        return MyProc.xid  # Already assigned

    # Assign new XID
    acquire_lock(XidGenLock, EXCLUSIVE)

    xid = ShmemVariableCache.nextXid
    ShmemVariableCache.nextXid = xid + 1

    # Check wraparound protection
    if age(xid) > 2_billion:
        ERROR: "database is not accepting commands to avoid wraparound"

    release_lock(XidGenLock)

    MyProc.xid = xid
    MyProc.subxid_count = 0

    return xid
```

#### SubXIDs (Subtransactions)

```sql
BEGIN;
    INSERT INTO accounts VALUES (1, 1000);  -- Main XID = 1000

    SAVEPOINT sp1;
    UPDATE accounts SET balance = 500 WHERE id = 1;  -- SubXID = 1001
    RELEASE SAVEPOINT sp1;

    SAVEPOINT sp2;
    DELETE FROM accounts WHERE id = 2;               -- SubXID = 1002
    ROLLBACK TO sp2;  -- SubXID 1002 aborted

COMMIT;  -- Main XID 1000 commits (SubXID 1001 commits with it)
```

**SubXID Tracking:**
```c
#define PGPROC_MAX_CACHED_SUBXIDS 64

If subxids > 64:
    - Overflow flag set in PGPROC
    - Must scan pg_subtrans SLRU for complete list
    - Visibility checks become slower
```

---

### 2.3 Tuple Visibility Rules with Pseudocode

Every tuple visibility check answers: **"Can this snapshot see this tuple?"**

#### System Columns Used in Visibility

```sql
SELECT xmin, xmax, ctid, * FROM mytable;

 xmin | xmax |  ctid  | id | name
------+------+--------+----+-------
 1000 |    0 | (0,1)  |  1 | Alice   -- Inserted by XID 1000, not deleted
 1005 | 1010 | (0,2)  |  2 | Bob     -- Inserted by 1005, deleted by 1010
 1010 |    0 | (0,3)  |  2 | Robert  -- New version of id=2, inserted by 1010
```

#### Visibility Check Algorithm (Simplified)

```pseudocode
function tuple_visible(tuple, snapshot):
    # Fast path: Check hint bits first (cached transaction status)
    if tuple.t_infomask & HEAP_XMIN_COMMITTED:
        xmin_committed = true
    elif tuple.t_infomask & HEAP_XMIN_INVALID:
        return false  # Creating transaction aborted
    else:
        xmin_committed = transaction_id_did_commit(tuple.t_xmin)
        # Set hint bit for next check
        set_hint_bit(tuple, xmin_committed)

    if not xmin_committed:
        return false  # Tuple never existed for us

    # Check if xmin is visible to our snapshot
    if not xmin_visible_in_snapshot(tuple.t_xmin, snapshot):
        return false  # Created after our snapshot

    # Tuple was created before our snapshot
    # Now check if it was deleted

    if tuple.t_infomask & HEAP_XMAX_INVALID:
        return true  # Not deleted

    # Check xmax (deleting transaction)
    if tuple.t_infomask & HEAP_XMAX_COMMITTED:
        xmax_committed = true
    else:
        xmax_committed = transaction_id_did_commit(tuple.t_xmax)
        set_hint_bit(tuple, xmax_committed)

    if not xmax_committed:
        return true  # Delete aborted, tuple still visible

    # Check if xmax is visible to our snapshot
    if xmax_visible_in_snapshot(tuple.t_xmax, snapshot):
        return false  # Deleted before our snapshot
    else:
        return true   # Deleted after our snapshot, we can see it
```

#### XID Visibility in Snapshot

```pseudocode
function xmin_visible_in_snapshot(xid, snapshot):
    # Special cases
    if xid == FrozenTransactionId:
        return true  # Frozen = always visible

    if xid >= snapshot.xmax:
        return false  # Transaction started after snapshot

    if xid < snapshot.xmin:
        return true   # Transaction finished before snapshot

    # xmin <= xid < xmax: check in-progress list
    if xid in snapshot.xip:
        return false  # Was running when snapshot taken

    return true  # Committed before snapshot
```

#### Complete Visibility Rules Table

| Condition | xmin Status | xmax Status | Visible? |
|-----------|-------------|-------------|----------|
| 1 | Aborted | (any) | No |
| 2 | In-progress | (any) | No (unless self) |
| 3 | Future | (any) | No |
| 4 | Committed before snap | Invalid/0 | **Yes** |
| 5 | Committed before snap | Aborted | **Yes** |
| 6 | Committed before snap | In-progress | **Yes** |
| 7 | Committed before snap | Future | **Yes** |
| 8 | Committed before snap | Committed before snap | No (deleted) |
| 9 | Committed before snap | Committed after snap | **Yes** |

#### Real-World Example

```sql
-- Session 1: Take snapshot at XID 1000
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
-- Snapshot: xmin=1000, xmax=1001, xip=[]

-- Session 2: Insert row (XID 1001)
INSERT INTO users VALUES (1, 'Alice');
-- Tuple: xmin=1001, xmax=0

-- Session 1: Query
SELECT * FROM users WHERE id = 1;
-- Check: xmin=1001 >= snapshot.xmax (1001) → NOT VISIBLE

-- Session 2: Commit
COMMIT;

-- Session 1: Query again (same snapshot)
SELECT * FROM users WHERE id = 1;
-- Check: xmin=1001 >= snapshot.xmax (1001) → STILL NOT VISIBLE
-- REPEATABLE READ: Same snapshot, consistent results

-- Session 1: Commit and start new transaction
COMMIT;
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
-- New snapshot: xmin=1000, xmax=1002, xip=[]

SELECT * FROM users WHERE id = 1;
-- Check: xmin=1001 < snapshot.xmax AND committed → VISIBLE!
```

---

### 2.4 xmin/xmax/xip Mechanism

#### Transaction State Storage - CLOG (Commit Log)

```
CLOG (pg_xact/) stores 2 bits per transaction:
00 = In progress
01 = Committed
10 = Aborted
11 = Sub-committed (subtransaction committed, parent unknown)

File structure:
pg_xact/0000  -- XIDs 0 to 1,048,575 (2M transactions * 2 bits / 8 = 512KB)
pg_xact/0001  -- XIDs 1,048,576 to 2,097,151
pg_xact/0002  -- ...
```

**CLOG Lookup:**
```pseudocode
function transaction_id_did_commit(xid):
    # Check local cache first
    if xid in clog_cache:
        return clog_cache[xid] == COMMITTED

    # Calculate CLOG file and offset
    file_num = xid / TRANSACTIONS_PER_FILE
    byte_offset = (xid % TRANSACTIONS_PER_FILE) * 2 / 8
    bit_offset = (xid % 4) * 2

    # Read from SLRU
    page = slru_read_page(CLOG, file_num, byte_offset / BLCKSZ)
    byte = page[byte_offset % BLCKSZ]
    status = (byte >> bit_offset) & 0x03

    # Cache result
    clog_cache[xid] = status

    return status == COMMITTED
```

#### Hint Bits Optimization

**Problem:** Every visibility check requires CLOG lookup (I/O expensive)

**Solution:** Cache transaction status in tuple header (hint bits)

```c
/* First visibility check for tuple with xmin=1000 */
Step 1: Check hint bits → Not set
Step 2: Check CLOG → XID 1000 committed
Step 3: Set HEAP_XMIN_COMMITTED hint bit in tuple
Step 4: Mark page dirty (hint bit change)

/* Second visibility check */
Step 1: Check hint bits → HEAP_XMIN_COMMITTED set
Step 2: Return immediately (no CLOG lookup!)

Performance gain: 100-1000x faster
```

**Hint Bit Write Amplification:**
- Setting hint bits dirties pages
- Can cause extra writes
- Trade-off: More writes now vs. repeated CLOG lookups later
- Usually worthwhile for frequently-accessed data

---

### 2.5 HOT (Heap-Only Tuples) Updates

HOT is an optimization that eliminates index updates for UPDATEs that don't modify indexed columns.

#### Conditions for HOT Update

```sql
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    price NUMERIC,
    stock INT,
    last_updated TIMESTAMP
);

CREATE INDEX idx_price ON products(price);

-- HOT UPDATE (indexed columns unchanged)
UPDATE products SET stock = stock - 1, last_updated = NOW()
WHERE id = 100;
-- ✅ HOT: id and price unchanged, sufficient free space on page

-- NON-HOT UPDATE (indexed column changed)
UPDATE products SET price = 29.99
WHERE id = 100;
-- ❌ NOT HOT: price is indexed, index entry must be updated
```

**Requirements:**
1. ✅ No indexed columns modified (except expression indexes)
2. ✅ Enough free space on same page for new tuple version
3. ✅ Not a cross-partition update

#### HOT Chain Structure

```
Page Layout (after multiple HOT updates):

ItemId Array:
[0] → Offset 8000 (REDIRECT to [3])
[1] → Offset 7500 (DEAD)
[2] → Offset 7000 (DEAD)
[3] → Offset 6500 (NORMAL - newest version)

Tuple Data:
Offset 8000: [Original tuple]      xmin=1000, xmax=1001, ctid=(0,1)
Offset 7500: [Updated v1]          xmin=1001, xmax=1002, ctid=(0,2)
Offset 7000: [Updated v2]          xmin=1002, xmax=1003, ctid=(0,3)
Offset 6500: [Updated v3, current] xmin=1003, xmax=0,    ctid=(0,3)

Index entry still points to ItemId [0]
→ Redirected to ItemId [3]
→ No index update needed!
```

**HOT Chain Traversal:**
```pseudocode
function follow_hot_chain(page, item_id, snapshot):
    item_pointer = get_item_pointer(page, item_id)

    # Follow redirects
    while item_pointer.flags == LP_REDIRECT:
        item_id = item_pointer.redirect_target
        item_pointer = get_item_pointer(page, item_id)

    tuple = get_tuple(page, item_pointer.offset)

    # Follow ctid chain if tuple not visible
    while not tuple_visible(tuple, snapshot):
        if tuple.t_ctid == tuple.self_ctid:
            return null  # No visible version

        (next_page, next_item) = tuple.t_ctid

        if next_page != current_page:
            break  # Chain leaves page (not HOT)

        tuple = get_tuple(next_page, next_item)

    return tuple
```

#### HOT Pruning

**Problem:** Dead tuples accumulate in HOT chains

**Solution:** Lazy HOT pruning during normal operations

```pseudocode
function prune_hot_chain_if_needed(page):
    if not page_is_full(page):
        return  # No pressure, skip pruning

    oldest_xmin = get_global_oldest_xmin()

    for each tuple in page:
        if tuple.xmax != 0 and tuple.xmax < oldest_xmin:
            # This version is dead to all transactions
            if tuple.ctid points to tuple on same page:
                # Part of HOT chain
                mark_line_pointer_as_DEAD(tuple)
                reclaim_tuple_storage(tuple)

    # Update redirect pointers to skip dead tuples
    for each line_pointer in page:
        if line_pointer.flags == LP_REDIRECT:
            target = follow_to_live_tuple(line_pointer)
            line_pointer.redirect_target = target
```

**Benefits:**
- Happens during SELECT, UPDATE, INSERT (not just VACUUM)
- Reclaims space quickly
- Keeps pages from bloating

#### Fillfactor Configuration

```sql
-- Default fillfactor = 90 (10% reserved for updates)
CREATE TABLE products (...);

-- High update frequency → Lower fillfactor (more HOT updates)
CREATE TABLE frequent_updates (...) WITH (fillfactor = 70);

-- Read-mostly table → Higher fillfactor (less wasted space)
CREATE TABLE mostly_reads (...) WITH (fillfactor = 100);
```

**Impact:**
```
fillfactor = 90: 8192 * 0.90 = 7372 bytes available initially, 820 bytes for HOT
fillfactor = 70: 8192 * 0.70 = 5734 bytes available initially, 2458 bytes for HOT

More reserved space = More HOT updates = Less bloat = Better performance
Trade-off: More disk space used
```

#### Monitoring HOT

```sql
-- Check HOT update efficiency
SELECT
    schemaname,
    relname,
    n_tup_upd AS total_updates,
    n_tup_hot_upd AS hot_updates,
    ROUND(100.0 * n_tup_hot_upd / NULLIF(n_tup_upd, 0), 2) AS hot_update_pct
FROM pg_stat_all_tables
WHERE n_tup_upd > 0
ORDER BY n_tup_upd DESC
LIMIT 20;

-- Low hot_update_pct indicates:
-- 1. Updates modify indexed columns frequently
-- 2. Pages don't have enough free space (decrease fillfactor)
-- 3. Table needs more aggressive vacuuming
```

---

### SQL Server Comparison: MVCC

| Feature | PostgreSQL | SQL Server |
|---------|------------|------------|
| **MVCC Storage** | In-place (xmin/xmax in tuple) | Version store (tempdb) |
| **Snapshot Location** | Per-backend memory | Shared version store |
| **Tuple Overhead** | 23+ bytes per row | 14 bytes version pointer (when versioned) |
| **Old Versions** | Same table, requires VACUUM | Tempdb, auto-cleanup |
| **Bloat** | Significant without VACUUM | Minimal (tempdb auto-shrinks) |
| **Read Performance** | Faster (no version store lookup) | Slower (may need version store) |
| **Write Performance** | Slower (in-place update) | Faster (version to tempdb) |
| **HOT Optimization** | Yes (HOT updates) | No equivalent |
| **Isolation Default** | Read Committed | Read Committed (no versioning) |
| **RCSI** | N/A (always MVCC) | Optional (enable READ_COMMITTED_SNAPSHOT) |
| **Snapshot Isolation** | Repeatable Read | Requires SNAPSHOT isolation level |

---

## 3. Executor Physical Operators

The PostgreSQL executor implements a **demand-pull pipeline** where each node produces tuples when requested by its parent.

### 3.1 Executor Architecture

```
Query Plan Tree (Bottom-Up Execution):

                    ┌─────────────┐
                    │   Client    │
                    └──────┬──────┘
                           │ Pull next row
                    ┌──────▼──────┐
                    │  Aggregate  │ ← Top node
                    └──────┬──────┘
                           │ Pull next row
                    ┌──────▼──────┐
                    │  Hash Join  │ ← Join node
                    └──────┬──────┘
                      ┌────┴────┐
            Pull      │         │      Pull
            ┌─────────▼───┐ ┌───▼─────────┐
            │  SeqScan    │ │  IndexScan  │ ← Scan nodes (leaves)
            │  (table1)   │ │  (table2)   │
            └─────────────┘ └─────────────┘
```

**Execution Model:**
```pseudocode
function execute_plan(plan_node):
    # Initialize node
    state = ExecInit(plan_node)

    # Pull tuples until exhausted
    while true:
        tuple = ExecProcNode(state)
        if tuple == NULL:
            break  # No more tuples

        send_to_client(tuple)

    # Cleanup
    ExecEnd(state)
```

---

### 3.2 SeqScan (Sequential Scan)

Sequential scan reads table pages from disk/buffer cache sequentially.

#### Algorithm Pseudocode

```pseudocode
function ExecSeqScan(scan_state):
    # Get current scan position
    tuple = scan_state.current_tuple

    # If no current tuple, fetch next
    if tuple == NULL:
        tuple = heap_getnext(scan_state.heap_scan)

    while tuple != NULL:
        # Check visibility
        if tuple_satisfies_snapshot(tuple, scan_state.snapshot):
            # Apply filter conditions (WHERE clause)
            if ExecQual(scan_state.qual, tuple):
                # Project attributes (SELECT list)
                result = ExecProject(scan_state.projection, tuple)

                # Save position for next call
                scan_state.current_tuple = tuple

                return result  # Return one tuple

        # Get next tuple
        tuple = heap_getnext(scan_state.heap_scan)

    return NULL  # No more tuples
```

#### Heap Scan Implementation

```pseudocode
function heap_getnext(heap_scan):
    while true:
        # If current page exhausted, read next page
        if scan.current_page_offset >= scan.current_page_tuples:
            # Get next page
            if scan.current_page == scan.end_page:
                return NULL  # Scan complete

            scan.current_page++
            page = buffer_read_page(scan.relation, scan.current_page)
            scan.current_page_tuples = get_tuple_count(page)
            scan.current_page_offset = 0

        # Get next tuple from current page
        item_id = scan.current_page_offset++
        line_pointer = get_line_pointer(page, item_id)

        if line_pointer.flags == LP_NORMAL:
            tuple = get_tuple(page, line_pointer.offset)
            return tuple
        # Skip dead/redirect line pointers

```

#### Example Execution

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT name, price FROM products WHERE price > 100;
```

```
Seq Scan on products  (cost=0.00..180.00 rows=500 width=20)
                      (actual time=0.025..2.345 rows=487 loops=1)
  Filter: (price > 100::numeric)
  Rows Removed by Filter: 513
  Buffers: shared hit=80
Planning Time: 0.112 ms
Execution Time: 2.567 ms
```

**Interpretation:**
- Scanned all 80 pages (80 * 8KB = 640 KB)
- Found 1000 rows total
- Filter removed 513 rows
- Returned 487 rows

**When Used:**
- No suitable index exists
- Returning large % of table (> 5-10%)
- Table is small
- Optimizer estimates SeqScan cheaper than IndexScan

---

### 3.3 IndexScan and IndexOnlyScan

#### IndexScan Algorithm

```pseudocode
function ExecIndexScan(index_scan_state):
    # Get next index tuple
    index_tuple = index_getnext(index_scan_state.index_scan)

    while index_tuple != NULL:
        # Extract heap tuple TID from index
        tid = index_tuple.t_tid

        # Fetch heap tuple (random I/O!)
        heap_tuple = heap_fetch(index_scan_state.heap_scan, tid)

        # Check visibility (index doesn't store visibility info)
        if tuple_satisfies_snapshot(heap_tuple, snapshot):
            # Apply filter conditions
            if ExecQual(index_scan_state.qual, heap_tuple):
                # Project result
                result = ExecProject(index_scan_state.projection, heap_tuple)
                return result

        # Get next index entry
        index_tuple = index_getnext(index_scan_state.index_scan)

    return NULL
```

#### IndexOnlyScan Algorithm (Optimization)

```pseudocode
function ExecIndexOnlyScan(index_scan_state):
    index_tuple = index_getnext(index_scan_state.index_scan)

    while index_tuple != NULL:
        tid = index_tuple.t_tid
        page_num = get_page_number(tid)

        # Check visibility map first
        if visibility_map_test(relation, page_num, VM_ALL_VISIBLE):
            # All tuples on page visible, skip heap fetch!
            result = ExecProject(index_scan_state.projection, index_tuple)
            return result
        else:
            # VM not set, must fetch heap tuple for visibility check
            heap_tuple = heap_fetch(index_scan_state.heap_scan, tid)

            if tuple_satisfies_snapshot(heap_tuple, snapshot):
                # Still use index data for projection
                result = ExecProject(index_scan_state.projection, index_tuple)
                return result

        index_tuple = index_getnext(index_scan_state.index_scan)

    return NULL
```

#### Example: IndexOnlyScan

```sql
CREATE INDEX idx_price ON products(price);
VACUUM products;  -- Set visibility map

EXPLAIN (ANALYZE, BUFFERS)
SELECT price FROM products WHERE price > 100;
```

```
Index Only Scan using idx_price on products  (cost=0.29..25.41 rows=487 width=6)
                                              (actual time=0.015..0.845 rows=487 loops=1)
  Index Cond: (price > 100::numeric)
  Heap Fetches: 0              ← No heap access!
  Buffers: shared hit=12       ← Only index + VM pages
Planning Time: 0.087 ms
Execution Time: 0.923 ms
```

**vs. Regular IndexScan (VM not set):**
```
Index Scan using idx_price on products  (cost=0.29..180.32 rows=487 width=6)
  Index Cond: (price > 100::numeric)
  Buffers: shared hit=12 (index) + 487 (heap) = 499
  Heap Fetches: 487            ← Random I/O for each row!
```

**Performance Gain:** ~50x fewer pages accessed

---

### 3.4 Nested Loop Join

#### Algorithm

```pseudocode
function ExecNestLoop(nl_state):
    outer_tuple = nl_state.current_outer_tuple

    # If no current outer tuple, get next
    if outer_tuple == NULL:
        outer_tuple = ExecProcNode(nl_state.outer_plan)
        if outer_tuple == NULL:
            return NULL  # Outer exhausted, join complete

        nl_state.current_outer_tuple = outer_tuple

        # Rescan inner for new outer tuple
        ExecReScan(nl_state.inner_plan)

    # Iterate through inner tuples
    while true:
        inner_tuple = ExecProcNode(nl_state.inner_plan)

        if inner_tuple == NULL:
            # Inner exhausted, get next outer
            outer_tuple = ExecProcNode(nl_state.outer_plan)

            if outer_tuple == NULL:
                return NULL  # Join complete

            nl_state.current_outer_tuple = outer_tuple
            ExecReScan(nl_state.inner_plan)
            continue

        # Test join condition
        if ExecQual(nl_state.join_qual, outer_tuple, inner_tuple):
            # Project result
            result = ExecProject(nl_state.projection, outer_tuple, inner_tuple)
            return result

```

#### Example with Index on Inner Table

```sql
EXPLAIN (ANALYZE)
SELECT c.name, o.order_date
FROM customers c
JOIN orders o ON c.id = o.customer_id
WHERE c.country = 'USA';
```

```
Nested Loop  (cost=0.29..523.45 rows=150 width=40)
  ->  Seq Scan on customers c  (cost=0.00..45.00 rows=50 width=20)
        Filter: (country = 'USA'::text)
  ->  Index Scan using idx_orders_customer_id on orders o  (cost=0.29..9.55 rows=3 width=24)
        Index Cond: (customer_id = c.id)

Execution:
  For each customer in USA (50 rows):
    Index scan orders using customer_id (avg 3 rows per customer)
  Total: 50 outer * 3 inner = 150 result rows

Cost: 50 outer scans + (50 * index scan cost)
```

**When Used:**
- Small outer table
- Index on inner table's join column
- OLTP queries (quick startup, early termination)
- One-to-many joins with selective outer

**Performance:**
- ✅ Best: Outer 100 rows, indexed inner
- ❌ Worst: Outer 1M rows, no index on inner → O(N*M) table scans!

---

### 3.5 Hash Join

#### Algorithm with Hash Table Building

```pseudocode
function ExecHashJoin(hj_state):
    # Phase 1: Build hash table from inner relation (once)
    if not hj_state.hash_table_built:
        hash_table = create_hash_table(hj_state.work_mem)

        # Build phase: Read all inner tuples
        while true:
            inner_tuple = ExecProcNode(hj_state.inner_plan)
            if inner_tuple == NULL:
                break

            # Extract join key
            join_key = ExecEvalExpr(hj_state.inner_hash_key, inner_tuple)
            hash_value = hash_function(join_key)

            # Insert into hash table
            if not hash_table_fits_in_memory(hash_table):
                # Hybrid hash: Spill batches to disk
                batch_num = hash_value % num_batches
                if batch_num == current_batch:
                    hash_table_insert(hash_table, hash_value, inner_tuple)
                else:
                    write_to_temp_file(batch_num, inner_tuple)
            else:
                hash_table_insert(hash_table, hash_value, inner_tuple)

        hj_state.hash_table_built = true

    # Phase 2: Probe phase - scan outer relation
    while true:
        outer_tuple = ExecProcNode(hj_state.outer_plan)

        if outer_tuple == NULL:
            # Current batch complete
            if more_batches_to_process():
                load_next_batch()
                ExecReScan(hj_state.outer_plan)
                continue
            else:
                return NULL  # Join complete

        # Probe hash table
        join_key = ExecEvalExpr(hj_state.outer_hash_key, outer_tuple)
        hash_value = hash_function(join_key)

        # Look up in hash table
        bucket = hash_table[hash_value % hash_table_size]

        for each inner_tuple in bucket:
            # Check join condition (handle hash collisions)
            if join_key == get_join_key(inner_tuple):
                if ExecQual(hj_state.join_qual, outer_tuple, inner_tuple):
                    result = ExecProject(hj_state.projection, outer_tuple, inner_tuple)
                    return result

```

#### Example Execution

```sql
SET work_mem = '64MB';

EXPLAIN (ANALYZE, BUFFERS)
SELECT p.name, c.category_name
FROM products p
JOIN categories c ON p.category_id = c.id;
```

```
Hash Join  (cost=25.00..380.00 rows=10000 width=40)
           (actual time=1.234..45.678 rows=10000 loops=1)
  Hash Cond: (p.category_id = c.id)
  Buffers: shared hit=250, temp read=0 written=0
  ->  Seq Scan on products p  (cost=0.00..180.00 rows=10000 width=24)
        Buffers: shared hit=180
  ->  Hash  (cost=15.00..15.00 rows=800 width=20)
            (actual time=1.123..1.123 rows=800 loops=1)
        Buckets: 1024  Batches: 1  Memory Usage: 45kB
        Buffers: shared hit=70
        ->  Seq Scan on categories c  (cost=0.00..15.00 rows=800 width=20)
              Buffers: shared hit=70

Execution breakdown:
  Build phase: Read 800 categories (1.123ms), build hash table (45 KB)
  Probe phase: Read 10000 products (44.555ms), probe hash table
  Total: 45.678ms
```

**Batching Example (Hash doesn't fit in work_mem):**
```
Hash Join  (cost=25.00..380.00 rows=10000 width=40)
  Hash Cond: (p.category_id = c.id)
  ->  Seq Scan on products p
  ->  Hash  (cost=15.00..15.00 rows=800 width=20)
        Buckets: 1024  Batches: 4  Memory Usage: 2048kB  ← Spilled to disk!

Execution:
  Batch 0: Build hash (subset), probe outer (subset), join
  Batch 1: Build hash (subset), probe outer (subset), join
  Batch 2: Build hash (subset), probe outer (subset), join
  Batch 3: Build hash (subset), probe outer (subset), join

Extra I/O: Write/read temp files for batches
```

**When Used:**
- Both tables moderately large
- No index on join columns
- Equijoin condition (hash requires `=`)
- Inner table fits in work_mem (or batching acceptable)

**Performance:**
- ✅ Best: Inner fits in memory, large outer → O(N + M)
- ❌ Worst: Many batches → Extra disk I/O

---

### 3.6 Merge Join

#### Algorithm

```pseudocode
function ExecMergeJoin(mj_state):
    # Ensure both inputs are sorted on join key
    # (Either by explicit Sort node or index scan in order)

    outer_tuple = mj_state.current_outer
    inner_tuple = mj_state.current_inner

    # Initialize if first call
    if outer_tuple == NULL:
        outer_tuple = ExecProcNode(mj_state.outer_plan)
    if inner_tuple == NULL:
        inner_tuple = ExecProcNode(mj_state.inner_plan)

    while outer_tuple != NULL and inner_tuple != NULL:
        outer_key = get_join_key(outer_tuple)
        inner_key = get_join_key(inner_tuple)

        compare = compare_keys(outer_key, inner_key)

        if compare < 0:
            # Outer < Inner: advance outer
            outer_tuple = ExecProcNode(mj_state.outer_plan)

        elif compare > 0:
            # Outer > Inner: advance inner
            inner_tuple = ExecProcNode(mj_state.inner_plan)

        else:
            # Keys match: handle duplicates
            # Mark position for potential backtracking
            mark_position(mj_state.inner_plan)

            # Return all matching pairs
            while outer_key == get_join_key(outer_tuple):
                # Scan inner for all matches
                while inner_key == get_join_key(inner_tuple):
                    if ExecQual(mj_state.join_qual, outer_tuple, inner_tuple):
                        result = ExecProject(mj_state.projection, outer_tuple, inner_tuple)

                        # Advance inner for next call
                        inner_tuple = ExecProcNode(mj_state.inner_plan)

                        # Save state
                        mj_state.current_outer = outer_tuple
                        mj_state.current_inner = inner_tuple

                        return result

                # Advance outer, rewind inner to mark
                outer_tuple = ExecProcNode(mj_state.outer_plan)
                rewind_to_mark(mj_state.inner_plan)
                inner_tuple = ExecProcNode(mj_state.inner_plan)

    return NULL  # No more matches
```

#### Example with Index Scans

```sql
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_customers_id ON customers(id);

EXPLAIN (ANALYZE)
SELECT c.name, o.order_date
FROM customers c
JOIN orders o ON c.id = o.customer_id
ORDER BY c.id;  -- Already in sorted order!
```

```
Merge Join  (cost=0.58..523.45 rows=10000 width=40)
            (actual time=0.025..45.123 rows=10000 loops=1)
  Merge Cond: (c.id = o.customer_id)
  ->  Index Scan using idx_customers_id on customers c  (cost=0.29..123.45 rows=5000 width=20)
  ->  Index Scan using idx_orders_customer on orders o  (cost=0.29..345.67 rows=10000 width=24)

Execution:
  Both inputs pre-sorted by index scans (no explicit Sort needed!)
  Merge algorithm walks through both sorted lists once
  Total: O(N + M) comparisons
```

**With Explicit Sorting:**
```
Merge Join  (cost=1234.56..2345.67 rows=10000 width=40)
  Merge Cond: (c.id = o.customer_id)
  ->  Sort  (cost=234.56..245.67 rows=5000 width=20)
        Sort Key: c.id
        ->  Seq Scan on customers c
  ->  Sort  (cost=890.12..912.34 rows=10000 width=24)
        Sort Key: o.customer_id
        ->  Seq Scan on orders o

Cost breakdown:
  Sort customers: 234.56
  Sort orders: 890.12
  Merge: 1220.99
  Total: 2345.67
```

**When Used:**
- Inputs already sorted (index scans)
- Sorting cost acceptable
- Equijoin on sorted columns
- Memory-efficient (streams data, no hash table)

**Performance:**
- ✅ Best: Pre-sorted inputs → O(N + M), no extra memory
- ❌ Worst: Must sort both inputs → O(N log N + M log M)

---

### 3.7 Aggregate Operators

#### Hash Aggregate

```pseudocode
function ExecHashAgg(agg_state):
    # Phase 1: Build hash table (GROUP BY keys → aggregate states)
    if not agg_state.table_built:
        hash_table = create_hash_table()

        while true:
            input_tuple = ExecProcNode(agg_state.outer_plan)
            if input_tuple == NULL:
                break

            # Extract GROUP BY keys
            group_key = ExecEvalExpr(agg_state.group_expr, input_tuple)
            hash_value = hash_function(group_key)

            # Look up or create aggregate state
            agg_entry = hash_table_lookup(hash_table, hash_value, group_key)

            if agg_entry == NULL:
                agg_entry = create_agg_entry(group_key)
                hash_table_insert(hash_table, hash_value, agg_entry)

            # Update aggregate state
            for each agg_function in agg_state.agg_functions:
                input_val = ExecEvalExpr(agg_function.input_expr, input_tuple)
                update_agg_state(agg_entry.agg_states[i], input_val)

        agg_state.table_built = true
        agg_state.iterator = hash_table_begin_scan(hash_table)

    # Phase 2: Return finalized aggregates
    agg_entry = hash_table_next(agg_state.iterator)

    if agg_entry == NULL:
        return NULL  # All groups returned

    # Finalize aggregates (e.g., COUNT/SUM → AVG)
    result = create_result_tuple()
    result.group_key = agg_entry.group_key

    for each agg_function in agg_state.agg_functions:
        agg_value = finalize_agg(agg_entry.agg_states[i], agg_function)
        result.agg_values[i] = agg_value

    return result
```

#### Example: Hash Aggregate

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT category_id, COUNT(*), AVG(price), MAX(price)
FROM products
GROUP BY category_id;
```

```
HashAggregate  (cost=230.00..235.00 rows=50 width=40)
               (actual time=12.345..12.567 rows=50 loops=1)
  Group Key: category_id
  Batches: 1  Memory Usage: 24kB
  Buffers: shared hit=180
  ->  Seq Scan on products  (cost=0.00..180.00 rows=10000 width=10)
        Buffers: shared hit=180

Execution:
  1. Scan 10000 products
  2. Build hash table: 50 groups (categories)
  3. For each row, update COUNT/SUM/MAX states
  4. Finalize aggregates (SUM/COUNT → AVG)
  5. Return 50 result rows
```

#### Group Aggregate (Sorted Input)

```pseudocode
function ExecGroupAgg(agg_state):
    while true:
        input_tuple = ExecProcNode(agg_state.outer_plan)

        if input_tuple != NULL:
            current_group = ExecEvalExpr(agg_state.group_expr, input_tuple)

        # Check if group changed or input exhausted
        if input_tuple == NULL or current_group != agg_state.previous_group:
            # Finalize previous group (if exists)
            if agg_state.agg_states != NULL:
                result = create_result_tuple()
                result.group_key = agg_state.previous_group

                for each agg_function:
                    result.agg_values[i] = finalize_agg(agg_state.agg_states[i])

                # Reset for new group
                reset_agg_states(agg_state.agg_states)
                agg_state.previous_group = current_group

                # Update new group with current tuple
                if input_tuple != NULL:
                    for each agg_function:
                        input_val = ExecEvalExpr(agg_function.input_expr, input_tuple)
                        update_agg_state(agg_state.agg_states[i], input_val)

                return result

            if input_tuple == NULL:
                return NULL  # Complete

        # Same group, update aggregates
        for each agg_function:
            input_val = ExecEvalExpr(agg_function.input_expr, input_tuple)
            update_agg_state(agg_state.agg_states[i], input_val)
```

#### Example: Group Aggregate

```sql
CREATE INDEX idx_products_category ON products(category_id);

EXPLAIN (ANALYZE)
SELECT category_id, COUNT(*), AVG(price)
FROM products
GROUP BY category_id;
```

```
GroupAggregate  (cost=0.29..456.78 rows=50 width=20)
                (actual time=0.025..23.456 rows=50 loops=1)
  Group Key: category_id
  ->  Index Scan using idx_products_category on products  (cost=0.29..380.00 rows=10000 width=10)

Execution:
  1. Index scan returns rows sorted by category_id
  2. Group aggregate processes in order:
     category_id=1: COUNT/SUM rows 1-200
     category_id=2: COUNT/SUM rows 201-400
     ...
     category_id=50: COUNT/SUM rows 9801-10000
  3. No hash table needed!
```

**HashAggregate vs. GroupAggregate:**

| Factor | HashAggregate | GroupAggregate |
|--------|---------------|----------------|
| Input requirement | Unsorted | Must be sorted |
| Memory usage | O(# groups) | O(1) |
| Typical use | Many groups, unsorted | Few groups or pre-sorted |
| Performance | Faster for small # groups | Faster when pre-sorted |
| Disk usage | May spill to temp files | None |

---

### SQL Server Comparison: Executor Operators

| Operator | PostgreSQL | SQL Server |
|----------|------------|------------|
| **SeqScan** | Heap scan, no order | Table Scan or Clustered Index Scan |
| **IndexScan** | B-tree index + heap lookup | Nonclustered Index Seek + Key Lookup |
| **IndexOnlyScan** | Uses Visibility Map | Covered Index (no VM needed) |
| **Nested Loop** | Same algorithm | Same algorithm |
| **Hash Join** | Hybrid hash join | Same (also hybrid) |
| **Merge Join** | Requires sorted input | Same (often with sort) |
| **Hash Aggregate** | In-memory, may spill | Same (Stream Aggregate for sorted) |
| **Group Aggregate** | Requires sorted input | Stream Aggregate |

**Key Differences:**
1. **PostgreSQL IndexOnlyScan** requires VM to be set (VACUUM) vs. **SQL Server Covered Index** works immediately
2. **PostgreSQL SeqScan** on heap vs. **SQL Server** usually scans clustered index (inherent order)
3. **PostgreSQL** visibility checks in executor vs. **SQL Server** no MVCC overhead (simpler)

---

**End of Part 1**

This document covered:
1. ✅ Storage Layer (Page structure, Tuple structure, TOAST, FSM, VM, Heap organization)
2. ✅ MVCC Implementation (Snapshots, XID management, Visibility rules, HOT updates)
3. ✅ Executor Physical Operators (SeqScan, IndexScan, Joins, Aggregates with pseudocode)

Continue to Part 2 for:
- VACUUM System
- Buffer Management
- Scenario-Based Interview Questions
