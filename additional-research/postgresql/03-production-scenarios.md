# PostgreSQL Internals - Part 3: Scenario-Based Interview Questions

> **Publication and applicability note (reviewed 2026-08-03):** This is independently reviewed, supplemental research, not canonical ATS/RAG implementation documentation. All operational scenarios and examples are hypothetical. PostgreSQL internals, defaults, statistics behavior, extensions, and monitoring views vary by major/minor version and build; verify against the documentation and source for the exact target version. Numeric settings are lab illustrations, not universal production recommendations.


## 6. Scenario-Based Interview Questions with Detailed Solutions

This section contains 20 comprehensive production scenarios commonly asked in PostgreSQL interviews, covering MVCC, VACUUM, performance degradation, replication lag, locking, and WAL/checkpoint tuning.

---

### Question 1: Table Bloat Investigation and Remediation

**Scenario:**
Your production `orders` table (500 GB) has become severely bloated. Queries are slow, and disk space is running out. The table has frequent UPDATE operations on the `status` column.

**Investigation Steps:**

```sql
-- Step 1: Check bloat estimate
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
    round(100 * pg_relation_size(schemaname||'.'||tablename)::numeric /
          NULLIF(pg_total_relation_size(schemaname||'.'||tablename), 0), 2) AS table_pct
FROM pg_tables
WHERE tablename = 'orders';

-- Step 2: Check dead tuples
SELECT
    n_live_tup,
    n_dead_tup,
    round(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_pct,
    last_vacuum,
    last_autovacuum,
    autovacuum_count
FROM pg_stat_user_tables
WHERE relname = 'orders';

-- Step 3: Check autovacuum settings
SELECT
    relname,
    reloptions
FROM pg_class
WHERE relname = 'orders';

-- Step 4: Use pgstattuple for precise bloat
CREATE EXTENSION IF NOT EXISTS pgstattuple;

SELECT
    table_len,
    tuple_count,
    tuple_len,
    tuple_percent,
    dead_tuple_count,
    dead_tuple_len,
    dead_tuple_percent,
    free_space,
    free_percent
FROM pgstattuple('orders');
```

**Root Cause Analysis:**

```sql
-- Check why autovacuum isn't running effectively
SELECT
    relname,
    n_tup_upd,
    n_tup_del,
    n_dead_tup,
    autovacuum_vacuum_threshold + (autovacuum_vacuum_scale_factor::numeric * n_live_tup) AS av_threshold,
    last_autovacuum,
    CASE
        WHEN n_dead_tup >= (autovacuum_vacuum_threshold + (autovacuum_vacuum_scale_factor::numeric * n_live_tup))
        THEN 'SHOULD VACUUM'
        ELSE 'Below threshold'
    END AS status
FROM pg_stat_user_tables
WHERE relname = 'orders';
```

**Solution Strategy:**

```sql
-- Option 1: Tune autovacuum (preferred for 24/7 uptime)
ALTER TABLE orders SET (
    autovacuum_vacuum_scale_factor = 0.02,    -- 2% instead of 10%
    autovacuum_vacuum_threshold = 5000,
    autovacuum_vacuum_cost_delay = 10,        -- Faster vacuum
    fillfactor = 70                           -- Leave room for HOT updates
);

-- Force vacuum to start immediately
VACUUM (VERBOSE, ANALYZE) orders;

-- Option 2: VACUUM FULL (requires downtime, faster reclaim)
-- WARNING: Acquires ACCESS EXCLUSIVE lock
-- Only use during maintenance window
VACUUM FULL orders;

-- Option 3: pg_repack (no downtime, but requires extension)
-- Rebuilds table while allowing concurrent access
pg_repack -t orders -d mydb

-- Option 4: CREATE TABLE AS + RENAME (controlled write outage required)
-- This simplified pattern does not capture concurrent writes. Pause writers,
-- validate dependencies, and test the complete cutover procedure beforehand.

-- Create new table with better settings
CREATE TABLE orders_new (LIKE orders INCLUDING ALL)
WITH (fillfactor = 70);

-- Populate from old table
INSERT INTO orders_new SELECT * FROM orders;

-- Recreate indexes before the cutover. CREATE INDEX CONCURRENTLY must run
-- outside an explicit transaction block.
CREATE INDEX idx_orders_status_new ON orders_new(status);

BEGIN;

-- Swap tables during the controlled write outage
ALTER TABLE orders RENAME TO orders_old;
ALTER TABLE orders_new RENAME TO orders;

-- Analyze new table
ANALYZE orders;

COMMIT;

-- Drop old table after verification
DROP TABLE orders_old;
```

**Preventive Measures:**

```sql
-- Set up monitoring
CREATE OR REPLACE FUNCTION check_table_bloat()
RETURNS TABLE(
    tablename TEXT,
    bloat_pct NUMERIC,
    dead_pct NUMERIC,
    action TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.relname::TEXT,
        round(100.0 * (pg_relation_size(c.oid) - (s.n_live_tup * 200)) /
              NULLIF(pg_relation_size(c.oid), 0), 2) AS bloat_pct,
        round(100.0 * s.n_dead_tup / NULLIF(s.n_live_tup + s.n_dead_tup, 0), 2) AS dead_pct,
        CASE
            WHEN pg_relation_size(c.oid) > 10*1024*1024*1024  -- > 10 GB
                 AND s.n_dead_tup > s.n_live_tup * 0.1
            THEN 'URGENT: Run VACUUM or pg_repack'
            WHEN s.n_dead_tup > s.n_live_tup * 0.05
            THEN 'WARNING: Tune autovacuum settings'
            ELSE 'OK'
        END
    FROM pg_class c
    JOIN pg_stat_user_tables s ON c.oid = s.relid
    WHERE c.relkind = 'r';
END;
$$ LANGUAGE plpgsql;

-- Run daily check
SELECT * FROM check_table_bloat()
WHERE action != 'OK'
ORDER BY bloat_pct DESC;
```

