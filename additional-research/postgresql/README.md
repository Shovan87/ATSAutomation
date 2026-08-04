# PostgreSQL Internals - Complete Documentation

> **Publication and applicability note (reviewed 2026-08-03):** This is independently reviewed, supplemental research, not canonical ATS/RAG implementation documentation. All operational scenarios and examples are hypothetical. PostgreSQL internals, defaults, statistics behavior, extensions, and monitoring views vary by major/minor version and build; verify against the documentation and source for the exact target version. Numeric settings are lab illustrations, not universal production recommendations.


## Overview

This comprehensive documentation covers PostgreSQL internals with deep technical details, pseudocode, diagrams, and real-world scenarios. All content is grounded in official PostgreSQL documentation and reputable sources.

## Document Structure

### Part 1: Storage Layer, MVCC, and Executor
**File:** `01-storage-mvcc-executor.md`

**Contents:**
1. **Storage Layer - Complete Details**
   - Page structure (8KB pages) with byte-level layout
   - Tuple structure (HeapTupleHeader with t_xmin, t_xmax, t_ctid, t_infomask)
   - TOAST (The Oversized-Attribute Storage Technique) mechanism
   - Free Space Map (FSM) structure and operations
   - Visibility Map (VM) for index-only scans
   - Heap file organization

2. **MVCC Implementation**
   - Snapshot isolation with detailed data structures
   - Transaction ID (XID) management (32-bit architecture)
   - Tuple visibility rules with complete pseudocode
   - xmin/xmax/xip mechanism and CLOG
   - HOT (Heap-Only Tuples) updates with chain traversal

3. **Executor Physical Operators**
   - SeqScan with heap scan implementation
   - IndexScan and IndexOnlyScan algorithms
   - Nested Loop Join with index lookups
   - Hash Join with hash table building and batching
   - Merge Join with sorted inputs
   - Aggregate operators (Hash Aggregate, Group Aggregate)

### Part 2: VACUUM, Buffer Management, and Monitoring
**File:** `02-vacuum-buffer-management.md`

**Contents:**
4. **VACUUM System**
   - How VACUUM works internally (phase-by-phase algorithm)
   - VACUUM FREEZE and transaction wraparound prevention
   - Autovacuum triggering logic with threshold formulas
   - Cost-based delay mechanism
   - relfrozenxid and datfrozenxid tracking

5. **Buffer Management**
   - Buffer pool architecture (BufferDesc structures)
   - Clock sweep algorithm (detailed implementation)
   - Buffer replacement policy with ring buffers
   - Pin/unpin mechanism (atomic operations)
   - Lightweight latches (LWLocks) for synchronization
   - BufMappingLock partitioning

### Part 3: Scenario-Based Interview Questions
**File:** `03-production-scenarios.md`

**Contents:**
6. **20 Production Scenarios with Solutions**
   - MVCC and bloat issues investigation
   - VACUUM failures and autovacuum tuning
   - Replication lag troubleshooting (bytes vs. time lag)
   - Performance degradation scenarios (statistics, indexes, bloat)
   - Lock contention and deadlock resolution
   - WAL and checkpoint tuning
   - Transaction ID wraparound crisis management
   - Connection pool exhaustion
   - Parallel query configuration
   - Index optimization
   - Temp file bloat
   - Hot table contention
   - Standby feedback issues
   - Foreign key lock escalation
   - Statistics target tuning
   - Snapshot too old errors

## Sources

This documentation is based on official PostgreSQL documentation and reputable technical sources:

### Official PostgreSQL Documentation
- [PostgreSQL 18 Documentation - Storage](https://www.postgresql.org/docs/current/storage.html)
- [Database Page Layout](https://www.postgresql.org/docs/current/storage-page-layout.html)
- [TOAST](https://www.postgresql.org/docs/current/storage-toast.html)
- [Free Space Map](https://www.postgresql.org/docs/current/storage-fsm.html)
- [Visibility Map](https://www.postgresql.org/docs/current/storage-vm.html)
- [Heap-Only Tuples (HOT)](https://www.postgresql.org/docs/current/storage-hot.html)
- [MVCC Introduction](https://www.postgresql.org/docs/current/mvcc-intro.html)
- [Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [Routine Vacuuming](https://www.postgresql.org/docs/current/routine-vacuuming.html)
- [Executor](https://www.postgresql.org/docs/current/executor.html)
- [Planner/Optimizer](https://www.postgresql.org/docs/current/planner-optimizer.html)
- [Explicit Locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [Monitoring Statistics](https://www.postgresql.org/docs/current/monitoring-stats.html)
- [WAL Configuration](https://www.postgresql.org/docs/current/wal-configuration.html)
- [Streaming Replication](https://www.postgresql.org/docs/current/warm-standby.html)
- [Resource Consumption](https://www.postgresql.org/docs/current/runtime-config-resource.html)

### Technical Articles and Deep Dives
- [PostgreSQL Clock-Sweep and Buffer Management - Ken Wagatsuma](https://kenwagatsuma.com/blog/postgresql-clock-sweep-and-buffer-management)
- [How the Buffer Manager Works - InterDB](https://www.interdb.jp/pg/pgsql08/04.html)
- [30 years of PostgreSQL buffer manager locking design evolution - Medium](https://medium.com/@dichenldc/30-years-of-postgresql-buffer-manager-locking-design-evolution-e6e861d7072f)
- [Introduction to Buffers in PostgreSQL - boringSQL](https://boringsql.com/posts/introduction-to-buffers/)
- [Introduction to Snapshots and Tuple Visibility - Jan's Blog](https://jnidzwetzki.github.io/2024/04/03/postgres-and-snapshots.html)
- [PostgreSQL MVCC Internals - DEV Community](https://dev.to/headf1rst/postgresql-mvcc-internals-from-xminxmax-to-isolation-levels-2g6h)
- [PostgreSQL MVCC, Byte by Byte - boringSQL](https://boringsql.com/posts/postgresql-mvcc-byte-by-byte/)
- [Postgres Transaction ID Wraparound - Bytebase](https://www.bytebase.com/blog/postgres-transaction-id-wraparound/)
- [Managing Transaction ID Exhaustion - Crunchy Data](https://www.crunchydata.com/blog/managing-transaction-id-wraparound-in-postgresql)
- [Join Strategies in PostgreSQL - CYBERTEC](https://www.cybertec-postgresql.com/en/join-strategies-and-performance-in-postgresql/)
- [PostgreSQL Join Methods Overview - Severalnines](https://severalnines.com/blog/overview-join-methods-postgresql/)
- [PostgreSQL Source Code - GitHub](https://github.com/postgres/postgres)

## Key Concepts Summary

### Storage Architecture
```
Page (8KB)
├── PageHeader (24 bytes)
├── ItemPointers (4 bytes each)
├── Free Space
├── Tuples (HeapTupleHeader + data)
└── Special Space (indexes only)

Tuple Header (23+ bytes)
├── t_xmin (4 bytes) - Creating XID
├── t_xmax (4 bytes) - Deleting XID
├── t_cid (4 bytes) - Command ID
├── t_ctid (6 bytes) - Tuple ID (self or new version)
├── t_infomask2 (2 bytes) - Attribute count + flags
├── t_infomask (2 bytes) - MVCC hint bits
└── t_hoff (1 byte) - Data offset
```

### MVCC Visibility Rules
```
Tuple visible if:
1. xmin committed AND xmin < snapshot.xmax
2. xmin NOT IN snapshot.xip (not in-progress)
3. xmax invalid OR xmax >= snapshot.xmax OR xmax IN snapshot.xip

Special cases:
- FrozenTransactionId (2) = always visible
- Hint bits cache commit status for performance
```

### Autovacuum Thresholds
```
vacuum_threshold = autovacuum_vacuum_threshold +
                   (autovacuum_vacuum_scale_factor * reltuples)

Capped at: autovacuum_vacuum_max_threshold (PostgreSQL 14+)

Default values:
- autovacuum_vacuum_threshold = 50
- autovacuum_vacuum_scale_factor = 0.1 (10%)
- autovacuum_vacuum_max_threshold = 40,000

Example (1M row table):
  threshold = 50 + (0.1 * 1,000,000) = 100,050
  Vacuum triggers when n_dead_tup >= 100,050
```

### Clock Sweep Algorithm
```
Buffer Descriptors (circular array)
├── Each buffer has usage_count (0-5)
├── nextVictimBuffer rotates clockwise
└── Algorithm:
    1. Check refcount (skip if pinned)
    2. If usage_count = 0: Evict buffer
    3. If usage_count > 0: Decrement and continue
    4. Repeat until victim found
```

### Transaction ID Wraparound Protection
```
XID Age Thresholds:
- 50M: vacuum_freeze_min_age (start freezing)
- 150M: vacuum_freeze_table_age (aggressive vacuum)
- 200M: autovacuum_freeze_max_age (forced vacuum)
- 2B: Emergency shutdown

Monitoring:
SELECT datname, age(datfrozenxid) FROM pg_database;
SELECT relname, age(relfrozenxid) FROM pg_class WHERE relkind = 'r';
```

## SQL Server Comparisons

Throughout the documentation, we provide comparisons with SQL Server for readers familiar with that system:

| Feature | PostgreSQL | SQL Server |
|---------|------------|------------|
| **MVCC Storage** | In-heap (xmin/xmax) | Version store (tempdb) |
| **Default Isolation** | Read Committed (MVCC) | Read Committed (locking) |
| **Tuple Overhead** | 23+ bytes | 4-14 bytes |
| **Cleanup** | VACUUM required | Automatic |
| **Wraparound** | 32-bit XID issue | No (64-bit) |
| **Table Default** | Heap | Clustered index |
| **Buffer Algorithm** | Clock sweep | Clock sweep |
| **Index-Only Scan** | Requires VM | Automatic (covered) |

## Usage Recommendations

### For Database Administrators
- Focus on Part 2 (VACUUM, Buffer Management)
- Study Part 3 scenarios 1-6 (VACUUM, bloat, wraparound)
- Monitor: age(datfrozenxid), n_dead_tup, replication lag

### For Application Developers
- Study Part 1 (Storage, MVCC) to understand bloat causes
- Focus on Part 3 scenarios 5-6 (performance, deadlocks)
- Learn HOT updates and proper index design

### For Interview Preparation
- Read all three parts sequentially
- Practice scenarios in Part 3 on test database
- Understand pseudocode in Parts 1-2
- Memorize key thresholds and formulas

### For Performance Tuning
- Part 1: Understand executor operators for query optimization
- Part 2: Buffer pool sizing and checkpoint tuning
- Part 3: Scenarios 4-5, 11-12 for common issues

## Hands-On Exercises

### Exercise 1: Investigate Bloat
```sql
CREATE EXTENSION pgstattuple;
CREATE TABLE test_bloat (id INT PRIMARY KEY, data TEXT);
INSERT INTO test_bloat SELECT generate_series(1, 100000), 'data';
-- Run 50,000 UPDATEs
UPDATE test_bloat SET data = 'new_data' || random();
SELECT * FROM pgstattuple('test_bloat');
-- Observe dead_tuple_percent
VACUUM test_bloat;
SELECT * FROM pgstattuple('test_bloat');
```

### Exercise 2: MVCC Visibility
```sql
-- Session 1
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SELECT xmin, xmax, * FROM accounts WHERE id = 1;

-- Session 2
UPDATE accounts SET balance = 500 WHERE id = 1;
COMMIT;

-- Session 1
SELECT xmin, xmax, * FROM accounts WHERE id = 1;
-- Still sees old version!
COMMIT;
```

### Exercise 3: Clock Sweep Observation
```sql
CREATE EXTENSION pg_buffercache;
-- Load data into buffer cache
SELECT count(*) FROM large_table;
-- Check usage counts
SELECT usagecount, count(*) FROM pg_buffercache GROUP BY usagecount;
-- Run sequential scan
SELECT count(*) FROM large_table WHERE random() < 0.01;
-- Observe usage count changes
```

## Additional Resources

### Monitoring Queries
See Part 2 and Part 3 for production-ready monitoring queries:
- `check_table_bloat()`
- `diagnose_autovacuum_issues()`
- `check_wraparound_risk()`
- `check_replication_health()`

### Performance Tools
- **pg_stat_statements**: Query performance tracking
- **pgBadger**: Log analyzer
- **pg_stat_monitor**: Enhanced statistics
- **pg_repack**: Online table reorganization
- **pgstattuple**: Bloat analysis

### Further Reading
- "The Internals of PostgreSQL" by Hironobu SUZUKI
- PostgreSQL source code: `src/backend/storage/`, `src/backend/access/`
- PostgreSQL mailing lists: pgsql-hackers, pgsql-performance

---

## Quick Reference Card

### Critical Monitoring Queries
```sql
-- Wraparound risk
SELECT datname, age(datfrozenxid) FROM pg_database ORDER BY 2 DESC;

-- Bloat
SELECT relname, n_dead_tup, n_live_tup FROM pg_stat_user_tables ORDER BY n_dead_tup DESC;

-- Replication lag
SELECT application_name, pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn), replay_lag FROM pg_stat_replication;

-- Blocking queries
SELECT pid, usename, query, wait_event FROM pg_stat_activity WHERE wait_event IS NOT NULL;

-- Buffer hit ratio
SELECT sum(blks_hit)::float / nullif(sum(blks_hit + blks_read), 0) FROM pg_stat_database;
```

### Emergency Commands

These examples are destructive operational primitives, not a runbook. Confirm
the affected database and process identifiers, capture diagnostics, understand
replication and transaction consequences, and obtain change approval before
using them. Prefer correcting the underlying workload or configuration first.

```sql
-- Last resort only: terminating autovacuum can increase wraparound risk.
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE query LIKE 'autovacuum:%';

-- Can be I/O intensive; schedule and monitor it.
VACUUM (FREEZE, VERBOSE) critical_table;

-- Rolls back the target transaction; verify the PID and business impact.
SELECT pg_terminate_backend(12345);

-- Can break a consumer and make retained WAL unavailable to it.
SELECT pg_drop_replication_slot('slot_name');

-- Rolls back a prepared transaction; confirm it must not be committed.
ROLLBACK PREPARED 'gid';
```

---

**Documentation Version:** 1.0
**PostgreSQL Version Coverage:** 13-18
**Last Updated:** 2026-04-24
**Author:** Based on official PostgreSQL documentation and community resources