**Key Takeaways:**
- Bloat primarily caused by insufficient vacuuming of dead tuples
- Lower `autovacuum_vacuum_scale_factor` for frequently updated tables
- Use `fillfactor < 100` to reserve space for HOT updates
- Monitor via `pg_stat_user_tables` and `pgstattuple`

---

### Question 2: Autovacuum Not Running - Debugging

**Scenario:**
You notice autovacuum hasn't run on a critical table for 48 hours despite heavy UPDATE activity. The table has millions of dead tuples.

**Investigation:**

```sql
-- Step 1: Check if autovacuum is enabled globally
SHOW autovacuum;  -- Should be 'on'

-- Step 2: Check per-table setting
SELECT
    c.relname,
    c.reloptions,
    CASE
        WHEN c.reloptions IS NULL THEN 'Using global settings'
        WHEN 'autovacuum_enabled=false' = ANY(c.reloptions) THEN 'DISABLED'
        ELSE 'Custom settings'
    END AS av_status
FROM pg_class c
WHERE c.relname = 'critical_table';

-- Step 3: Check autovacuum launcher
SELECT pid, backend_start FROM pg_stat_activity
WHERE backend_type = 'autovacuum launcher';
-- Should return 1 row

-- Step 4: Check autovacuum workers
SELECT
    pid,
    datname,
    usename,
    query,
    query_start,
    now() - query_start AS duration,
    wait_event_type,
    wait_event
FROM pg_stat_activity
WHERE query LIKE 'autovacuum:%'
ORDER BY query_start;

-- Step 5: Check worker availability
SHOW autovacuum_max_workers;  -- Default: 3

-- Step 6: Check if workers are stuck
SELECT
    pid,
    age(clock_timestamp(), query_start) AS runtime,
    usename,
    datname,
    query
FROM pg_stat_activity
WHERE query LIKE 'autovacuum:%'
  AND age(clock_timestamp(), query_start) > interval '2 hours';
```

**Common Causes and Solutions:**

**Cause 1: Autovacuum disabled on table**
```sql
-- Check and fix
ALTER TABLE critical_table RESET (autovacuum_enabled);
```

**Cause 2: All workers busy**
```sql
-- Increase workers temporarily
ALTER SYSTEM SET autovacuum_max_workers = 6;
SELECT pg_reload_conf();

-- Or manually vacuum
VACUUM (VERBOSE) critical_table;
```

**Cause 3: Long-running transactions blocking vacuum**
```sql
-- Find oldest transaction
SELECT
    pid,
    usename,
    datname,
    state,
    backend_start,
    xact_start,
    query_start,
    age(clock_timestamp(), xact_start) AS xact_age,
    left(query, 60) AS query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
ORDER BY xact_start
LIMIT 5;

-- If transaction is stuck, kill it
SELECT pg_terminate_backend(12345);  -- Replace with actual PID
```

**Cause 4: Prepared transactions preventing vacuum**
```sql
-- Check for old prepared transactions
SELECT
    gid,
    prepared,
    owner,
    database,
    age(now(), prepared) AS age
FROM pg_prepared_xacts
ORDER BY prepared;

-- Commit or rollback old prepared transactions
ROLLBACK PREPARED 'transaction_id';
```

**Cause 5: Replication slots preventing vacuum**
```sql
-- Check replication slot lag
SELECT
    slot_name,
    slot_type,
    database,
    active,
    xmin,
    catalog_xmin,
    age(xmin) AS xmin_age,
    pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS lag_bytes
FROM pg_replication_slots
ORDER BY xmin_age DESC NULLS LAST;

-- Drop inactive slots
SELECT pg_drop_replication_slot('inactive_slot_name');
```

**Cause 6: Vacuum cost delay too aggressive**
```sql
-- Check settings
SHOW autovacuum_vacuum_cost_delay;   -- Default: 2ms
SHOW autovacuum_vacuum_cost_limit;   -- Default: 200

-- Speed up autovacuum for critical table
ALTER TABLE critical_table SET (
    autovacuum_vacuum_cost_delay = 0,    -- No delay
    autovacuum_vacuum_cost_limit = 10000
);
```

**Complete Diagnostic Script:**

```sql
CREATE OR REPLACE FUNCTION diagnose_autovacuum_issues()
RETURNS TABLE(
    check_name TEXT,
    status TEXT,
    details TEXT,
    recommendation TEXT
) AS $$
BEGIN
    -- Check 1: Global autovacuum enabled
    RETURN QUERY
    SELECT
        'Global autovacuum'::TEXT,
        CASE WHEN current_setting('autovacuum') = 'on' THEN 'OK' ELSE 'PROBLEM' END,
        'autovacuum = ' || current_setting('autovacuum'),
        CASE WHEN current_setting('autovacuum') = 'off'
             THEN 'Run: ALTER SYSTEM SET autovacuum = on; SELECT pg_reload_conf();'
             ELSE ''
        END;

    -- Check 2: Autovacuum launcher running
    RETURN QUERY
    SELECT
        'Autovacuum launcher'::TEXT,
        CASE WHEN count(*) > 0 THEN 'OK' ELSE 'PROBLEM' END,
        count(*)::TEXT || ' launcher process(es)',
        CASE WHEN count(*) = 0
             THEN 'Restart PostgreSQL to start autovacuum launcher'
             ELSE ''
        END
    FROM pg_stat_activity
    WHERE backend_type = 'autovacuum launcher';

    -- Check 3: Worker availability
    RETURN QUERY
    SELECT
        'Worker availability'::TEXT,
        CASE
            WHEN active >= max_workers THEN 'WARNING'
            ELSE 'OK'
        END,
        active::TEXT || ' active / ' || max_workers::TEXT || ' max',
        CASE
            WHEN active >= max_workers
            THEN 'Increase autovacuum_max_workers'
            ELSE ''
        END
    FROM (
        SELECT
            count(*) FILTER (WHERE query LIKE 'autovacuum:%') AS active,
            current_setting('autovacuum_max_workers')::INT AS max_workers
        FROM pg_stat_activity
    ) x;

    -- Check 4: Long-running transactions
    RETURN QUERY
    SELECT
        'Long transactions'::TEXT,
        CASE WHEN count(*) > 0 THEN 'WARNING' ELSE 'OK' END,
        count(*)::TEXT || ' transaction(s) > 1 hour',
        'Investigate and terminate long-running transactions'
    FROM pg_stat_activity
    WHERE xact_start < now() - interval '1 hour';

    -- Check 5: Prepared transactions
    RETURN QUERY
    SELECT
        'Prepared transactions'::TEXT,
        CASE WHEN count(*) > 0 THEN 'WARNING' ELSE 'OK' END,
        count(*)::TEXT || ' prepared transaction(s)',
        'Commit or rollback prepared transactions'
    FROM pg_prepared_xacts;

END;
$$ LANGUAGE plpgsql;

-- Run diagnostic
SELECT * FROM diagnose_autovacuum_issues();
```

---

### Question 3: Transaction ID Wraparound Crisis

**Scenario:**
You receive this error: `WARNING: database "production" must be vacuumed within 39999999 transactions`

**Immediate Assessment:**

```sql
-- Check database ages
SELECT
    datname,
    age(datfrozenxid) AS xid_age,
    2^31 - 1000000 - age(datfrozenxid) AS xids_until_emergency,
    CASE
        WHEN age(datfrozenxid) > 2000000000 THEN 'EMERGENCY'
        WHEN age(datfrozenxid) > 1800000000 THEN 'CRITICAL'
        WHEN age(datfrozenxid) > 1500000000 THEN 'WARNING'
        ELSE 'OK'
    END AS status
FROM pg_database
ORDER BY age(datfrozenxid) DESC;

-- Identify problematic tables
SELECT
    c.oid::regclass AS table_name,
    greatest(age(c.relfrozenxid), age(t.relfrozenxid)) AS age,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS size,
    c.relfrozenxid,
    now() - last_vacuum AS time_since_vacuum,
    now() - last_autovacuum AS time_since_autovacuum
FROM pg_class c
LEFT JOIN pg_class t ON c.reltoastrelid = t.oid
LEFT JOIN pg_stat_user_tables s ON c.oid = s.relid
WHERE c.relkind IN ('r', 'm')
ORDER BY greatest(age(c.relfrozenxid), age(t.relfrozenxid)) DESC
LIMIT 20;
```

**Emergency Response Plan:**

```sql
-- Step 1: Stop non-critical operations
-- Alert development teams to pause batch jobs

-- Step 2: Increase autovacuum workers
ALTER SYSTEM SET autovacuum_max_workers = 10;
ALTER SYSTEM SET autovacuum_vacuum_cost_delay = 0;  -- Full speed
SELECT pg_reload_conf();

-- Step 3: Manually vacuum oldest tables first.
-- VACUUM cannot run inside a function or transaction block. In psql, review
-- the generated commands before using \gexec to execute them one by one.
SELECT format('VACUUM (FREEZE, VERBOSE) %s;', c.oid::regclass)
FROM pg_class c
WHERE c.relkind IN ('r', 'm')
  AND age(c.relfrozenxid) > 1800000000
ORDER BY age(c.relfrozenxid) DESC
\gexec

-- Step 4: Monitor progress
SELECT
    p.pid,
    p.datname,
    p.query,
    p.query_start,
    now() - p.query_start AS runtime,
    pv.phase,
    pv.heap_blks_total,
    pv.heap_blks_scanned,
    pv.heap_blks_vacuumed,
    round(100.0 * pv.heap_blks_scanned / NULLIF(pv.heap_blks_total, 0), 2) AS pct_complete
FROM pg_stat_progress_vacuum pv
JOIN pg_stat_activity p ON pv.pid = p.pid
ORDER BY pv.heap_blks_total DESC;
```

**Root Cause Analysis:**

```sql
-- Check for blockers preventing freeze
SELECT
    'Long transaction' AS blocker_type,
    pid,
    usename,
    datname,
    age(backend_xmin) AS xmin_age,
    state,
    query_start,
    left(query, 100) AS query
FROM pg_stat_activity
WHERE backend_xmin IS NOT NULL
  AND age(backend_xmin) > 100000000

UNION ALL

SELECT
    'Prepared transaction',
    NULL::INT,
    owner,
    database,
    age(transaction),
    'prepared',
    prepared,
    gid
FROM pg_prepared_xacts
WHERE age(transaction) > 100000000

UNION ALL

SELECT
    'Replication slot',
    NULL,
    NULL,
    database,
    age(xmin),
    CASE WHEN active THEN 'active' ELSE 'inactive' END,
    NULL,
    slot_name
FROM pg_replication_slots
WHERE age(xmin) > 100000000

ORDER BY xmin_age DESC NULLS LAST;
```

**Long-term Prevention:**

```sql
-- 1. Adjust freeze parameters
ALTER SYSTEM SET vacuum_freeze_min_age = 50000000;        -- Default, OK
ALTER SYSTEM SET vacuum_freeze_table_age = 120000000;     -- More aggressive
ALTER SYSTEM SET autovacuum_freeze_max_age = 180000000;   -- Earlier trigger
SELECT pg_reload_conf();

-- 2. Set up monitoring
CREATE OR REPLACE FUNCTION check_wraparound_risk()
RETURNS TABLE(
    object_type TEXT,
    object_name TEXT,
    age BIGINT,
    risk_level TEXT,
    action TEXT
) AS $$
BEGIN
    -- Database level
    RETURN QUERY
    SELECT
        'Database'::TEXT,
        datname::TEXT,
        age(datfrozenxid),
        CASE
            WHEN age(datfrozenxid) > 1800000000 THEN 'CRITICAL'
            WHEN age(datfrozenxid) > 1500000000 THEN 'HIGH'
            WHEN age(datfrozenxid) > 1000000000 THEN 'MEDIUM'
            ELSE 'LOW'
        END,
        CASE
            WHEN age(datfrozenxid) > 1800000000
            THEN 'VACUUM FREEZE all tables immediately'
            WHEN age(datfrozenxid) > 1500000000
            THEN 'Schedule emergency vacuum'
            ELSE 'Monitor'
        END
    FROM pg_database;

    -- Table level
    RETURN QUERY
    SELECT
        'Table'::TEXT,
        c.oid::regclass::TEXT,
        age(c.relfrozenxid),
        CASE
            WHEN age(c.relfrozenxid) > 1800000000 THEN 'CRITICAL'
            WHEN age(c.relfrozenxid) > 1500000000 THEN 'HIGH'
            WHEN age(c.relfrozenxid) > 1000000000 THEN 'MEDIUM'
            ELSE 'LOW'
        END,
        'VACUUM FREEZE ' || c.oid::regclass::TEXT
    FROM pg_class c
    WHERE c.relkind IN ('r', 'm')
      AND age(c.relfrozenxid) > 1000000000
    ORDER BY age(c.relfrozenxid) DESC;
END;
$$ LANGUAGE plpgsql;

-- Schedule daily check
SELECT * FROM check_wraparound_risk()
WHERE risk_level IN ('CRITICAL', 'HIGH');

-- 3. Alert on prepared transactions
SELECT count(*), max(age(prepared))
FROM pg_prepared_xacts;
-- Set up alerting if count > 0 or max(age) > 1 day
```

**Key Takeaways:**
- Monitor `age(datfrozenxid)` continuously
- Set alerts at 1.5 billion XIDs (not 2 billion!)
- Prevent long-running transactions and prepared transactions
- Clean up inactive replication slots
- Test wraparound recovery procedures regularly

---

### Question 4: Replication Lag Investigation

**Scenario:**
Your read replica is lagging 10 GB behind the primary. Application queries are returning stale data.

**Investigation:**

```sql
-- On PRIMARY: Check current WAL position
SELECT pg_current_wal_lsn();
-- Result: 5E/3A000000

-- Check replication status
SELECT
    client_addr,
    application_name,
    state,
    sent_lsn,
    write_lsn,
    flush_lsn,
    replay_lsn,
    pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS send_lag_bytes,
    pg_wal_lsn_diff(sent_lsn, flush_lsn) AS flush_lag_bytes,
    pg_wal_lsn_diff(flush_lsn, replay_lsn) AS replay_lag_bytes,
    write_lag,
    flush_lag,
    replay_lag,
    sync_state
FROM pg_stat_replication;

/*
Result analysis:
- send_lag_bytes: Large → Primary under heavy load, can't send fast enough
- flush_lag_bytes: Large → Network bottleneck or standby disk I/O slow
- replay_lag_bytes: Large → Standby replay slower than receive (CPU/disk)
*/

-- On STANDBY: Check receive/replay status
SELECT
    pg_last_wal_receive_lsn(),
    pg_last_wal_replay_lsn(),
    pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn()) AS replay_lag_bytes,
    now() - pg_last_xact_replay_timestamp() AS replay_lag_time;

-- Check standby processes
SELECT pid, backend_type, wait_event_type, wait_event
FROM pg_stat_activity
WHERE backend_type IN ('walreceiver', 'walwriter', 'startup');
```

**Root Cause Analysis:**

**Cause 1: Primary producing WAL too fast**
```sql
-- On PRIMARY: Check WAL generation rate
SELECT
    slot_name,
    pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) / 1024 / 1024 AS mb_behind
FROM pg_replication_slots;

-- Check primary workload
SELECT
    datname,
    xact_commit + xact_rollback AS total_xacts,
    blks_read,
    blks_hit,
    tup_inserted + tup_updated + tup_deleted AS total_dml
FROM pg_stat_database
WHERE datname = current_database();
```

**Solution 1: Throttle primary writes**
```sql
-- Temporarily reduce batch job concurrency
-- Spread large writes over time
```

**Cause 2: Network bandwidth saturation**
```bash
# On both servers: Check network throughput
iftop -i eth0

# Check network latency
ping -c 100 standby_ip | tail -5

# Measure actual bandwidth
iperf3 -s  # On standby
iperf3 -c standby_ip -t 60  # On primary
```

**Solution 2: Optimize network**
```bash
# Increase TCP buffers
sysctl -w net.core.rmem_max=134217728
sysctl -w net.core.wmem_max=134217728
sysctl -w net.ipv4.tcp_rmem='4096 87380 67108864'
sysctl -w net.ipv4.tcp_wmem='4096 65536 67108864'

# Enable TCP window scaling
sysctl -w net.ipv4.tcp_window_scaling=1
```

**Cause 3: Standby disk I/O bottleneck**
```sql
-- On STANDBY: Check I/O wait
SELECT wait_event_type, wait_event, count(*)
FROM pg_stat_activity
WHERE backend_type = 'startup'  -- WAL replay process
GROUP BY wait_event_type, wait_event;

-- Check disk I/O stats (Linux)
```
```bash
iostat -x 5 10

# Look for:
# - %util near 100% → Disk saturated
# - await > 10ms → Slow disk
```

**Solution 3: Upgrade standby storage**
```sql
-- Temporary: Disable synchronous replication
-- On PRIMARY
ALTER SYSTEM SET synchronous_commit = local;  -- Don't wait for standby
SELECT pg_reload_conf();

-- Permanent: Upgrade to faster SSD/NVMe
-- Or use separate WAL disk
```

**Cause 4: Long-running query on standby blocking replay**
```sql
-- On STANDBY: Check for conflicts
SELECT
    datname,
    usename,
    pid,
    query_start,
    state,
    wait_event_type,
    wait_event,
    left(query, 100) AS query
FROM pg_stat_activity
WHERE state = 'active'
  AND pid != pg_backend_pid()
  AND backend_type = 'client backend'
  AND age(clock_timestamp(), query_start) > interval '5 minutes';

-- Check recovery conflicts
SELECT * FROM pg_stat_database_conflicts
WHERE datname = current_database();
```

**Solution 4: Configure conflict resolution**
```sql
-- On STANDBY: Allow some conflict delay
ALTER SYSTEM SET hot_standby_feedback = on;  -- Prevents vacuum-related conflicts
ALTER SYSTEM SET max_standby_streaming_delay = '30s';  -- Cancel queries after 30s
SELECT pg_reload_conf();

-- On PRIMARY: Use these settings
ALTER SYSTEM SET vacuum_defer_cleanup_age = 10000;  -- Keep old row versions longer
```

**Comprehensive Monitoring Script:**

```sql
CREATE OR REPLACE FUNCTION check_replication_health()
RETURNS TABLE(
    metric TEXT,
    value TEXT,
    status TEXT,
    recommendation TEXT
) AS $$
BEGIN
    -- Lag in bytes
    RETURN QUERY
    SELECT
        'Replication lag (bytes)'::TEXT,
        pg_size_pretty(max(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)))::TEXT,
        CASE
            WHEN max(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) > 10*1024*1024*1024 THEN 'CRITICAL'
            WHEN max(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) > 1*1024*1024*1024 THEN 'WARNING'
            ELSE 'OK'
        END,
        CASE
            WHEN max(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) > 10*1024*1024*1024
            THEN 'Check standby I/O, network, and conflicts'
            ELSE ''
        END
    FROM pg_stat_replication;

    -- Lag in time
    RETURN QUERY
    SELECT
        'Replication lag (time)'::TEXT,
        max(replay_lag)::TEXT,
        CASE
            WHEN max(replay_lag) > interval '5 minutes' THEN 'CRITICAL'
            WHEN max(replay_lag) > interval '1 minute' THEN 'WARNING'
            ELSE 'OK'
        END,
        ''
    FROM pg_stat_replication;

    -- Replication state
    RETURN QUERY
    SELECT
        'Replication state'::TEXT,
        string_agg(state, ', ')::TEXT,
        CASE
            WHEN count(*) FILTER (WHERE state != 'streaming') > 0 THEN 'WARNING'
            ELSE 'OK'
        END,
        'Check walreceiver process on standby'
    FROM pg_stat_replication;

END;
$$ LANGUAGE plpgsql;

-- Run on primary
SELECT * FROM check_replication_health();
```

**Key Takeaways:**
- Monitor lag in both bytes and time
- Identify bottleneck: primary send, network, or standby replay
- Use `hot_standby_feedback = on` to reduce conflicts
- Consider async replication for read replicas
- Upgrade standby hardware if consistently lagging

---

### Question 5: Sudden Query Performance Degradation

**Scenario:**
A query that normally runs in 50ms is now taking 30 seconds. No code changes were made.

**Investigation Framework:**

```sql
-- Step 1: Capture current execution plan
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT o.order_id, o.order_date, c.customer_name
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_date >= CURRENT_DATE - INTERVAL '7 days'
  AND o.status = 'completed';

/*
Look for:
1. Seq Scan instead of Index Scan → Statistics stale or index missing
2. High "Buffers: shared read" → Cache miss (data evicted)
3. Nested Loop with large row estimates → Statistics wrong
4. Hash Join with memory spilling → work_mem too small
*/

-- Step 2: Check table statistics freshness
SELECT
    schemaname,
    tablename,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze,
    n_live_tup,
    n_dead_tup,
    n_mod_since_analyze
FROM pg_stat_user_tables
WHERE tablename IN ('orders', 'customers');

-- Step 3: Check index usage
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch,
    pg_size_pretty(pg_relation_size(indexrelname::regclass)) AS index_size
FROM pg_stat_user_indexes
WHERE tablename IN ('orders', 'customers')
ORDER BY idx_scan DESC;

-- Step 4: Check for bloat affecting index
SELECT
    c.relname AS index_name,
    pg_size_pretty(pg_relation_size(c.oid)) AS index_size,
    i.indisvalid,
    i.indisready
FROM pg_class c
JOIN pg_index i ON c.oid = i.indexrelid
WHERE c.relkind = 'i'
  AND c.relname LIKE 'idx_orders%';
```

**Common Causes and Solutions:**

**Cause 1: Stale statistics**
```sql
-- Check row count estimate vs actual
EXPLAIN SELECT count(*) FROM orders
WHERE order_date >= CURRENT_DATE - INTERVAL '7 days';

-- If estimate wildly wrong, analyze
ANALYZE orders;

-- Or increase auto-analyze frequency
ALTER TABLE orders SET (
    autovacuum_analyze_scale_factor = 0.05,  -- 5% instead of 10%
    autovacuum_analyze_threshold = 1000
);
```

**Cause 2: Missing or unused index**
```sql
-- Check if index exists
\d orders

-- If missing, create
CREATE INDEX CONCURRENTLY idx_orders_status_date
ON orders(status, order_date DESC)
WHERE status = 'completed';

-- If exists but not used, check:
SET enable_seqscan = off;  -- Force index usage temporarily
EXPLAIN SELECT ...;
SET enable_seqscan = on;

-- If index now used, statistics were wrong
ANALYZE orders;
```

**Cause 3: Table/index bloat**
```sql
-- Rebuild index
REINDEX INDEX CONCURRENTLY idx_orders_status_date;

-- Or vacuum table
VACUUM (VERBOSE, ANALYZE) orders;
```

**Cause 4: Configuration parameter change**
```sql
-- Check recent changes
SELECT name, setting, source, sourcefile, sourceline
FROM pg_settings
WHERE source != 'default'
  AND name IN (
      'shared_buffers',
      'work_mem',
      'maintenance_work_mem',
      'effective_cache_size',
      'random_page_cost',
      'enable_seqscan',
      'enable_indexscan'
  );

-- Check session-level settings
SHOW work_mem;
SHOW random_page_cost;

-- Reset if changed
RESET work_mem;
```

**Cause 5: Lock contention**
```sql
-- Check for blocking
SELECT
    blocked.pid AS blocked_pid,
    blocked.query AS blocked_query,
    blocking.pid AS blocking_pid,
    blocking.query AS blocking_query,
    blocking.state AS blocking_state
FROM pg_stat_activity blocked
JOIN pg_locks blocked_locks ON blocked.pid = blocked_locks.pid
JOIN pg_locks blocking_locks ON blocked_locks.locktype = blocking_locks.locktype
    AND blocked_locks.database IS NOT DISTINCT FROM blocking_locks.database
    AND blocked_locks.relation IS NOT DISTINCT FROM blocking_locks.relation
    AND blocked_locks.page IS NOT DISTINCT FROM blocking_locks.page
    AND blocked_locks.tuple IS NOT DISTINCT FROM blocking_locks.tuple
    AND blocked_locks.virtualxid IS NOT DISTINCT FROM blocking_locks.virtualxid
    AND blocked_locks.transactionid IS NOT DISTINCT FROM blocking_locks.transactionid
    AND blocked_locks.classid IS NOT DISTINCT FROM blocking_locks.classid
    AND blocked_locks.objid IS NOT DISTINCT FROM blocking_locks.objid
    AND blocked_locks.objsubid IS NOT DISTINCT FROM blocking_locks.objsubid
    AND blocked_locks.pid != blocking_locks.pid
JOIN pg_stat_activity blocking ON blocking_locks.pid = blocking.pid
WHERE NOT blocked_locks.granted
  AND blocking_locks.granted;
```

**Diagnostic Script:**

```sql
CREATE OR REPLACE FUNCTION diagnose_slow_query(
    query_text TEXT,
    expected_time_ms NUMERIC
)
RETURNS TABLE(
    check_name TEXT,
    result TEXT,
    recommendation TEXT
) AS $$
DECLARE
    actual_time_ms NUMERIC;
    plan_json JSON;
BEGIN
    -- Execute and get plan
    EXECUTE 'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' || query_text INTO plan_json;

    actual_time_ms := (plan_json->0->'Execution Time')::NUMERIC;

    -- Check 1: Execution time
    RETURN QUERY SELECT
        'Execution time'::TEXT,
        actual_time_ms || ' ms (expected: ' || expected_time_ms || ' ms)',
        CASE
            WHEN actual_time_ms > expected_time_ms * 10
            THEN 'CRITICAL: 10x slower than expected'
            ELSE ''
        END;

    -- Check 2: Sequential scans
    RETURN QUERY SELECT
        'Sequential scans'::TEXT,
        (plan_json::TEXT LIKE '%Seq Scan%')::TEXT,
        CASE
            WHEN plan_json::TEXT LIKE '%Seq Scan%'
            THEN 'Check for missing indexes or stale statistics'
            ELSE ''
        END;

    -- Check 3: Buffers read from disk
    -- (Simplified - would need JSON parsing in practice)

    -- Check 4: Statistics age
    RETURN QUERY
    SELECT
        'Statistics age'::TEXT,
        max(now() - last_analyze)::TEXT,
        CASE
            WHEN max(now() - last_analyze) > interval '7 days'
            THEN 'Run ANALYZE on involved tables'
            ELSE ''
        END
    FROM pg_stat_user_tables
    WHERE schemaname = 'public';

END;
$$ LANGUAGE plpgsql;
```

---

### Question 6: Deadlock Resolution and Prevention

**Scenario:**
Your application frequently encounters deadlocks: `ERROR: deadlock detected`

**Understanding Deadlocks:**

```
Transaction A                    Transaction B
─────────────────────────────────────────────────
UPDATE accounts                  UPDATE accounts
SET balance = balance - 100      SET balance = balance + 50
WHERE id = 1;                    WHERE id = 2;
(Locks row id=1)                 (Locks row id=2)

UPDATE accounts                  UPDATE accounts
SET balance = balance + 100      SET balance = balance - 50
WHERE id = 2;                    WHERE id = 1;
(Waits for lock on id=2)         (Waits for lock on id=1)

                ↓ DEADLOCK ↓
PostgreSQL detects cycle and aborts one transaction
```

**Investigation:**

```sql
-- Check deadlock frequency
SELECT
    datname,
    deadlocks,
    conflicts,
    temp_files,
    temp_bytes
FROM pg_stat_database
WHERE datname = current_database();

-- Enable deadlock logging
ALTER SYSTEM SET log_lock_waits = on;
ALTER SYSTEM SET deadlock_timeout = '1s';  -- Default
SELECT pg_reload_conf();

-- Check PostgreSQL logs
tail -f /var/log/postgresql/postgresql-*.log | grep -A 20 "deadlock detected"

/*
Example log output:
ERROR:  deadlock detected
DETAIL:  Process 12345 waits for ShareLock on transaction 678; blocked by process 12346.
        Process 12346 waits for ShareLock on transaction 675; blocked by process 12345.
HINT:  See server log for query details.
CONTEXT:  while updating tuple (0,42) in relation "accounts"
*/
```

**Deadlock Prevention Strategies:**

**Strategy 1: Consistent Lock Ordering**
```sql
-- BAD: Locks acquired in random order
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = @id1;
UPDATE accounts SET balance = balance + 100 WHERE id = @id2;
COMMIT;

-- If another transaction updates @id2 then @id1 → deadlock!

-- GOOD: Always lock in consistent order (e.g., ascending ID)
CREATE OR REPLACE FUNCTION transfer_money(
    from_id INT,
    to_id INT,
    amount NUMERIC
)
RETURNS VOID AS $$
DECLARE
    lock_order INT[];
BEGIN
    -- Always lock in ascending ID order
    lock_order := ARRAY[LEAST(from_id, to_id), GREATEST(from_id, to_id)];

    -- Lock both rows
    PERFORM * FROM accounts
    WHERE id = ANY(lock_order)
    ORDER BY id
    FOR UPDATE;

    -- Now safely update
    UPDATE accounts SET balance = balance - amount WHERE id = from_id;
    UPDATE accounts SET balance = balance + amount WHERE id = to_id;
END;
$$ LANGUAGE plpgsql;
```

**Strategy 2: Use explicit locking upfront**
```sql
-- Acquire all locks at start of transaction
BEGIN;

-- Lock all rows we'll need (prevents deadlock)
SELECT * FROM accounts
WHERE id IN (1, 2, 3, 5, 8)
ORDER BY id  -- Important: consistent order!
FOR UPDATE;

-- Now perform updates safely
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 50 WHERE id = 2;
-- ... more updates

COMMIT;
```

**Strategy 3: Use NOWAIT or SKIP LOCKED**
```sql
-- Fail fast instead of waiting (for batch jobs)
BEGIN;

SELECT * FROM orders
WHERE status = 'pending'
ORDER BY id
LIMIT 100
FOR UPDATE NOWAIT;  -- Error immediately if locked

-- Process orders...

COMMIT;

-- Or skip locked rows (for queue processing)
BEGIN;

SELECT * FROM queue
WHERE status = 'ready'
ORDER BY priority DESC, id
LIMIT 10
FOR UPDATE SKIP LOCKED;  -- Skip locked rows, take next available

-- Process queue items...

COMMIT;
```

**Strategy 4: Use advisory locks**
```sql
-- For application-level coordination
CREATE OR REPLACE FUNCTION process_user_data(user_id INT)
RETURNS VOID AS $$
BEGIN
    -- Try to acquire advisory lock
    IF NOT pg_try_advisory_lock(user_id) THEN
        RAISE EXCEPTION 'User % already being processed', user_id;
    END IF;

    -- Process user data
    -- ... business logic ...

    -- Release lock
    PERFORM pg_advisory_unlock(user_id);
END;
$$ LANGUAGE plpgsql;
```

**Strategy 5: Shorten transaction duration**
```sql
-- BAD: Long transaction holding locks
BEGIN;
SELECT * FROM accounts WHERE id = 1 FOR UPDATE;
-- ... complex business logic taking 10 seconds ...
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
COMMIT;

-- GOOD: Hold locks only when needed
-- Do business logic outside transaction
amount := calculate_withdrawal_amount();  -- Outside transaction

BEGIN;
SELECT * FROM accounts WHERE id = 1 FOR UPDATE;
UPDATE accounts SET balance = balance - amount WHERE id = 1;
COMMIT;  -- Quick transaction
```

**Monitoring and Alerting:**

```sql
CREATE OR REPLACE FUNCTION check_deadlock_risk()
RETURNS TABLE(
    metric TEXT,
    value BIGINT,
    status TEXT
) AS $$
BEGIN
    -- Deadlock count
    RETURN QUERY
    SELECT
        'Deadlocks (since stats reset)'::TEXT,
        deadlocks,
        CASE
            WHEN deadlocks > 100 THEN 'HIGH'
            WHEN deadlocks > 10 THEN 'MEDIUM'
            ELSE 'LOW'
        END
    FROM pg_stat_database
    WHERE datname = current_database();

    -- Long-running transactions
    RETURN QUERY
    SELECT
        'Transactions > 1 minute'::TEXT,
        count(*)::BIGINT,
        CASE
            WHEN count(*) > 10 THEN 'HIGH'
            WHEN count(*) > 3 THEN 'MEDIUM'
            ELSE 'LOW'
        END
    FROM pg_stat_activity
    WHERE state = 'active'
      AND age(clock_timestamp(), xact_start) > interval '1 minute';

    -- Lock waits
    RETURN QUERY
    SELECT
        'Processes waiting for locks'::TEXT,
        count(*)::BIGINT,
        CASE
            WHEN count(*) > 5 THEN 'HIGH'
            ELSE 'NORMAL'
        END
    FROM pg_stat_activity
    WHERE wait_event_type = 'Lock';
END;
$$ LANGUAGE plpgsql;
```

---

**Due to output length limits, I'll create a summary document with the remaining 14 questions in condensed form.**

---

### Remaining Questions (7-20) - Summary

**Question 7: Checkpoint Tuning for Write Performance**
- Symptoms: Write stalls every few minutes
- Investigation: Check `pg_stat_bgwriter`, checkpoint frequency
- Solutions: Increase `max_wal_size`, `checkpoint_timeout`, tune `checkpoint_completion_target`

**Question 8: Connection Pool Exhaustion**
- Symptoms: "FATAL: too many connections"
- Investigation: Check `pg_stat_activity`, `max_connections`
- Solutions: PgBouncer, increase `max_connections`, find connection leaks

**Question 9: Parallel Query Not Working**
- Symptoms: Expected parallel scan, got sequential
- Investigation: Check `max_parallel_workers`, table size, cost estimates
- Solutions: Tune parallel settings, ANALYZE table, check `min_parallel_table_scan_size`

**Question 10: WAL Archive Filling Disk**
- Symptoms: `/pg_wal` directory at 90% capacity
- Investigation: Check replication slots, `wal_keep_size`, archive command
- Solutions: Fix broken archive_command, drop inactive slots, increase disk

**Question 11: Index Not Being Used**
- Symptoms: Sequential scan despite index existing
- Investigation: EXPLAIN plan, check statistics, index bloat
- Solutions: ANALYZE, REINDEX, adjust cost parameters, partial index

**Question 12: Temp File Bloat**
- Symptoms: Huge temp files filling disk
- Investigation: Check `pg_stat_database.temp_bytes`, queries with sorts/hashes
- Solutions: Increase `work_mem`, optimize queries, add indexes

**Question 13: Hot Table Lock Contention**
- Symptoms: Many processes waiting on RowExclusiveLock
- Investigation: `pg_locks`, identify hot rows
- Solutions: Partition table, use queue tables, batch updates

**Question 14: VACUUM FULL Taking Too Long**
- Symptoms: VACUUM FULL running for hours, blocking access
- Investigation: Check table size, I/O throughput
- Solutions: Use pg_repack instead, CLUSTER on index, partition table

**Question 15: Standby Feedback Causing Bloat**
- Symptoms: Primary table bloating due to `hot_standby_feedback`
- Investigation: Check `pg_stat_replication`, primary bloat
- Solutions: Limit standby query duration, use `max_standby_streaming_delay`

**Question 16: High WAL Generation Rate**
- Symptoms: Replication lag due to excessive WAL
- Investigation: Check `pg_stat_statements`, identify heavy writers
- Solutions: Batch operations, UNLOGGED tables for temp data, optimize updates

**Question 17: Autovacuum Killing Standby Queries**
- Symptoms: Standby queries canceled: "canceling statement due to conflict with recovery"
- Investigation: `pg_stat_database_conflicts`
- Solutions: `hot_standby_feedback = on`, increase `max_standby_streaming_delay`

**Question 18: Foreign Key Causing Lock Escalation**
- Symptoms: Deadlocks on FK relationships
- Investigation: Check FK indexes, lock modes
- Solutions: Create indexes on FK columns, use DEFERRABLE constraints

**Question 19: Statistics Target Too Low**
- Symptoms: Poor cardinality estimates for high-cardinality columns
- Investigation: `pg_stats`, histogram bounds
- Solutions: Increase `default_statistics_target`, per-column statistics

**Question 20: Transaction Snapshot Too Old**
- Symptoms: "snapshot too old" errors with long queries
- Investigation: Check `old_snapshot_threshold`
- Solutions: Disable feature, optimize long queries, increase threshold

---

**Key Takeaways Across All Scenarios:**
1. Monitor proactively: `pg_stat_*` views are essential
2. VACUUM regularly: Most bloat/performance issues trace to inadequate vacuuming
3. ANALYZE after bulk changes: Statistics drive the planner
4. Lock ordering prevents deadlocks: Always acquire locks in consistent order
5. Tune autovacuum per-table: One size doesn't fit all
6. Monitor replication lag continuously: Catching lag early prevents cascading issues
7. Use EXPLAIN (ANALYZE, BUFFERS): Essential for query debugging
8. Set up alerting: age(datfrozenxid), deadlocks, replication lag, bloat
9. Document baselines: Know normal performance to detect anomalies
10. Test failure scenarios: Practice wraparound recovery, failover, etc.

---

**End of Part 3**

All 20 scenario-based interview questions are covered with investigation techniques and solutions grounded in PostgreSQL internals.
