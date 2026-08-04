# SQL Server L3/L4 DBA Interview Questions

> **Publication and applicability note (reviewed 2026-08-03):** This is independently reviewed, supplemental research, not canonical ATS/RAG implementation documentation. All scenarios, organizations, accounts, paths, workloads, and incidents are hypothetical. SQL Server/Azure SQL features, DMVs, permissions, defaults, and tooling vary by edition, compatibility level, cumulative update, and service tier; validate every command in a non-production environment first. Numeric settings are illustrative, not universal tuning values.

## 100 Scenario-Based Questions on AlwaysOn & Performance Tuning

**Prepared for:** Senior Database Administrator Positions (L3/L4)
**Focus Areas:** SQL Server AlwaysOn Availability Groups & Performance Tuning
**Date:** March 2026

---

## Table of Contents
1. [AlwaysOn Availability Groups (Questions 1-35)](#section-1-alwayson-availability-groups)
2. [Performance Tuning & Query Optimization (Questions 36-65)](#section-2-performance-tuning--query-optimization)
3. [Wait Statistics, Blocking & Deadlocks (Questions 66-85)](#section-3-wait-statistics-blocking--deadlocks)
4. [Indexing & Execution Plans (Questions 86-100)](#section-4-indexing--execution-plans)

---

## Section 1: AlwaysOn Availability Groups

### Q1: Your production AlwaysOn AG experienced an automatic failover at 3 AM. The secondary replica shows "NOT SYNCHRONIZING" status. How would you troubleshoot this?

**Answer:**
1. **Check Error Logs:**
   - Review SQL Server ERRORLOG on both primary and secondary
   - Check Windows Event Log for clustering events
   - Examine AlwaysOn Health XE session: `SELECT * FROM sys.fn_xe_file_target_read_file('AlwaysOn*.xel', NULL, NULL, NULL)`

   **🔍 What to Look For in Error Logs:**
   ```sql
   -- Common AG error numbers and their meanings:
   -- Error 35202: "A connection timeout has occurred on a previously established connection"
   --              → Network connectivity issue between replicas
   -- Error 35206: "A connection timeout has occurred while attempting to establish a connection"
   --              → Initial connection failure (firewall/endpoint issue)
   -- Error 1480:  "The AG database is changing roles because the AG failover"
   --              → Expected during failover, confirms role change occurred
   -- Error 35264: "Data movement on database suspended/resumed"
   --              → Database was manually suspended or auto-suspended due to error
   -- Error 41131: "Failed to bring availability group online"
   --              → WSFC cluster problem or quorum loss
   -- Error 19421: "Session timeout occurred - no acknowledgement from partner"
   --              → Secondary replica not responding (crash, network, or overload)

   -- Parse Extended Events for detailed troubleshooting:
   SELECT
       event_data.value('(event/@name)[1]', 'varchar(50)') AS event_name,
       event_data.value('(event/@timestamp)[1]', 'datetime2') AS event_time,
       event_data.value('(event/data[@name="error_number"]/value)[1]', 'int') AS error_number,
       event_data.value('(event/data[@name="message"]/value)[1]', 'varchar(max)') AS error_message,
       event_data.value('(event/data[@name="availability_group_name"]/value)[1]', 'varchar(100)') AS ag_name
   FROM (
       SELECT CAST(event_data AS XML) AS event_data
       FROM sys.fn_xe_file_target_read_file('AlwaysOn*.xel', NULL, NULL, NULL)
   ) AS events
   WHERE event_data.value('(event/@timestamp)[1]', 'datetime2') >= DATEADD(HOUR, -1, GETDATE())
     AND event_data.value('(event/@name)[1]', 'varchar(50)') IN (
         'error_reported',
         'availability_replica_state_change',
         'availability_replica_automatic_failover_validation'
     )
   ORDER BY event_time DESC

   -- Key patterns indicating specific problems:
   -- "The lease between availability replica 'X' and WSFC has expired"
   --   → Lease timeout (default 20 seconds) - replica considered failed
   --   → Check: Server CPU 100%, I/O stalls, network latency spikes

   -- "Database 'X' is waiting for physical database page allocations to be rolled back"
   --   → Long recovery due to large uncommitted transactions
   --   → Solution: Enable Accelerated Database Recovery (ADR)

   -- "Always On: The availability replica manager is going offline"
   --   → Replica shutting down (planned or crash)
   --   → Check: Windows event log for service stop reason
   ```

2. **Verify Synchronization State:**
   ```sql
   SELECT
       ar.replica_server_name,
       db.database_name,
       dr.synchronization_state_desc,
       dr.synchronization_health_desc,
       dr.last_hardened_lsn,
       dr.last_commit_time,
       dr.is_suspended,
       dr.suspend_reason_desc,
       DATEDIFF(SECOND, dr.last_commit_time, GETDATE()) AS seconds_since_last_commit
   FROM sys.dm_hadr_database_replica_states dr
   INNER JOIN sys.availability_replicas ar ON dr.replica_id = ar.replica_id
   INNER JOIN sys.databases db ON dr.database_id = db.database_id
   WHERE db.name = 'YourDatabaseName'
   ```

   **🔍 Interpreting Synchronization State:**
   ```
   synchronization_state_desc - What each value means:

   ❌ NOT SYNCHRONIZING (Your current problem!)
      Causes:
      - is_suspended = 1 (check suspend_reason_desc)
      - Network disconnection between replicas
      - Redo thread crash on secondary
      - Transaction log full on primary
      Action Required:
      - If suspended: Review suspend_reason_desc
        • SUSPEND_FROM_REDO: Redo thread encountered error
        • SUSPEND_FROM_CAPTURE: Log capture thread error
        • SUSPEND_FROM_APPLY: Apply thread error on secondary
      - Check: log_send_queue_size and redo_queue_size (should be 0 if truly stuck)

   ⚠️ SYNCHRONIZING
      Meaning: Actively replicating but may be behind
      Acceptable when:
      - Brief spikes during heavy transaction load
      - After failover (catching up)
      Concerning when:
      - Persistent for > 5 minutes
      - log_send_queue or redo_queue growing
      Action: Monitor queue sizes (see Q2 for lag analysis)

   ✅ SYNCHRONIZED
      Meaning: Fully caught up, zero lag
      Target state for: SYNCHRONOUS_COMMIT replicas
      Acceptable lag: < 1 second for synchronous

   🔄 REVERTING
      Meaning: Database going offline (transient state)
      Duration: Usually < 30 seconds
      Occurs during: Failover, role change, AG removal

   🔄 INITIALIZING
      Meaning: Database being added/seeded to AG
      Duration: Depends on database size
      Occurs during: Automatic/manual seeding

   synchronization_health_desc - Overall health:

   ❌ NOT_HEALTHY
      Impact: Data loss possible if failover occurs
      Threshold: Any database in NOT_SYNCHRONIZING state
      Action: Immediate resolution required

   ⚠️ PARTIALLY_HEALTHY
      Impact: Some databases at risk
      Meaning: Mixed state (some SYNCHRONIZED, some NOT)
      Action: Investigate unhealthy databases

   ✅ HEALTHY
      Impact: Replica health matches the configured synchronization mode
      Meaning: Synchronous replicas should be synchronized; asynchronous
               replicas can be healthy while still having send/redo lag
      Warning: HEALTHY asynchronous replicas do not guarantee zero data loss

   last_commit_time interpretation:
   - NULL or > 5 minutes old: ❌ Replication completely broken
   - 1-5 minutes old: ⚠️ Severe lag, investigate immediately
   - 10-60 seconds old: ⚠️ Concerning lag, monitor closely
   - < 10 seconds old: ✅ Acceptable for asynchronous mode
   - < 1 second old: ✅ Excellent for synchronous mode
   ```

3. **Check Network Connectivity:**
   ```sql
   SELECT
       ar.replica_server_name,
       ar.endpoint_url,
       ars.role_desc,
       ars.connected_state_desc,
       ars.last_connect_error_number,
       ars.last_connect_error_description,
       ars.last_connect_error_timestamp
   FROM sys.dm_hadr_availability_replica_states ars
   INNER JOIN sys.availability_replicas ar ON ars.replica_id = ar.replica_id
   ```

   **🔍 Network Connectivity Analysis:**
   ```
   connected_state_desc values:

   ✅ CONNECTED
      Good: Replica communicating normally
      Verify: last_connect_error_timestamp should be NULL or old

   ❌ DISCONNECTED
      Problem: No connection between replicas
      Common causes:
      - Firewall blocking port 5022 (default endpoint)
      - Replica server down/crashed
      - Network outage
      - Endpoint authentication failure
      Immediate action:
      1. Ping replica server
      2. Test-NetConnection to port 5022
      3. Check endpoint: SELECT * FROM sys.database_mirroring_endpoints

   last_connect_error_number interpretation:
   - 35201: Connection attempt timeout
     → Network too slow, increase SESSION_TIMEOUT
   - 35202: Established connection timeout
     → Network intermittent, check for packet loss
   - 1418: Server not responding
     → Replica crashed or network completely down
   - 15581: Certificate-based authentication failed
     → Certificate issue, verify endpoint security

   Test endpoint connectivity:
   - Verify firewall: Test-NetConnection -ComputerName SecondaryServer -Port 5022
   - Check endpoint status:
     SELECT name, state_desc, is_encryption_enabled
     FROM sys.database_mirroring_endpoints
     → state_desc should be STARTED
   ```

4. **Check Suspension Status:**
   ```sql
   SELECT
       db.name AS database_name,
       dr.is_suspended,
       dr.suspend_reason_desc,
       dr.log_send_queue_size / 1024.0 AS log_send_queue_mb,
       dr.redo_queue_size / 1024.0 AS redo_queue_mb,
       dr.recovery_lsn,
       dr.truncation_lsn
   FROM sys.dm_hadr_database_replica_states dr
   INNER JOIN sys.databases db ON dr.database_id = db.database_id
   WHERE dr.is_suspended = 1
   ```

   **🔍 Suspension Reasons:**
   ```
   suspend_reason_desc analysis:

   SUSPEND_FROM_USER
   → Manual suspension by DBA
   → Resolution: ALTER DATABASE [DB] SET HADR RESUME

   SUSPEND_FROM_REDO
   → Redo thread encountered error on secondary
   → Common causes:
     • Page corruption on secondary
     • Out of disk space on secondary
     • Redo thread crash
   → Action: Check secondary ERRORLOG for specific error

   SUSPEND_FROM_CAPTURE
   → Log capture error on primary
   → Causes: Transaction log corruption, disk errors
   → Action: DBCC CHECKDB on primary

   SUSPEND_FROM_APPLY
   → Apply thread error on secondary
   → Similar to SUSPEND_FROM_REDO
   → Action: Review secondary server health
   ```

5. **Resume Data Movement:**
   ```sql
   -- Only resume if suspension cause is resolved!
   ALTER DATABASE [DatabaseName] SET HADR RESUME
   GO

   -- Verify resumed successfully
   SELECT
       db.name,
       dr.is_suspended,
       dr.synchronization_state_desc,
       DATEDIFF(SECOND, dr.last_commit_time, GETDATE()) AS lag_seconds
   FROM sys.dm_hadr_database_replica_states dr
   INNER JOIN sys.databases db ON dr.database_id = db.database_id
   WHERE db.name = 'DatabaseName'
   ```

   **⚠️ Important:** Don't resume blindly!
   - If suspended due to corruption: Fix corruption first (DBCC CHECKDB)
   - If suspended due to disk space: Free up space first
   - If suspended due to network: Verify connectivity restored

6. **Root Cause Analysis:**
   ```sql
   -- Check transaction log space usage
   SELECT
       db.name AS database_name,
       db.log_reuse_wait_desc,
       mf.size * 8 / 1024 AS log_size_mb,
       CAST(FILEPROPERTY(mf.name, 'SpaceUsed') AS INT) * 8 / 1024 AS log_used_mb,
       (mf.size - CAST(FILEPROPERTY(mf.name, 'SpaceUsed') AS INT)) * 8 / 1024 AS log_free_mb,
       CAST(FILEPROPERTY(mf.name, 'SpaceUsed') AS INT) * 100.0 / mf.size AS log_used_percent
   FROM sys.databases db
   INNER JOIN sys.master_files mf ON db.database_id = mf.database_id
   WHERE mf.type_desc = 'LOG'
     AND db.name IN (SELECT database_name FROM sys.availability_databases_cluster)
   ```

   **🔍 Log Reuse Wait Analysis:**
   ```
   log_reuse_wait_desc meanings:

   AVAILABILITY_REPLICA
   → Log cannot truncate because secondary needs it
   → Causes:
     • Secondary disconnected/suspended
     • Secondary redo queue very large
   → Impact: Transaction log grows on primary
   → Action: Resolve secondary issue or remove from AG temporarily

   ACTIVE_TRANSACTION
   → Long-running open transaction
   → Find it:
     SELECT * FROM sys.dm_tran_active_transactions
     WHERE transaction_begin_time < DATEADD(MINUTE, -5, GETDATE())

   LOG_BACKUP
   → No log backup taken recently
   → Action: Take log backup immediately
   ```

**Key DMVs:** sys.dm_hadr_database_replica_states, sys.dm_hadr_availability_replica_states

**Decision Tree Summary:**
```
NOT SYNCHRONIZING diagnosis:
├─ is_suspended = 1?
│  ├─ YES → Check suspend_reason_desc
│  │       └─ Resume after fixing root cause
│  └─ NO → Check connected_state_desc
│         ├─ DISCONNECTED → Network/endpoint issue
│         │                └─ Test connectivity, check firewall
│         └─ CONNECTED → Check error log for redo errors
│                       └─ Possible corruption or disk issue on secondary
```

---

### Q2: You notice the secondary replica is lagging behind by 30 minutes during peak hours. What steps would you take to identify and resolve this?

**Answer:**
1. **Measure Current Lag:**
   ```sql
   SELECT
       ar.replica_server_name,
       db_name(drs.database_id) AS database_name,
       drs.log_send_queue_size/1024.0 AS log_send_queue_mb,
       drs.log_send_rate/1024.0 AS log_send_rate_mb_sec,
       drs.redo_queue_size/1024.0 AS redo_queue_mb,
       drs.redo_rate/1024.0 AS redo_rate_mb_sec,
       CASE
           WHEN drs.redo_rate = 0 THEN -1
           ELSE CAST(drs.redo_queue_size AS FLOAT) / drs.redo_rate
       END AS estimated_redo_completion_time_sec,
       DATEDIFF(SECOND, drs.last_commit_time, GETDATE()) AS commit_lag_seconds,
       drs.last_hardened_lsn,
       drs.last_redone_lsn,
       drs.log_send_queue_size + drs.redo_queue_size AS total_lag_kb
   FROM sys.dm_hadr_database_replica_states drs
   INNER JOIN sys.availability_replicas ar ON drs.replica_id = ar.replica_id
   WHERE ar.replica_server_name = 'SecondaryServer'
   ```

   **🔍 Interpreting Lag Metrics:**
   ```
   log_send_queue_size (KB):
   ✅ < 1024 KB (1 MB):        Excellent - Near real-time
   ⚠️ 1024-10240 KB (1-10 MB): Acceptable - Minor lag
   ⚠️ 10240-51200 KB (10-50 MB): Warning - Growing backlog
   ❌ > 51200 KB (50 MB):      Critical - Severe network or bandwidth issue

   Interpretation:
   - This measures how much log is waiting to be SENT from primary to secondary
   - High value = Network can't keep up with transaction rate
   - Continuously growing = Bandwidth insufficient or network congestion

   log_send_rate (KB/sec):
   ✅ > 10240 KB/s (10 MB/s):  Good network throughput
   ⚠️ 1024-10240 KB/s:         Moderate - acceptable for low transaction rate
   ❌ < 1024 KB/s (1 MB/s):    Poor - network bottleneck likely

   Rule of thumb:
   - If (log_send_queue_size / log_send_rate) > 300 seconds (5 min)
     → Network cannot drain queue in reasonable time
     → Action: Increase bandwidth or enable compression

   redo_queue_size (KB):
   ✅ < 1024 KB (1 MB):        Excellent - Secondary keeping up
   ⚠️ 1024-10240 KB (1-10 MB): Acceptable - Brief spikes OK
   ⚠️ 10240-102400 KB (10-100 MB): Warning - Secondary struggling
   ❌ > 102400 KB (100 MB):    Critical - Secondary severely behind

   Interpretation:
   - This measures log RECEIVED but not yet APPLIED on secondary
   - High value = Secondary CPU/disk can't keep up with redo workload
   - Continuously growing = Secondary resources insufficient

   redo_rate (KB/sec):
   ✅ Matches or exceeds log_send_rate: Secondary keeping pace
   ⚠️ 50-90% of log_send_rate:       Secondary struggling but coping
   ❌ < 50% of log_send_rate:         Secondary falling further behind

   estimated_redo_completion_time_sec:
   ✅ < 60 seconds:     Excellent - will catch up quickly
   ⚠️ 60-300 seconds:   Acceptable - 1-5 minute recovery
   ⚠️ 300-1800 seconds: Warning - 5-30 minute recovery
   ❌ > 1800 seconds:   Critical - > 30 min to catch up (if load stops NOW)

   Note: This assumes redo_rate remains constant and no new transactions

   commit_lag_seconds:
   ✅ < 5 seconds:       Excellent for async, good for sync
   ⚠️ 5-30 seconds:      Acceptable for async, investigate for sync
   ⚠️ 30-300 seconds:    Significant lag (5 min data loss window)
   ❌ > 300 seconds:     Severe lag (> 5 min data loss risk)

   Special case:
   - If commit_lag_seconds > 1800 (30 min) as in your scenario:
     → 30 minutes of potential data loss if failover occurs
     → Immediate action required
   ```

2. **Identify Bottleneck:**

   **🔍 Bottleneck Decision Matrix:**
   ```
   Scenario A: Network Bottleneck
   Symptoms:
   - log_send_queue_size: HIGH (> 50 MB) ❌
   - redo_queue_size: LOW (< 10 MB) ✅
   - log_send_rate: LOW (< 5 MB/s) ❌
   - redo_rate: N/A (nothing to redo yet)

   Root Cause: Network cannot transmit log fast enough
   Common reasons:
   - Insufficient network bandwidth (1 Gbps insufficient for high-volume OLTP)
   - Network congestion (shared network with other traffic)
   - High latency WAN link (geographic DR)
   - Network equipment issues (packet loss, errors)

   Action Priority:
   1. Enable compression (can reduce bandwidth by 60-70%)
   2. Verify network health (packet loss, retransmits)
   3. Upgrade network (10 Gbps recommended for AG)
   4. Dedicated VLAN for AG traffic

   ---
   Scenario B: Secondary Redo Bottleneck
   Symptoms:
   - log_send_queue_size: LOW (< 10 MB) ✅
   - redo_queue_size: HIGH (> 100 MB) ❌
   - log_send_rate: GOOD (> 10 MB/s) ✅
   - redo_rate: LOW (< 5 MB/s) ❌

   Root Cause: Secondary cannot apply log changes fast enough
   Common reasons:
   - Insufficient CPU on secondary (redo single-threaded per database)
   - Slow disk I/O on secondary (poor IOPS)
   - Blocking on secondary (read queries holding locks)
   - Large transactions (redo must process entire transaction atomically)

   Action Priority:
   1. Check for blocking queries on secondary
   2. Verify disk performance (IOPS, latency)
   3. Enable Accelerated Database Recovery (ADR) for fast redo
   4. Increase CPU allocation to secondary

   ---
   Scenario C: Both Bottlenecks (Worst Case)
   Symptoms:
   - log_send_queue_size: HIGH (> 50 MB) ❌
   - redo_queue_size: HIGH (> 100 MB) ❌
   - Both queues growing continuously

   Root Cause: Cascading failure - network can't send, secondary can't process

   Action Priority:
   1. Address network first (compression, bandwidth)
   2. Then address secondary performance
   3. Consider temporary asynchronous commit mode
   4. Scale up both network and secondary resources

   ---
   Scenario D: Transaction Rate Too High
   Symptoms:
   - log_send_rate: GOOD (> 20 MB/s) ✅
   - redo_rate: GOOD (> 15 MB/s) ✅
   - BUT both queues still growing slowly

   Root Cause: Primary generating log faster than it can be replicated

   This is workload issue, not AG issue:
   - Primary transaction rate: 25 MB/s
   - Network throughput: 20 MB/s
   - Secondary redo: 15 MB/s
   → System cannot keep up with workload

   Solutions:
   1. Batch transactions (reduce log generation)
   2. Defer non-critical writes to off-peak
   3. Scale up infrastructure (network AND secondary)
   4. Consider read-scale out to reduce secondary load
   ```

   **Quick Diagnostic Script:**
   ```sql
   -- Run this to automatically identify bottleneck
   DECLARE @LogSendQueue INT, @RedoQueue INT
   SELECT TOP 1
       @LogSendQueue = log_send_queue_size / 1024,
       @RedoQueue = redo_queue_size / 1024
   FROM sys.dm_hadr_database_replica_states
   WHERE is_local = 0
   ORDER BY log_send_queue_size + redo_queue_size DESC

   SELECT
       CASE
           WHEN @LogSendQueue > 50000 AND @RedoQueue < 10000
               THEN '❌ NETWORK BOTTLENECK - Enable compression, check bandwidth'
           WHEN @LogSendQueue < 10000 AND @RedoQueue > 100000
               THEN '❌ SECONDARY REDO BOTTLENECK - Check CPU/disk on secondary'
           WHEN @LogSendQueue > 50000 AND @RedoQueue > 100000
               THEN '❌ BOTH BOTTLENECKS - Critical infrastructure issue'
           WHEN @LogSendQueue < 1000 AND @RedoQueue < 1000
               THEN '✅ HEALTHY - No bottleneck detected'
           ELSE '⚠️ MINOR LAG - Monitor closely'
       END AS bottleneck_analysis,
       @LogSendQueue AS log_send_queue_mb,
       @RedoQueue AS redo_queue_mb
   ```

3. **Resolution Steps:**
   - **For Network Issues:**
     - Enable compression: `ALTER AVAILABILITY GROUP [AGName] MODIFY REPLICA ON 'SecondaryServer' WITH (SEEDING_MODE = AUTOMATIC, SESSION_TIMEOUT = 20)`
     - Increase network bandwidth

   - **For Secondary Redo Issues:**
     - Check for long-running queries blocking redo: `SELECT * FROM sys.dm_exec_requests WHERE blocking_session_id > 0`
     - Add more CPUs or enable Accelerated Database Recovery (ADR)
     - Consider using readable secondary with read-intent routing to reduce load

4. **Implement Monitoring:**
   ```sql
   CREATE EVENT SESSION AG_DataMovementTracking
   ON SERVER
   ADD EVENT sqlserver.hadr_db_commit_mgr_harden
   ADD TARGET package0.event_file(SET filename=N'AG_DataMovement.xel')
   WITH (STARTUP_STATE=ON)
   ```

---

### Q3: During a planned failover, you notice the database on the new primary is in "RESOLVING" state for 10 minutes. What's happening and how do you fix it?

**Answer:**
**What's Happening:**
RESOLVING state indicates the database is performing crash recovery (redo/undo) after failover. This includes:
- Rolling forward committed transactions (REDO phase)
- Rolling back uncommitted transactions (UNDO phase)

**Root Causes:**
1. Large uncommitted transactions at time of failover
2. High volume of log records to process
3. Insufficient I/O on new primary replica

**Diagnostic Steps:**
```sql
-- Check recovery progress
SELECT
    database_id,
    DB_NAME(database_id) AS DatabaseName,
    percent_complete,
    estimated_completion_time,
    command
FROM sys.dm_exec_requests
WHERE command IN ('DB STARTUP', 'ASYNC_IO_COMPLETION')

-- Check VLFs that may slow recovery
DBCC LOGINFO
```

**Resolution:**
1. **Immediate Action:**
   - Wait for recovery to complete (killing the process will restart recovery)
   - Monitor using sys.dm_exec_requests

2. **Prevention for Future:**
   ```sql
   -- Enable Accelerated Database Recovery (SQL 2019+)
   ALTER DATABASE [DatabaseName] SET ACCELERATED_DATABASE_RECOVERY = ON

   -- Reduce VLF count
   -- 1. Shrink log file
   DBCC SHRINKFILE (LogFileName, TRUNCATEONLY)
   -- 2. Grow to optimal size in single growth
   ALTER DATABASE [DatabaseName] MODIFY FILE (NAME = LogFileName, SIZE = 50GB, FILEGROWTH = 8GB)
   ```

3. **Check for Long Transactions:**
   ```sql
   DBCC OPENTRAN
   ```

**Expected Resolution Time:** With ADR enabled, recovery typically completes in seconds regardless of active transaction size.

---

### Q4: You need to add a new database to an existing AG, but the database is 2TB in size. What's the most efficient method?

**Answer:**
**Best Approach: Automatic Seeding (SQL Server 2016+)**

1. **Prerequisites Check:**
   ```sql
   -- Verify endpoint exists and is started
   SELECT * FROM sys.database_mirroring_endpoints

   -- Check available disk space on secondary (needs 2x database size)
   EXEC xp_fixeddrives
   ```

2. **Configure Automatic Seeding:**
   ```sql
   -- On Primary
   ALTER AVAILABILITY GROUP [AGName]
   MODIFY REPLICA ON 'PrimaryServer'
   WITH (SEEDING_MODE = AUTOMATIC)

   ALTER AVAILABILITY GROUP [AGName]
   MODIFY REPLICA ON 'SecondaryServer'
   WITH (SEEDING_MODE = AUTOMATIC)
   ```

3. **Add Database to AG:**
   ```sql
   -- Ensure database is in FULL recovery model
   ALTER DATABASE [LargeDB] SET RECOVERY FULL

   -- Take full backup (required for transaction log chain)
   BACKUP DATABASE [LargeDB] TO DISK = 'NUL'

   -- Add to AG
   ALTER AVAILABILITY GROUP [AGName] ADD DATABASE [LargeDB]
   ```

4. **Monitor Seeding Progress:**
   ```sql
   SELECT
       ag.name AS ag_name,
       db.database_name,
       drs.is_primary_replica,
       drs.synchronization_state_desc,
       drs.synchronization_health_desc,
       ar.replica_server_name,
       ar.seeding_mode_desc,
       ps.internal_state_desc,
       ps.transfer_rate_bytes_per_second/1024/1024 AS transfer_rate_mb_sec,
       ps.transferred_size_bytes/1024/1024/1024 AS transferred_size_gb,
       ps.database_size_bytes/1024/1024/1024 AS database_size_gb,
       ps.transferred_size_bytes*100.0/ps.database_size_bytes AS percent_complete,
       ps.failure_message
   FROM sys.dm_hadr_automatic_seeding ps
   JOIN sys.availability_groups ag ON ps.ag_id = ag.group_id
   JOIN sys.availability_replicas ar ON ar.replica_id = ps.ag_remote_replica_id
   JOIN sys.dm_hadr_database_replica_states drs ON ag.group_id = drs.group_id
   JOIN sys.databases db ON db.database_id = drs.database_id
   ```

**Alternative Approach for Faster Seeding:**
```sql
-- Manual seeding with backup/restore (faster over slow network)
-- 1. On Primary
BACKUP DATABASE [LargeDB] TO DISK = '\\SharedPath\LargeDB_Full.bak' WITH COMPRESSION
BACKUP LOG [LargeDB] TO DISK = '\\SharedPath\LargeDB_Log.trn'

-- 2. On Secondary
RESTORE DATABASE [LargeDB] FROM DISK = '\\SharedPath\LargeDB_Full.bak' WITH NORECOVERY
RESTORE LOG [LargeDB] FROM DISK = '\\SharedPath\LargeDB_Log.trn' WITH NORECOVERY

-- 3. Join to AG
ALTER DATABASE [LargeDB] SET HADR AVAILABILITY GROUP = [AGName]
```

**Performance Tips:**
- Use backup compression
- Consider multiple backup files for parallel processing
- Ensure network bandwidth is sufficient
- Schedule during maintenance window

---

### Q5: Your AG listener is not routing read-only connections to the secondary replica. How do you troubleshoot and fix this?

**Answer:**
**Diagnostic Steps:**

1. **Verify Read-Only Routing Configuration:**
   ```sql
   -- Check routing list
   SELECT
       ag.name AS AGName,
       ar.replica_server_name,
       ar.read_only_routing_url,
       ar.secondary_role_allow_connections_desc
   FROM sys.availability_replicas ar
   JOIN sys.availability_groups ag ON ar.group_id = ag.group_id

   -- Check routing order
   SELECT
       ar.replica_server_name,
       arl.routing_priority,
       ar2.replica_server_name AS routed_to_server
   FROM sys.availability_read_only_routing_lists arl
   JOIN sys.availability_replicas ar ON arl.replica_id = ar.replica_id
   JOIN sys.availability_replicas ar2 ON arl.read_only_replica_id = ar2.replica_id
   ORDER BY ar.replica_server_name, arl.routing_priority
   ```

2. **Verify Connection String:**
   ```plaintext
   Correct: Server=AGListener;Database=MyDB;ApplicationIntent=ReadOnly
   Incorrect: Server=AGListener;Database=MyDB (missing ApplicationIntent)
   ```

3. **Check Secondary Replica Settings:**
   ```sql
   -- Verify secondary allows read connections
   SELECT
       replica_server_name,
       secondary_role_allow_connections_desc
   FROM sys.availability_replicas
   -- Should show "ALL" or "READ_ONLY"
   ```

**Resolution:**

1. **Configure Read-Only Routing URL:**
   ```sql
   ALTER AVAILABILITY GROUP [AGName]
   MODIFY REPLICA ON 'PrimaryServer'
   WITH (PRIMARY_ROLE(READ_ONLY_ROUTING_URL = 'TCP://PrimaryServer.domain.com:1433'))

   ALTER AVAILABILITY GROUP [AGName]
   MODIFY REPLICA ON 'SecondaryServer'
   WITH (
       SECONDARY_ROLE(ALLOW_CONNECTIONS = ALL),
       PRIMARY_ROLE(READ_ONLY_ROUTING_URL = 'TCP://SecondaryServer.domain.com:1433')
   )
   ```

2. **Configure Routing List:**
   ```sql
   ALTER AVAILABILITY GROUP [AGName]
   MODIFY REPLICA ON 'PrimaryServer'
   WITH (PRIMARY_ROLE(READ_ONLY_ROUTING_LIST = ('SecondaryServer')))

   ALTER AVAILABILITY GROUP [AGName]
   MODIFY REPLICA ON 'SecondaryServer'
   WITH (PRIMARY_ROLE(READ_ONLY_ROUTING_LIST = ('PrimaryServer')))
   ```

3. **Test Connection:**
   ```sql
   -- From application server
   sqlcmd -S AGListener -d MyDB -K ReadOnly -Q "SELECT @@SERVERNAME"
   -- Should return SecondaryServer name
   ```

**Common Issues:**
- Incorrect port in routing URL
- Firewall blocking routing URL port
- DNS resolution issues with routing URL
- ApplicationIntent not specified in connection string

---

### Q6: During high transaction load, you see "HADR_SYNC_COMMIT" waits accumulating. What does this indicate and how do you resolve it?

**Answer:**
**What It Indicates:**
HADR_SYNC_COMMIT waits occur when the primary replica is waiting for acknowledgment from synchronous secondary replicas that transaction log has been hardened to disk. High waits indicate:
1. Network latency between replicas
2. Secondary replica I/O bottleneck
3. Excessive transaction volume

**Diagnostic Queries:**

```sql
-- 1. Check current wait stats
SELECT
    wait_type,
    waiting_tasks_count,
    wait_time_ms,
    max_wait_time_ms,
    signal_wait_time_ms,
    wait_time_ms - signal_wait_time_ms AS resource_wait_time_ms
FROM sys.dm_os_wait_stats
WHERE wait_type = 'HADR_SYNC_COMMIT'

-- 2. Measure network latency
SELECT
    ar.replica_server_name,
    hars.connected_state_desc,
    hars.last_connect_error_description,
    hars.last_connect_error_timestamp
FROM sys.dm_hadr_availability_replica_states hars
JOIN sys.availability_replicas ar ON hars.replica_id = ar.replica_id

-- 3. Check log send/redo queues
SELECT
    ar.replica_server_name,
    db_name(drs.database_id) AS database_name,
    drs.log_send_queue_size,
    drs.log_send_rate,
    drs.redo_queue_size,
    drs.redo_rate,
    drs.last_commit_time,
    DATEDIFF(s, drs.last_commit_time, GETDATE()) AS seconds_behind_primary
FROM sys.dm_hadr_database_replica_states drs
JOIN sys.availability_replicas ar ON drs.replica_id = ar.replica_id
WHERE drs.is_local = 0
```

**Resolution Strategies:**

1. **Optimize Network Performance:**
   ```sql
   -- Enable compression for AG traffic
   ALTER AVAILABILITY GROUP [AGName]
   MODIFY REPLICA ON 'SecondaryServer'
   WITH (SEEDING_MODE = AUTOMATIC) -- Enables compression

   -- Adjust session timeout (default 10 seconds)
   ALTER AVAILABILITY GROUP [AGName]
   MODIFY REPLICA ON 'SecondaryServer'
   WITH (SESSION_TIMEOUT = 20) -- Increase if frequent disconnects
   ```

2. **Improve Secondary I/O Performance:**
   - Move transaction log to faster storage (SSD/NVMe)
   - Ensure secondary has equal or better I/O than primary
   - Check for I/O bottlenecks:
   ```sql
   SELECT
       db_name(vfs.database_id) AS database_name,
       mf.name AS file_name,
       io_stall_read_ms,
       num_of_reads,
       io_stall_read_ms / NULLIF(num_of_reads, 0) AS avg_read_latency_ms,
       io_stall_write_ms,
       num_of_writes,
       io_stall_write_ms / NULLIF(num_of_writes, 0) AS avg_write_latency_ms
   FROM sys.dm_io_virtual_file_stats(NULL, NULL) vfs
   JOIN sys.master_files mf ON vfs.database_id = mf.database_id AND vfs.file_id = mf.file_id
   WHERE mf.type_desc = 'LOG'
   ORDER BY avg_write_latency_ms DESC
   ```

3. **Consider Availability Mode Change:**
   ```sql
   -- If synchronous commit causing performance issues, evaluate async
   -- (Only if RPO allows data loss)
   ALTER AVAILABILITY GROUP [AGName]
   MODIFY REPLICA ON 'SecondaryServer'
   WITH (AVAILABILITY_MODE = ASYNCHRONOUS_COMMIT)
   ```

4. **Application-Level Optimization:**
   - Reduce transaction size (commit more frequently)
   - Implement batching for bulk operations
   - Consider delayed durability for non-critical transactions:
   ```sql
   ALTER DATABASE [DatabaseName] SET DELAYED_DURABILITY = ALLOWED
   -- Then in application:
   COMMIT TRANSACTION WITH (DELAYED_DURABILITY = ON)
   ```

5. **Enable Accelerated Database Recovery (SQL 2019+):**
   ```sql
   ALTER DATABASE [DatabaseName] SET ACCELERATED_DATABASE_RECOVERY = ON
   ```

**Expected Results:**
- HADR_SYNC_COMMIT waits should be < 5ms in most cases
- If consistently > 10ms, investigate network or secondary I/O

---

### Q7: You need to perform a rolling upgrade of SQL Server across your AG replicas. Outline the detailed steps and potential issues.

**Answer:**
**Pre-Upgrade Planning:**

1. **Version Compatibility Check:**
   ```sql
   -- Current versions
   SELECT
       ar.replica_server_name,
       ar.endpoint_url,
       SERVERPROPERTY('ProductVersion') AS Version,
       SERVERPROPERTY('ProductLevel') AS ServicePack,
       SERVERPROPERTY('Edition') AS Edition
   FROM sys.availability_replicas ar
   ```
   - Ensure target version supports rolling upgrade (usually 1-2 versions)
   - Review [Microsoft documentation](https://learn.microsoft.com/en-us/sql/database-engine/availability-groups/windows/upgrading-always-on-availability-group-replica-instances)

2. **Backup Strategy:**
   ```sql
   -- Full backup before upgrade
   BACKUP DATABASE [Database1] TO DISK = '\\BackupPath\PreUpgrade_Full.bak' WITH COMPRESSION, CHECKSUM
   BACKUP LOG [Database1] TO DISK = '\\BackupPath\PreUpgrade_Log.trn' WITH COMPRESSION, CHECKSUM
   ```

**Rolling Upgrade Steps:**

**Phase 1: Upgrade Secondaries**
```sql
-- 1. Suspend data movement (optional, for faster upgrade)
ALTER DATABASE [Database1] SET HADR SUSPEND

-- 2. On each secondary (starting with async, then sync secondaries):
--    a. Stop SQL Server service
--    b. Run SQL Server installer
--    c. Start SQL Server service
--    d. Verify upgrade
SELECT SERVERPROPERTY('ProductVersion')

-- 3. Resume data movement
ALTER DATABASE [Database1] SET HADR RESUME

-- 4. Verify synchronization
SELECT
    replica_server_name,
    synchronization_state_desc,
    synchronization_health_desc
FROM sys.dm_hadr_database_replica_states drs
JOIN sys.availability_replicas ar ON drs.replica_id = ar.replica_id
```

**Phase 2: Fail Over to Upgraded Secondary**
```sql
-- 1. Perform planned failover to upgraded secondary
ALTER AVAILABILITY GROUP [AGName] FAILOVER

-- 2. Verify new primary
SELECT
    @@SERVERNAME AS CurrentPrimary,
    SERVERPROPERTY('ProductVersion') AS Version
```

**Phase 3: Upgrade Former Primary**
```sql
-- 1. Now this is a secondary - upgrade it
-- Stop SQL Server service
-- Run installer
-- Start SQL Server service

-- 2. Verify all replicas upgraded
SELECT
    ar.replica_server_name,
    hars.role_desc,
    hars.operational_state_desc,
    SERVERPROPERTY('ProductVersion') AS Version
FROM sys.dm_hadr_availability_replica_states hars
JOIN sys.availability_replicas ar ON hars.replica_id = ar.replica_id
```

**Phase 4: Fail Back (Optional)**
```sql
-- Return to original primary if desired
ALTER AVAILABILITY GROUP [AGName] FAILOVER
```

**Monitoring During Upgrade:**
```sql
-- Create monitoring script
SELECT
    ag.name,
    ar.replica_server_name,
    ar.availability_mode_desc,
    drs.synchronization_state_desc,
    drs.synchronization_health_desc,
    drs.database_state_desc,
    drs.is_suspended,
    drs.suspend_reason_desc
FROM sys.dm_hadr_database_replica_states drs
JOIN sys.availability_groups ag ON drs.group_id = ag.group_id
JOIN sys.availability_replicas ar ON drs.replica_id = ar.replica_id
ORDER BY ag.name, ar.replica_server_name
```

**Potential Issues and Mitigations:**

1. **Issue: Failover takes longer than expected**
   - Mitigation: Ensure databases use Accelerated Database Recovery
   - Check for long-running transactions before failover: `DBCC OPENTRAN`

2. **Issue: Data movement suspended after upgrade**
   - Mitigation: Manually resume: `ALTER DATABASE [DB] SET HADR RESUME`

3. **Issue: Automatic seeding fails after upgrade**
   - Mitigation: Use manual seeding with backup/restore

4. **Issue: Version incompatibility**
   - Mitigation: Verify supported upgrade paths beforehand

5. **Issue: Service won't start after upgrade**
   - Mitigation: Check error log, ensure compatibility flags are set

**Best Practices:**
- Schedule during maintenance window
- Test in non-production environment first
- Have rollback plan ready
- Monitor performance after each step
- Keep downtime window minimal (typically < 1 minute per failover)

---

### Q8: Explain the difference between SYNCHRONOUS_COMMIT and ASYNCHRONOUS_COMMIT modes. In what scenarios would you use each?

**Answer:**

**Technical Differences:**

| Aspect | SYNCHRONOUS_COMMIT | ASYNCHRONOUS_COMMIT |
|--------|-------------------|---------------------|
| Transaction Commit | Waits for secondary to harden log | Doesn't wait for secondary |
| Data Loss (RPO) | Zero data loss | Potential data loss |
| Performance Impact | Higher latency on commits | Minimal latency on commits |
| Automatic Failover | Supported | Not supported |
| Network Dependency | High - network latency affects commits | Low - network issues don't block commits |
| Use Case | Production DBs requiring no data loss | DR sites, reporting secondaries |

**How Synchronous Commit Works:**
```plaintext
1. Application commits transaction
2. Primary writes log to disk
3. Primary sends log to secondary
4. Secondary hardens log to disk
5. Secondary sends acknowledgment
6. Primary acknowledges commit to application ← Transaction waits here
```

**How Asynchronous Commit Works:**
```plaintext
1. Application commits transaction
2. Primary writes log to disk
3. Primary acknowledges commit to application ← Returns immediately
4. Primary sends log to secondary (in background)
5. Secondary hardens log to disk
6. Secondary sends acknowledgment (not waited for)
```

**Configuration:**
```sql
-- Set to Synchronous
ALTER AVAILABILITY GROUP [AGName]
MODIFY REPLICA ON 'Server1'
WITH (AVAILABILITY_MODE = SYNCHRONOUS_COMMIT)

-- Set to Asynchronous
ALTER AVAILABILITY GROUP [AGName]
MODIFY REPLICA ON 'Server2'
WITH (AVAILABILITY_MODE = ASYNCHRONOUS_COMMIT)
```

**Scenario-Based Usage:**

**Scenario 1: Local HA with Zero Data Loss**
```sql
-- Primary: Server1 (DataCenter-A)
-- Secondary: Server2 (DataCenter-A, same location)
-- Configuration: SYNCHRONOUS_COMMIT
-- Reason: Low network latency (<1ms), requires zero data loss, automatic failover

ALTER AVAILABILITY GROUP [ProductionAG]
MODIFY REPLICA ON 'Server1' WITH (
    AVAILABILITY_MODE = SYNCHRONOUS_COMMIT,
    FAILOVER_MODE = AUTOMATIC
)

ALTER AVAILABILITY GROUP [ProductionAG]
MODIFY REPLICA ON 'Server2' WITH (
    AVAILABILITY_MODE = SYNCHRONOUS_COMMIT,
    FAILOVER_MODE = AUTOMATIC
)
```

**Scenario 2: Geo-Distributed DR**
```sql
-- Primary: Server1 (DataCenter-A, New York)
-- Secondary: Server2 (DataCenter-B, London)
-- Configuration: ASYNCHRONOUS_COMMIT
-- Reason: High network latency (80ms), DR only, can tolerate some data loss

ALTER AVAILABILITY GROUP [ProductionAG]
MODIFY REPLICA ON 'DRServer' WITH (
    AVAILABILITY_MODE = ASYNCHRONOUS_COMMIT,
    FAILOVER_MODE = MANUAL
)
```

**Scenario 3: Hybrid Approach**
```sql
-- Primary: NYC-Server1
-- Sync Secondary: NYC-Server2 (same DC, <1ms)
-- Async Secondary 1: London-Server (DR, 80ms)
-- Async Secondary 2: Reporting-Server (offload reads)

ALTER AVAILABILITY GROUP [ProductionAG]
MODIFY REPLICA ON 'NYC-Server2' WITH (
    AVAILABILITY_MODE = SYNCHRONOUS_COMMIT,
    FAILOVER_MODE = AUTOMATIC
)

ALTER AVAILABILITY GROUP [ProductionAG]
MODIFY REPLICA ON 'London-Server' WITH (
    AVAILABILITY_MODE = ASYNCHRONOUS_COMMIT,
    FAILOVER_MODE = MANUAL,
    SECONDARY_ROLE(ALLOW_CONNECTIONS = NO) -- DR only
)

ALTER AVAILABILITY GROUP [ProductionAG]
MODIFY REPLICA ON 'Reporting-Server' WITH (
    AVAILABILITY_MODE = ASYNCHRONOUS_COMMIT,
    FAILOVER_MODE = MANUAL,
    SECONDARY_ROLE(ALLOW_CONNECTIONS = ALL) -- Read-only access
)
```

**Performance Monitoring:**
```sql
-- Check commit latency for synchronous replicas
SELECT
    ar.replica_server_name,
    ar.availability_mode_desc,
    drs.database_id,
    db_name(drs.database_id) AS database_name,
    drs.last_commit_time,
    drs.last_hardened_time,
    DATEDIFF(ms, drs.last_commit_time, drs.last_hardened_time) AS commit_latency_ms
FROM sys.dm_hadr_database_replica_states drs
JOIN sys.availability_replicas ar ON drs.replica_id = ar.replica_id
WHERE ar.availability_mode_desc = 'SYNCHRONOUS_COMMIT'
```

**Decision Matrix:**

Use SYNCHRONOUS_COMMIT when:
- ✅ Network latency < 5ms
- ✅ Zero data loss required (RPO = 0)
- ✅ Automatic failover needed
- ✅ Replicas in same data center

Use ASYNCHRONOUS_COMMIT when:
- ✅ Network latency > 10ms (especially cross-geo)
- ✅ Some data loss acceptable (RPO > 0)
- ✅ Manual failover acceptable
- ✅ Reporting/read-only secondary
- ✅ DR site (disaster recovery)

**Hybrid Pattern (Recommended for Production):**
```
Primary (NYC)
├─ Sync Secondary (NYC) - Zero data loss, auto-failover
├─ Async Secondary (London) - DR protection
└─ Async Secondary (Local) - Read-only reporting
```

---

### Q9: Your AG cluster lost quorum and all replicas went offline. How do you recover?

**Answer:**

**Understanding Quorum:**
- WSFC requires majority of votes to maintain quorum
- Example: 3-node cluster needs 2 votes minimum
- Loss of quorum = cluster stops, AG goes offline

**Recovery Steps:**

**Step 1: Assess the Situation**
```powershell
# Check cluster status
Get-ClusterNode
Get-ClusterGroup

# Check which nodes are available
Get-ClusterNode | Select-Object Name, State, NodeWeight
```

**Step 2: Force Quorum (If Majority Nodes Lost)**
```powershell
# Force quorum from available node
Start-ClusterNode -Name "Node1" -ForceQuorum

# Or force quorum on current node
Start-ClusterNode -ForceQuorum
```

**Step 3: Verify Cluster Service**
```powershell
# Check cluster service
Get-Service ClusSvc

# Start if needed
Start-Service ClusSvc

# Verify cluster resources
Get-ClusterResource | Select-Object Name, State, OwnerGroup
```

**Step 4: Bring AG Online**
```sql
-- Check AG state
SELECT
    ag.name,
    hags.primary_replica,
    hags.primary_recovery_health_desc,
    hags.synchronization_health_desc
FROM sys.availability_groups ag
LEFT JOIN sys.dm_hadr_availability_group_states hags ON ag.group_id = hags.group_id

-- If AG is offline, bring online
ALTER AVAILABILITY GROUP [AGName] ONLINE

-- Check individual database states
SELECT
    db_name(database_id) AS database_name,
    synchronization_state_desc,
    synchronization_health_desc,
    database_state_desc
FROM sys.dm_hadr_database_replica_states
WHERE is_local = 1
```

**Step 5: Resume Data Movement if Suspended**
```sql
-- Check for suspended databases
SELECT
    db_name(database_id) AS database_name,
    is_suspended,
    suspend_reason_desc
FROM sys.dm_hadr_database_replica_states
WHERE is_suspended = 1

-- Resume each database
ALTER DATABASE [Database1] SET HADR RESUME
ALTER DATABASE [Database2] SET HADR RESUME
```

**Step 6: Restore Redundancy**
```powershell
# Add back failed nodes
Add-ClusterNode -Name "Node2" -Cluster "ClusterName"
Add-ClusterNode -Name "Node3" -Cluster "ClusterName"

# Verify quorum configuration
(Get-Cluster).DynamicQuorum  # Should be 1 (enabled)

# Check witness configuration (if using)
Get-ClusterQuorum
```

**Advanced Recovery Scenario: Split-Brain Prevention**

If you have multiple sites and each thinks it's primary:

```sql
-- On each suspected primary, check role
SELECT
    ar.replica_server_name,
    hars.role_desc,
    hars.operational_state_desc
FROM sys.dm_hadr_availability_replica_states hars
JOIN sys.availability_replicas ar ON hars.replica_id = ar.replica_id
WHERE hars.is_local = 1

-- If multiple primaries exist, force one offline
ALTER AVAILABILITY GROUP [AGName] OFFLINE

-- Then on correct primary
ALTER AVAILABILITY GROUP [AGName] FORCE_FAILOVER_ALLOW_DATA_LOSS
```

**File Share Witness Configuration (Prevent Future Quorum Loss):**
```powershell
# Configure file share witness
Set-ClusterQuorum -FileShareWitness "\\FileServer\ClusterWitness"

# Or use Cloud Witness (Azure)
Set-ClusterQuorum -CloudWitness -AccountName "storageaccount" -AccessKey "key"
```

**Post-Recovery Validation:**
```sql
-- 1. Verify all replicas synchronized
SELECT
    ag.name AS ag_name,
    ar.replica_server_name,
    hars.role_desc,
    drs.database_id,
    db_name(drs.database_id) AS database_name,
    drs.synchronization_state_desc,
    drs.synchronization_health_desc
FROM sys.availability_groups ag
JOIN sys.availability_replicas ar ON ag.group_id = ar.group_id
JOIN sys.dm_hadr_availability_replica_states hars ON ar.replica_id = hars.replica_id
LEFT JOIN sys.dm_hadr_database_replica_states drs ON ar.replica_id = drs.replica_id
ORDER BY ag.name, ar.replica_server_name, database_name

-- 2. Check for data loss
-- Compare LSNs on all replicas
SELECT
    replica_server_name,
    database_id,
    db_name(database_id) AS database_name,
    last_hardened_lsn,
    last_hardened_time
FROM sys.dm_hadr_database_replica_states drs
JOIN sys.availability_replicas ar ON drs.replica_id = ar.replica_id
ORDER BY database_id, last_hardened_lsn DESC

-- 3. Verify automatic failover capability
SELECT
    ar.replica_server_name,
    ar.failover_mode_desc,
    ar.availability_mode_desc
FROM sys.availability_replicas ar
WHERE ar.failover_mode_desc = 'AUTOMATIC'
```

**Prevention Strategies:**
1. Use odd number of nodes (3, 5) for natural majority
2. Implement File Share Witness or Cloud Witness
3. Enable Dynamic Quorum (default in Windows 2012+)
4. Configure proper node weights
5. Monitor cluster health proactively

---

### Q10: You have 3 synchronous replicas in your AG. During peak time, you notice significant performance degradation. How do you identify which replica is causing the issue?

**Answer:**

**Diagnostic Approach:**

**Step 1: Identify HADR Wait Statistics**
```sql
-- Check HADR-related waits on primary
SELECT
    wait_type,
    waiting_tasks_count,
    wait_time_ms,
    max_wait_time_ms,
    wait_time_ms / NULLIF(waiting_tasks_count, 0) AS avg_wait_time_ms
FROM sys.dm_os_wait_stats
WHERE wait_type LIKE 'HADR%'
ORDER BY wait_time_ms DESC
```

**Key Wait Types:**
- **HADR_SYNC_COMMIT** - Waiting for secondary to acknowledge transaction commit
- **HADR_LOG_SEND** - Waiting to send log blocks to secondary
- **HADR_NOTIFICATION_DEQUEUE** - Background task waits (usually benign)

**Step 2: Check Per-Replica Performance**
```sql
-- Detailed replica performance metrics
SELECT
    ag.name AS ag_name,
    ar.replica_server_name,
    ar.availability_mode_desc,
    db_name(drs.database_id) AS database_name,

    -- Log Send Queue (Primary → Secondary network delay)
    drs.log_send_queue_size AS log_send_queue_kb,
    drs.log_send_rate AS log_send_rate_kb_sec,
    CASE
        WHEN drs.log_send_rate > 0
        THEN drs.log_send_queue_size / drs.log_send_rate
        ELSE -1
    END AS est_log_send_completion_sec,

    -- Redo Queue (Secondary processing delay)
    drs.redo_queue_size AS redo_queue_kb,
    drs.redo_rate AS redo_rate_kb_sec,
    CASE
        WHEN drs.redo_rate > 0
        THEN drs.redo_queue_size / drs.redo_rate
        ELSE -1
    END AS est_redo_completion_sec,

    -- Time lag
    drs.last_sent_time,
    drs.last_received_time,
    drs.last_hardened_time,
    drs.last_redone_time,
    drs.last_commit_time,
    DATEDIFF(s, drs.last_commit_time, GETDATE()) AS seconds_behind_primary,

    -- Health indicators
    drs.synchronization_state_desc,
    drs.synchronization_health_desc,
    drs.database_state_desc,
    drs.is_suspended,
    drs.suspend_reason_desc,

    -- Low-level stats
    drs.log_send_queue_size * 1.0 / 1024 AS log_send_queue_mb,
    drs.redo_queue_size * 1.0 / 1024 AS redo_queue_mb

FROM sys.dm_hadr_database_replica_states drs
INNER JOIN sys.availability_replicas ar ON drs.replica_id = ar.replica_id
INNER JOIN sys.availability_groups ag ON ar.group_id = ag.group_id
WHERE ar.availability_mode_desc = 'SYNCHRONOUS_COMMIT'
  AND drs.is_local = 0  -- Remote replicas only
ORDER BY est_redo_completion_sec DESC, log_send_queue_size DESC
```

**Step 3: Identify the Bottleneck**

**Problem Pattern 1: High log_send_queue_size**
```sql
-- Indicates network bottleneck between primary and specific secondary
-- Check from primary:
SELECT
    ar.replica_server_name,
    hars.connected_state_desc,
    hars.last_connect_error_description,
    hars.last_connect_error_number,
    hars.last_connect_error_timestamp
FROM sys.dm_hadr_availability_replica_states hars
JOIN sys.availability_replicas ar ON hars.replica_id = ar.replica_id
WHERE hars.connected_state_desc <> 'CONNECTED'
```

**Problem Pattern 2: High redo_queue_size**
```sql
-- Indicates secondary replica is slow at processing (CPU/IO bottleneck)
-- Run on the slow secondary replica:

-- Check for blocking on secondary
SELECT
    session_id,
    blocking_session_id,
    wait_type,
    wait_time,
    wait_resource,
    command,
    program_name
FROM sys.dm_exec_requests
WHERE blocking_session_id > 0
   OR wait_type IN ('LCK_M_X', 'LCK_M_S', 'PAGEIOLATCH_SH', 'PAGEIOLATCH_EX')

-- Check I/O latency on secondary
SELECT
    db_name(vfs.database_id) AS database_name,
    mf.physical_name,
    mf.type_desc,
    vfs.num_of_writes,
    vfs.io_stall_write_ms,
    vfs.io_stall_write_ms / NULLIF(vfs.num_of_writes, 0) AS avg_write_latency_ms
FROM sys.dm_io_virtual_file_stats(NULL, NULL) vfs
JOIN sys.master_files mf ON vfs.database_id = mf.database_id AND vfs.file_id = mf.file_id
WHERE mf.type = 1  -- Log files
ORDER BY avg_write_latency_ms DESC
```

**Step 4: Replica-Specific Extended Events**
```sql
-- Create XE session on primary to track slow secondaries
CREATE EVENT SESSION AGPerformance ON SERVER
ADD EVENT sqlserver.hadr_db_commit_mgr_harden(
    WHERE duration > 100000  -- > 100ms
    ACTION(
        sqlserver.database_name,
        sqlserver.client_app_name,
        sqlserver.session_id
    )
)
ADD TARGET package0.histogram(
    SET filtering_event_name = 'sqlserver.hadr_db_commit_mgr_harden',
        source = 'sqlserver.database_name',
        source_type = 1
)
WITH (MAX_MEMORY = 50MB, EVENT_RETENTION_MODE = ALLOW_SINGLE_EVENT_LOSS)

ALTER EVENT SESSION AGPerformance ON SERVER STATE = START

-- After running for a while, query results
SELECT
    n.value('(value)[1]', 'bigint') AS database_id,
    db_name(n.value('(value)[1]', 'bigint')) AS database_name,
    n.value('(@count)[1]', 'bigint') AS event_count
FROM (
    SELECT CAST(target_data AS XML) AS target_data
    FROM sys.dm_xe_session_targets xst
    JOIN sys.dm_xe_sessions xs ON xst.event_session_address = xs.address
    WHERE xs.name = 'AGPerformance'
      AND xst.target_name = 'histogram'
) AS data
CROSS APPLY target_data.nodes('HistogramTarget/Slot') AS T(n)
ORDER BY event_count DESC
```

**Resolution Strategies:**

**For Network Bottleneck (High log_send_queue):**
```sql
-- 1. Enable compression
ALTER AVAILABILITY GROUP [AGName]
MODIFY REPLICA ON 'SlowReplica'
WITH (SEEDING_MODE = AUTOMATIC)  -- Enables compression

-- 2. Check and increase bandwidth
-- 3. Verify no firewall/router issues
```

**For Secondary I/O Bottleneck (High redo_queue):**
```sql
-- 1. Move log files to faster storage
-- 2. Ensure transaction log on SSD/NVMe
-- 3. Check for resource contention:

-- Check CPU pressure on secondary
SELECT
    scheduler_id,
    current_tasks_count,
    runnable_tasks_count,
    work_queue_count,
    pending_disk_io_count
FROM sys.dm_os_schedulers
WHERE scheduler_id < 255

-- 4. Consider converting slowest replica to ASYNC
ALTER AVAILABILITY GROUP [AGName]
MODIFY REPLICA ON 'SlowReplica'
WITH (AVAILABILITY_MODE = ASYNCHRONOUS_COMMIT)
```

**For Blocking on Secondary:**
```sql
-- Kill blocking sessions (if read-only workload is causing blocking)
KILL <session_id>

-- Or prevent read workload from blocking redo
ALTER AVAILABILITY GROUP [AGName]
MODIFY REPLICA ON 'SlowReplica'
WITH (SECONDARY_ROLE(ALLOW_CONNECTIONS = NO))
```

**Monitoring Dashboard Query:**
```sql
-- Real-time monitoring query
SELECT
    ar.replica_server_name,
    CASE
        WHEN drs.log_send_queue_size > 10240 THEN '⚠️ Network Issue'
        WHEN drs.redo_queue_size > 10240 THEN '⚠️ Secondary Slow'
        WHEN DATEDIFF(s, drs.last_commit_time, GETDATE()) > 60 THEN '🔴 Lagging'
        ELSE '✅ Healthy'
    END AS status,
    drs.log_send_queue_size / 1024.0 AS log_send_mb,
    drs.redo_queue_size / 1024.0 AS redo_mb,
    DATEDIFF(s, drs.last_commit_time, GETDATE()) AS lag_seconds
FROM sys.dm_hadr_database_replica_states drs
JOIN sys.availability_replicas ar ON drs.replica_id = ar.replica_id
WHERE drs.is_local = 0
ORDER BY lag_seconds DESC
```

---

## Section 2: Performance Tuning & Query Optimization

### Q36: A critical query suddenly started taking 30 seconds instead of 2 seconds. Walk through your troubleshooting process.

**Answer:**

**Step 1: Capture Current Execution Plan**
```sql
-- Enable actual execution plan
SET STATISTICS IO ON
SET STATISTICS TIME ON

-- Run the problematic query
<YOUR_QUERY>

-- Analyze messages tab for:
-- - Logical reads (should be minimal)
-- - CPU time
-- - Elapsed time
```

**Step 2: Check for Plan Change (Parameter Sniffing)**
```sql
-- Find query and per-plan runtime intervals in Query Store
SELECT
    q.query_id,
    qt.query_sql_text,
    p.plan_id,
    rs.last_execution_time,
    rs.avg_duration / 1000000.0 AS avg_duration_sec,
    rs.avg_logical_io_reads,
    rs.count_executions
FROM sys.query_store_query q
JOIN sys.query_store_query_text qt ON q.query_text_id = qt.query_text_id
JOIN sys.query_store_plan p ON q.query_id = p.query_id
JOIN sys.query_store_runtime_stats rs ON p.plan_id = rs.plan_id
WHERE qt.query_sql_text LIKE '%YourQuerySignature%'
ORDER BY rs.last_execution_time DESC

-- Compare plans for one query
SELECT
    p.query_id,
    p.plan_id,
    rs.avg_duration / 1000000.0 AS avg_duration_sec,
    rs.last_execution_time
FROM sys.query_store_plan p
JOIN sys.query_store_runtime_stats rs ON p.plan_id = rs.plan_id
WHERE p.query_id = <your_query_id>
ORDER BY rs.last_execution_time

-- If bad plan found, force good plan
EXEC sp_query_store_force_plan @query_id = X, @plan_id = Y
```

**Step 3: Check for Blocking**
```sql
SELECT
    r.session_id,
    r.blocking_session_id,
    r.wait_type,
    r.wait_time,
    r.wait_resource,
    t.text AS query_text,
    blocking_text.text AS blocking_query_text
FROM sys.dm_exec_requests r
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
LEFT JOIN sys.dm_exec_requests br ON r.blocking_session_id = br.session_id
OUTER APPLY sys.dm_exec_sql_text(br.sql_handle) blocking_text
WHERE r.session_id = <your_spid>
```

**Step 4: Check for Statistics Issues**
```sql
-- Check when statistics were last updated
SELECT
    OBJECT_NAME(s.object_id) AS table_name,
    s.name AS stats_name,
    STATS_DATE(s.object_id, s.stats_id) AS last_updated,
    sp.rows,
    sp.modification_counter,
    sp.modification_counter * 100.0 / NULLIF(sp.rows, 0) AS pct_modified
FROM sys.stats s
CROSS APPLY sys.dm_db_stats_properties(s.object_id, s.stats_id) sp
WHERE OBJECT_NAME(s.object_id) IN ('YourTable1', 'YourTable2')
ORDER BY pct_modified DESC

-- Update statistics if stale
UPDATE STATISTICS [TableName] WITH FULLSCAN
-- Or specific statistics
UPDATE STATISTICS [TableName] ([StatisticsName]) WITH FULLSCAN
```

**Step 5: Check for Index Issues**
```sql
-- Check for missing indexes
SELECT
    migs.avg_user_impact,
    migs.avg_total_user_cost,
    migs.user_seeks + migs.user_scans AS total_uses,
    mid.statement AS table_name,
    mid.equality_columns,
    mid.inequality_columns,
    mid.included_columns,
    'CREATE INDEX IX_' + OBJECT_NAME(mid.object_id) + '_' +
        REPLACE(REPLACE(ISNULL(mid.equality_columns, ''), ',', '_'), ' ', '') +
        CASE WHEN mid.inequality_columns IS NOT NULL
            THEN '_' + REPLACE(REPLACE(mid.inequality_columns, ',', '_'), ' ', '')
            ELSE '' END +
    ' ON ' + mid.statement +
    ' (' + ISNULL(mid.equality_columns, '') +
        CASE WHEN mid.inequality_columns IS NOT NULL
            THEN CASE WHEN mid.equality_columns IS NOT NULL THEN ',' ELSE '' END + mid.inequality_columns
            ELSE '' END + ')' +
    CASE WHEN mid.included_columns IS NOT NULL
        THEN ' INCLUDE (' + mid.included_columns + ')'
        ELSE '' END AS create_index_statement
FROM sys.dm_db_missing_index_groups mig
JOIN sys.dm_db_missing_index_group_stats migs ON mig.index_group_handle = migs.group_handle
JOIN sys.dm_db_missing_index_details mid ON mig.index_handle = mid.index_handle
WHERE mid.database_id = DB_ID()
ORDER BY migs.avg_user_impact * migs.avg_total_user_cost * (migs.user_seeks + migs.user_scans) DESC

-- Check for fragmentation
SELECT
    OBJECT_NAME(ips.object_id) AS table_name,
    i.name AS index_name,
    ips.index_type_desc,
    ips.avg_fragmentation_in_percent,
    ips.page_count
FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') ips
JOIN sys.indexes i ON ips.object_id = i.object_id AND ips.index_id = i.index_id
WHERE ips.avg_fragmentation_in_percent > 30
  AND ips.page_count > 1000
ORDER BY ips.avg_fragmentation_in_percent DESC
```

**Step 6: Check for Data Volume Changes**
```sql
-- Check table sizes
SELECT
    t.name AS table_name,
    p.rows AS row_count,
    SUM(a.total_pages) * 8 / 1024 AS total_space_mb,
    SUM(a.used_pages) * 8 / 1024 AS used_space_mb
FROM sys.tables t
JOIN sys.partitions p ON t.object_id = p.object_id
JOIN sys.allocation_units a ON p.partition_id = a.container_id
WHERE t.name IN ('YourTable1', 'YourTable2')
GROUP BY t.name, p.rows
ORDER BY row_count DESC
```

**Step 7: Check for Lock Escalation**
```sql
-- Check lock escalation events
SELECT
    OBJECT_NAME(object_id) AS table_name,
    index_id,
    partition_number,
    lock_escalation_desc
FROM sys.partitions p
JOIN sys.tables t ON p.object_id = t.object_id
WHERE OBJECT_NAME(p.object_id) IN ('YourTable')

-- Disable lock escalation if needed
ALTER TABLE [YourTable] SET (LOCK_ESCALATION = DISABLE)
```

**Resolution Decision Tree:**

```
Query Slow?
├─ Plan Changed? → Force good plan or recompile
├─ Blocking? → Identify and kill blocker
├─ Statistics Stale? → Update statistics
├─ Missing Index? → Create index
├─ Fragmentation High? → Rebuild index
└─ Data Volume Increased? → Partition table or archive old data
```

**Step 8: Quick Fixes (Tactical)**
```sql
-- Option 1: Force recompile (clears bad plan)
EXEC sp_recompile '[TableName]'

-- Option 2: Clear procedure cache (use cautiously)
DBCC FREEPROCCACHE

-- Option 3: Add query hint
SELECT * FROM Table WITH (FORCESEEK)
-- Or
SELECT * FROM Table OPTION (RECOMPILE)

-- Option 4: Update statistics asynchronously
UPDATE STATISTICS [Table] WITH FULLSCAN, RESAMPLE ON PARTITIONS (1)
```

**Permanent Solution:**
```sql
-- Enable Query Store for ongoing monitoring
ALTER DATABASE [YourDB] SET QUERY_STORE = ON
ALTER DATABASE [YourDB] SET QUERY_STORE (
    OPERATION_MODE = READ_WRITE,
    DATA_FLUSH_INTERVAL_SECONDS = 900,
    INTERVAL_LENGTH_MINUTES = 60,
    MAX_STORAGE_SIZE_MB = 1000,
    QUERY_CAPTURE_MODE = AUTO,
    SIZE_BASED_CLEANUP_MODE = AUTO
)
```

---

### Q37: You have a stored procedure that performs well with parameter value 'A' but times out with parameter value 'B'. Explain and fix this.

**Answer:**

**Problem: Parameter Sniffing**

When a stored procedure is compiled, SQL Server generates an execution plan based on the first set of parameters it receives. This plan is cached and reused for subsequent executions, which can cause problems when different parameter values require different plans.

**Demonstration of the Issue:**
```sql
CREATE PROCEDURE usp_GetOrders
    @StatusCode NVARCHAR(20)
AS
BEGIN
    SELECT
        OrderID,
        CustomerID,
        OrderDate,
        TotalAmount
    FROM Orders
    WHERE StatusCode = @StatusCode
END

-- Scenario:
-- StatusCode 'Pending' = 10 rows (Index Seek is optimal)
-- StatusCode 'Completed' = 10,000,000 rows (Table Scan is optimal)

-- If procedure first compiled with 'Pending':
EXEC usp_GetOrders 'Pending'  -- Fast (uses Index Seek plan)
EXEC usp_GetOrders 'Completed'  -- Slow! (uses same Index Seek plan for 10M rows)
```

**Diagnostic Steps:**

```sql
-- 1. Verify it's parameter sniffing
-- Run with different parameters and compare plans
SET STATISTICS IO ON
EXEC usp_GetOrders 'A'  -- Note logical reads
EXEC usp_GetOrders 'B'  -- Note logical reads

-- 2. Check cached plan
SELECT
    cp.objtype,
    cp.usecounts,
    cp.size_in_bytes,
    OBJECT_NAME(st.objectid) AS proc_name,
    st.text,
    qp.query_plan
FROM sys.dm_exec_cached_plans cp
CROSS APPLY sys.dm_exec_sql_text(cp.plan_handle) st
CROSS APPLY sys.dm_exec_query_plan(cp.plan_handle) qp
WHERE st.text LIKE '%usp_GetOrders%'
  AND st.objectid = OBJECT_ID('usp_GetOrders')

-- 3. Check Query Store for plan variance
SELECT
    q.query_id,
    p.plan_id,
    qt.query_sql_text,
    rs.avg_duration/1000.0 AS avg_duration_ms,
    rs.min_duration/1000.0 AS min_duration_ms,
    rs.max_duration/1000.0 AS max_duration_ms,
    rs.count_executions
FROM sys.query_store_query q
JOIN sys.query_store_query_text qt ON q.query_text_id = qt.query_text_id
JOIN sys.query_store_plan p ON q.query_id = p.query_id
JOIN sys.query_store_runtime_stats rs ON p.plan_id = rs.plan_id
WHERE qt.query_sql_text LIKE '%usp_GetOrders%'
ORDER BY rs.max_duration DESC
```

**Solution Options:**

**Option 1: OPTION (RECOMPILE) - Best for highly variable parameters**
```sql
ALTER PROCEDURE usp_GetOrders
    @StatusCode NVARCHAR(20)
AS
BEGIN
    SELECT
        OrderID,
        CustomerID,
        OrderDate,
        TotalAmount
    FROM Orders
    WHERE StatusCode = @StatusCode
    OPTION (RECOMPILE)  -- New plan for each execution
END

-- Pros: Always optimal plan
-- Cons: CPU overhead for compilation
```

**Option 2: OPTIMIZE FOR UNKNOWN - Best for general cases**
```sql
ALTER PROCEDURE usp_GetOrders
    @StatusCode NVARCHAR(20)
AS
BEGIN
    SELECT
        OrderID,
        CustomerID,
        OrderDate,
        TotalAmount
    FROM Orders
    WHERE StatusCode = @StatusCode
    OPTION (OPTIMIZE FOR (@StatusCode UNKNOWN))  -- Uses average distribution
END

-- Pros: Avoids parameter sniffing, uses statistics
-- Cons: May not be optimal for any specific parameter
```

**Option 3: Local Variable Copy - Forces average estimate**
```sql
ALTER PROCEDURE usp_GetOrders
    @StatusCode NVARCHAR(20)
AS
BEGIN
    DECLARE @StatusCodeLocal NVARCHAR(20) = @StatusCode

    SELECT
        OrderID,
        CustomerID,
        OrderDate,
        TotalAmount
    FROM Orders
    WHERE StatusCode = @StatusCodeLocal  -- SQL Server can't sniff local variables
END

-- Pros: Simple, no query hints needed
-- Cons: May result in suboptimal plans
```

**Option 4: OPTIMIZE FOR - When you know common values**
```sql
ALTER PROCEDURE usp_GetOrders
    @StatusCode NVARCHAR(20)
AS
BEGIN
    SELECT
        OrderID,
        CustomerID,
        OrderDate,
        TotalAmount
    FROM Orders
    WHERE StatusCode = @StatusCode
    OPTION (OPTIMIZE FOR (@StatusCode = 'Completed'))  -- Optimize for most common value
END

-- Pros: Optimal for specified value
-- Cons: May be slow for other values
```

**Option 5: Dynamic SQL with sp_executesql - Most flexible**
```sql
ALTER PROCEDURE usp_GetOrders
    @StatusCode NVARCHAR(20)
AS
BEGIN
    DECLARE @SQL NVARCHAR(MAX) = N'
        SELECT
            OrderID,
            CustomerID,
            OrderDate,
            TotalAmount
        FROM Orders
        WHERE StatusCode = @StatusCode'

    EXEC sp_executesql
        @SQL,
        N'@StatusCode NVARCHAR(20)',
        @StatusCode

    -- Each unique parameter value gets its own cached plan
END

-- Pros: Separate plans for each parameter value
-- Cons: More complex, potential for SQL injection if not careful
```

**Option 6: Conditional Logic (Branch by Cardinality)**
```sql
ALTER PROCEDURE usp_GetOrders
    @StatusCode NVARCHAR(20)
AS
BEGIN
    DECLARE @RowCount INT

    -- Check cardinality first
    SELECT @RowCount = COUNT(*)
    FROM Orders
    WHERE StatusCode = @StatusCode

    IF @RowCount < 1000
    BEGIN
        -- Use index seek for small result sets
        SELECT
            OrderID,
            CustomerID,
            OrderDate,
            TotalAmount
        FROM Orders WITH (INDEX(IX_Orders_StatusCode))
        WHERE StatusCode = @StatusCode
    END
    ELSE
    BEGIN
        -- Use table scan for large result sets
        SELECT
            OrderID,
            CustomerID,
            OrderDate,
            TotalAmount
        FROM Orders WITH (INDEX(0))  -- Force table scan
        WHERE StatusCode = @StatusCode
    END
END
```

**Best Practice Solution - Hybrid Approach:**
```sql
ALTER PROCEDURE usp_GetOrders
    @StatusCode NVARCHAR(20),
    @ForceRecompile BIT = 0
AS
BEGIN
    SET NOCOUNT ON

    -- Check data distribution
    DECLARE @RowCount INT
    SELECT @RowCount = SUM(rows)
    FROM sys.partitions
    WHERE object_id = OBJECT_ID('Orders')

    -- For small tables or forced recompile
    IF @RowCount < 100000 OR @ForceRecompile = 1
    BEGIN
        SELECT
            OrderID,
            CustomerID,
            OrderDate,
            TotalAmount
        FROM Orders
        WHERE StatusCode = @StatusCode
        OPTION (RECOMPILE)
    END
    ELSE
    BEGIN
        -- For large tables, use OPTIMIZE FOR UNKNOWN
        SELECT
            OrderID,
            CustomerID,
            OrderDate,
            TotalAmount
        FROM Orders
        WHERE StatusCode = @StatusCode
        OPTION (OPTIMIZE FOR (@StatusCode UNKNOWN))
    END
END
```

**Monitoring and Validation:**
```sql
-- Create Extended Event to track compilations
CREATE EVENT SESSION ParameterSniffingMonitor
ON SERVER
ADD EVENT sqlserver.sql_statement_recompile(
    ACTION(
        sqlserver.database_name,
        sqlserver.sql_text,
        sqlserver.session_id
    )
    WHERE sqlserver.database_name = 'YourDB'
)
ADD TARGET package0.event_file(SET filename='C:\Temp\Recompiles.xel')
WITH (STARTUP_STATE=OFF)

ALTER EVENT SESSION ParameterSniffingMonitor ON SERVER STATE=START

-- Query results
SELECT
    event_data.value('(event/@timestamp)[1]', 'DATETIME2') AS event_time,
    event_data.value('(event/data[@name="statement"]/value)[1]', 'NVARCHAR(MAX)') AS statement,
    event_data.value('(event/data[@name="recompile_cause"]/text)[1]', 'NVARCHAR(100)') AS recompile_cause
FROM (
    SELECT CAST(event_data AS XML) AS event_data
    FROM sys.fn_xe_file_target_read_file('C:\Temp\Recompiles*.xel', NULL, NULL, NULL)
) AS tab
```

---

### Q38: Your tempdb is experiencing contention. How do you identify the source and resolve it?

**Answer:**

**Types of Tempdb Contention:**
1. **PFS (Page Free Space) Page Contention** - Multiple sessions trying to allocate pages
2. **SGAM (Shared Global Allocation Map) Page Contention** - Allocating uniform extents
3. **GAM (Global Allocation Map) Page Contention** - Allocating mixed extents
4. **Metadata Contention** - System table contention

**Diagnostic Steps:**

**Step 1: Identify Contention Type**
```sql
-- Check for allocation contention waits
SELECT
    wait_type,
    waiting_tasks_count,
    wait_time_ms,
    max_wait_time_ms,
    signal_wait_time_ms
FROM sys.dm_os_wait_stats
WHERE wait_type IN (
    'PAGELATCH_UP',      -- Page latch contention (common in tempdb)
    'PAGELATCH_SH',
    'PAGELATCH_EX',
    'PAGEIOLATCH_UP',
    'PAGEIOLATCH_SH',
    'PAGEIOLATCH_EX',
    'LATCH_EX',
    'LATCH_SH'
)
ORDER BY wait_time_ms DESC

-- Identify which specific pages are contended
SELECT
    session_id,
    wait_type,
    wait_duration_ms,
    resource_description
FROM sys.dm_os_waiting_tasks
WHERE wait_type LIKE 'PAGE%LATCH%'
  AND wait_duration_ms > 0
ORDER BY wait_duration_ms DESC

-- Decode the page to see if it's PFS/SGAM/GAM
-- Format: DatabaseID:FileID:PageID
-- Page 1 = GAM
-- Page 2 = SGAM
-- Page 3, 8088, 16176, etc. = PFS pages (every 8088 pages)
```

**Step 2: Check Tempdb Configuration**
```sql
-- Check number of tempdb data files
SELECT
    name,
    physical_name,
    size * 8 / 1024 AS size_mb,
    max_size,
    growth,
    is_percent_growth
FROM sys.master_files
WHERE database_id = DB_ID('tempdb')
ORDER BY file_id

-- Check file sizes are equal
SELECT
    name,
    size * 8 / 1024 AS current_size_mb,
    FILEPROPERTY(name, 'SpaceUsed') * 8 / 1024 AS used_mb,
    (size - FILEPROPERTY(name, 'SpaceUsed')) * 8 / 1024 AS free_mb
FROM sys.database_files
WHERE type_desc = 'ROWS'
```

**Step 3: Identify Heavy Tempdb Users**
```sql
-- Check which sessions are using tempdb heavily
SELECT
    es.session_id,
    es.login_name,
    es.host_name,
    es.program_name,
    er.command,
    t.text AS query_text,
    tsu.user_objects_alloc_page_count AS user_objects_pages,
    tsu.internal_objects_alloc_page_count AS internal_objects_pages,
    (tsu.user_objects_alloc_page_count + tsu.internal_objects_alloc_page_count) * 8 / 1024 AS total_tempdb_mb
FROM sys.dm_db_task_space_usage tsu
INNER JOIN sys.dm_exec_sessions es ON tsu.session_id = es.session_id
INNER JOIN sys.dm_exec_requests er ON es.session_id = er.session_id
OUTER APPLY sys.dm_exec_sql_text(er.sql_handle) t
WHERE tsu.session_id > 50  -- Exclude system sessions
ORDER BY total_tempdb_mb DESC

-- Check for version store usage (row versioning)
SELECT
    SUM(version_store_reserved_page_count) * 8 / 1024 AS version_store_mb,
    SUM(user_object_reserved_page_count) * 8 / 1024 AS user_objects_mb,
    SUM(internal_object_reserved_page_count) * 8 / 1024 AS internal_objects_mb,
    SUM(mixed_extent_page_count) * 8 / 1024 AS mixed_extent_mb
FROM sys.dm_db_file_space_usage
```

**Resolution Steps:**

**Resolution 1: Optimize Tempdb File Configuration**
```sql
-- Add multiple tempdb data files (Rule: # of files = # of CPUs up to 8)
-- Calculate optimal number
DECLARE @CPUCount INT = (SELECT cpu_count FROM sys.dm_os_sys_info)
DECLARE @FileCount INT = CASE WHEN @CPUCount <= 8 THEN @CPUCount ELSE 8 END

-- Add files to match CPU count
USE master
GO
DECLARE @i INT = (SELECT COUNT(*) FROM sys.master_files WHERE database_id = 2 AND type = 0)
DECLARE @CPUs INT = (SELECT cpu_count FROM sys.dm_os_sys_info)
DECLARE @TargetFiles INT = CASE WHEN @CPUs <= 8 THEN @CPUs ELSE 8 END

WHILE @i < @TargetFiles
BEGIN
    SET @i = @i + 1

    DECLARE @filename NVARCHAR(255) = N'tempdev' + CAST(@i AS NVARCHAR(10))
    DECLARE @filepath NVARCHAR(500) = N'D:\MSSQL\DATA\' + @filename + N'.ndf'

    EXEC('ALTER DATABASE tempdb ADD FILE (
        NAME = N''' + @filename + ''',
        FILENAME = N''' + @filepath + ''',
        SIZE = 8GB,
        FILEGROWTH = 512MB
    )')
END

-- Ensure all files are same size
ALTER DATABASE tempdb MODIFY FILE (NAME = tempdev, SIZE = 8GB)
ALTER DATABASE tempdb MODIFY FILE (NAME = tempdev2, SIZE = 8GB)
-- Repeat for all files

-- Set proper growth increment (not percentage!)
ALTER DATABASE tempdb MODIFY FILE (NAME = tempdev, FILEGROWTH = 512MB)
```

**Resolution 2: Enable Trace Flags (SQL Server 2016+)**
```sql
-- Trace Flag 1117: Grow all files in filegroup equally
-- Trace Flag 1118: Reduce mixed extent allocation contention
-- (These are default in SQL 2016+, but can enable explicitly)

-- Check if already enabled
DBCC TRACESTATUS(1117, 1118)

-- Enable globally
DBCC TRACEON(1117, 1118, -1)

-- Make persistent across restarts
-- SQL 2016+: Already default behavior
-- Earlier versions: Add -T1117 -T1118 to startup parameters
```

**Resolution 3: Optimize Queries Using Tempdb**
```sql
-- Find queries creating large temp tables
SELECT TOP 20
    qs.execution_count,
    qs.total_worker_time / qs.execution_count AS avg_cpu_time,
    qs.total_elapsed_time / qs.execution_count AS avg_elapsed_time,
    SUBSTRING(qt.text, (qs.statement_start_offset/2)+1,
        ((CASE qs.statement_end_offset
            WHEN -1 THEN DATALENGTH(qt.text)
            ELSE qs.statement_end_offset
        END - qs.statement_start_offset)/2) + 1) AS query_text,
    qp.query_plan
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) qt
CROSS APPLY sys.dm_exec_query_plan(qs.plan_handle) qp
WHERE qt.text LIKE '%INTO #%'  -- Temp table creation
   OR qt.text LIKE '%CREATE TABLE #%'
ORDER BY qs.total_worker_time / qs.execution_count DESC

-- Optimize temp table usage
-- Bad: SELECT * INTO #temp FROM LargeTable
-- Good:
CREATE TABLE #temp (
    Col1 INT,
    Col2 VARCHAR(100),
    INDEX IX_Col1 (Col1)  -- Add index immediately
)
INSERT INTO #temp (Col1, Col2)
SELECT Col1, Col2  -- Only needed columns
FROM LargeTable
WHERE <filter>  -- Filter before inserting
```

**Resolution 4: Reduce Version Store Usage**
```sql
-- Check for long-running transactions keeping version store
SELECT
    s.session_id,
    s.login_name,
    s.transaction_isolation_level,
    at.transaction_id,
    at.transaction_begin_time,
    DATEDIFF(MINUTE, at.transaction_begin_time, GETDATE()) AS transaction_duration_minutes,
    dest.text AS query_text
FROM sys.dm_tran_active_transactions at
INNER JOIN sys.dm_tran_session_transactions st ON at.transaction_id = st.transaction_id
INNER JOIN sys.dm_exec_sessions s ON st.session_id = s.session_id
LEFT JOIN sys.dm_exec_requests r ON s.session_id = r.session_id
OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) dest
WHERE at.transaction_type = 4  -- User transaction
ORDER BY transaction_duration_minutes DESC

-- Kill long-running transactions if appropriate
KILL <session_id>

-- Change isolation level if RCSI causing issues
-- Check current setting
SELECT name, is_read_committed_snapshot_on
FROM sys.databases
WHERE name = 'YourDB'

-- Disable if causing tempdb issues (evaluate impact first!)
ALTER DATABASE YourDB SET READ_COMMITTED_SNAPSHOT OFF
```

**Resolution 5: Implement Query Changes**
```sql
-- Replace cursors with set-based operations
-- Bad:
DECLARE cursor_name CURSOR FOR SELECT Col1 FROM Table
-- Processing one row at a time...

-- Good:
WITH CTE AS (
    SELECT Col1, ROW_NUMBER() OVER (ORDER BY Col1) AS rn
    FROM Table
)
UPDATE CTE SET Col1 = Col1 + 1  -- Set-based operation

-- Avoid functions causing spills to tempdb
-- Bad:
SELECT * FROM Table
ORDER BY SomeComplexCalculation(Col1)  -- May spill to tempdb

-- Good:
SELECT *, SomeComplexCalculation(Col1) AS CalcResult
FROM Table
ORDER BY CalcResult

-- Add memory grant if query is spilling
SELECT * FROM Table
ORDER BY Col1
OPTION (MIN_GRANT_PERCENT = 10)  -- Reserve more memory
```

**Monitoring and Prevention:**
```sql
-- Create alert for tempdb space usage
USE msdb
GO
EXEC sp_add_alert
    @name = N'Tempdb Space Alert',
    @message_id = 0,
    @severity = 0,
    @enabled = 1,
    @delay_between_responses = 900,  -- 15 minutes
    @include_event_description_in = 1,
    @category_name = N'[Uncategorized]',
    @performance_condition = N'SQLServer:Databases|Percent Log Used|tempdb|>|80'

-- Regular monitoring query
SELECT
    fg.name AS filegroup_name,
    df.name AS file_name,
    df.physical_name,
    CAST(df.size * 8.0 / 1024 AS DECIMAL(10,2)) AS size_mb,
    CAST(FILEPROPERTY(df.name, 'SpaceUsed') * 8.0 / 1024 AS DECIMAL(10,2)) AS used_mb,
    CAST((df.size - FILEPROPERTY(df.name, 'SpaceUsed')) * 8.0 / 1024 AS DECIMAL(10,2)) AS free_mb,
    CAST(FILEPROPERTY(df.name, 'SpaceUsed') * 100.0 / df.size AS DECIMAL(5,2)) AS pct_used
FROM sys.database_files df
LEFT JOIN sys.filegroups fg ON df.data_space_id = fg.data_space_id
WHERE df.type_desc = 'ROWS'
ORDER BY pct_used DESC
```

---

### Q39: You notice high CPU usage on SQL Server. Walk through your diagnostic and resolution approach.

**Answer:**

**Diagnostic Process:**

**Step 1: Confirm CPU Pressure**
```sql
-- Check current CPU utilization
SELECT TOP 30
    record.value('(./Record/@id)[1]', 'int') AS record_id,
    record.value('(./Record/SchedulerMonitorEvent/SystemHealth/SystemIdle)[1]', 'int') AS system_idle,
    record.value('(./Record/SchedulerMonitorEvent/SystemHealth/ProcessUtilization)[1]', 'int') AS sql_cpu_utilization,
    100 - record.value('(./Record/SchedulerMonitorEvent/SystemHealth/SystemIdle)[1]', 'int')
        - record.value('(./Record/SchedulerMonitorEvent/SystemHealth/ProcessUtilization)[1]', 'int') AS other_process_cpu,
    DATEADD(ms, -1 * ((SELECT ms_ticks FROM sys.dm_os_sys_info) - record.value('(./Record/@time)[1]', 'bigint')), GETDATE()) AS event_time
FROM (
    SELECT timestamp, CONVERT(xml, record) AS record
    FROM sys.dm_os_ring_buffers
    WHERE ring_buffer_type = N'RING_BUFFER_SCHEDULER_MONITOR'
      AND record LIKE '%<SystemHealth>%'
) AS x
ORDER BY record_id DESC
```

**🔍 Interpreting CPU Utilization Metrics:**
```
sql_cpu_utilization (% of total CPU used by SQL Server):
✅ 0-40%:      Normal - SQL Server lightly loaded
⚠️ 40-70%:     Moderate - Acceptable during business hours
⚠️ 70-90%:     High - Monitor closely, optimize queries
❌ 90-100%:    Critical - CPU bottleneck, immediate action required

system_idle (% of CPU idle across system):
✅ > 30%:      System healthy, spare capacity available
⚠️ 10-30%:     System busy but functional
❌ < 10%:      System overloaded, performance degraded

other_process_cpu (% used by non-SQL processes):
✅ < 10%:      Normal - SQL Server has priority
⚠️ 10-30%:     Acceptable - antivirus, monitoring agents
❌ > 30%:      Problem - competing processes stealing CPU
              Action: Identify rogue process with Task Manager

Pattern Analysis:
- Sustained sql_cpu_utilization > 80% for > 5 minutes
  → Workload exceeds server capacity
  → Solution: Optimize queries OR add more CPU cores

- Spiky sql_cpu_utilization (0% → 100% → 0%)
  → Specific query causing spikes
  → Solution: Identify and optimize query

- sql_cpu_utilization low but system_idle also low
  → Other processes consuming CPU
  → Check: other_process_cpu for culprit
```

```sql
-- Check signal wait percentage (indicates CPU pressure)
-- This metric shows % of wait time spent waiting for CPU vs other resources
SELECT
    CAST(100.0 * SUM(signal_wait_time_ms) / SUM(wait_time_ms) AS NUMERIC(20,2)) AS signal_wait_percent,
    CAST(SUM(signal_wait_time_ms) / 1000.0 / 60 AS NUMERIC(20,2)) AS signal_wait_time_minutes,
    CAST(SUM(wait_time_ms - signal_wait_time_ms) / 1000.0 / 60 AS NUMERIC(20,2)) AS resource_wait_minutes
FROM sys.dm_os_wait_stats
WHERE wait_time_ms > 0
  AND wait_type NOT IN (  -- Filter out benign waits
    'CLR_SEMAPHORE', 'LAZYWRITER_SLEEP', 'RESOURCE_QUEUE',
    'SLEEP_TASK', 'SLEEP_SYSTEMTASK', 'SQLTRACE_BUFFER_FLUSH',
    'WAITFOR', 'LOGMGR_QUEUE', 'CHECKPOINT_QUEUE',
    'REQUEST_FOR_DEADLOCK_SEARCH', 'XE_TIMER_EVENT', 'BROKER_TO_FLUSH',
    'BROKER_TASK_STOP', 'CLR_MANUAL_EVENT', 'CLR_AUTO_EVENT',
    'DISPATCHER_QUEUE_SEMAPHORE', 'FT_IFTS_SCHEDULER_IDLE_WAIT',
    'XE_DISPATCHER_WAIT', 'XE_DISPATCHER_JOIN', 'SQLTRACE_INCREMENTAL_FLUSH_SLEEP'
)
```

**🔍 Signal Wait Percentage Analysis:**
```
signal_wait_percent thresholds:
✅ < 10%:      Excellent - CPU not the bottleneck
              Queries waiting mostly on I/O, locks, or network
⚠️ 10-20%:     Acceptable - Some CPU contention
              Normal for busy OLTP systems
⚠️ 20-30%:     High - CPU becoming bottleneck
              Action: Review top CPU-consuming queries
❌ > 30%:      Critical - Severe CPU pressure
              Queries spending > 30% of wait time waiting for CPU

Interpretation:
- signal_wait_percent = (Time waiting for CPU) / (Total wait time)
- High % means: "When queries need to wait, they're waiting for CPU"

Example scenarios:
A) signal_wait_percent = 5%, sql_cpu_utilization = 40%
   → CPU healthy, waits are I/O or blocking
   → Focus on: Disk performance, index optimization

B) signal_wait_percent = 35%, sql_cpu_utilization = 95%
   → CPU saturated, queries queuing for CPU time
   → Focus on: Query optimization, add CPU cores

C) signal_wait_percent = 15%, sql_cpu_utilization = 60%
   → Balanced load, moderate CPU and I/O
   → System healthy but monitor trends
```

```sql
-- Check runnable tasks (queries waiting for CPU)
SELECT
    scheduler_id,
    cpu_id,
    current_tasks_count,
    runnable_tasks_count,  -- Queries ready to run but waiting for CPU
    current_workers_count,
    active_workers_count,
    work_queue_count,
    pending_disk_io_count,
    load_factor,
    yield_count
FROM sys.dm_os_schedulers
WHERE scheduler_id < 255  -- Exclude hidden schedulers
ORDER BY runnable_tasks_count DESC
```

**🔍 Scheduler Metrics Interpretation:**
```
runnable_tasks_count (per scheduler):
✅ 0-2:        Excellent - No CPU queue
⚠️ 2-5:        Acceptable - Slight CPU contention
⚠️ 5-10:       High - Queries waiting for CPU
❌ > 10:       Critical - Severe CPU backlog

What it means:
- Each scheduler maps to one logical CPU core
- runnable_tasks_count = queries ready to execute but waiting for CPU time
- If consistently > 0, CPU is bottleneck for that core

Example:
Scheduler 0: runnable_tasks_count = 15
Scheduler 1: runnable_tasks_count = 2
Scheduler 2: runnable_tasks_count = 14
→ Problem: Load imbalanced, schedulers 0 and 2 overloaded
→ Cause: Parallel queries concentrating on specific schedulers
→ Solution: Review MAXDOP settings

current_tasks_count:
- Total tasks on scheduler (runnable + running + suspended)
- High value (> 50) indicates heavy load on that scheduler

load_factor:
- Running average of task count
- Calculated: (current_tasks_count + runnable_tasks_count) over time
- SQL Server uses this for scheduler load balancing
- Higher load_factor = scheduler more likely to skip new task assignment

yield_count:
- Number of times tasks voluntarily yielded CPU
- Very high yield_count (> 1M) with high runnable_tasks
  → CPU starvation, tasks yielding frequently because of pressure
```

**Quick Decision Matrix:**
```
┌─────────────────────────┬──────────────────┬─────────────────┐
│ Metric                  │ Value            │ Action          │
├─────────────────────────┼──────────────────┼─────────────────┤
│ sql_cpu_utilization     │ > 90%            │ ❌ CPU bound    │
│ signal_wait_percent     │ > 25%            │ Find top queries│
│ runnable_tasks_count    │ > 5 per sched    │ Optimize/scale  │
├─────────────────────────┼──────────────────┼─────────────────┤
│ sql_cpu_utilization     │ < 50%            │ ✅ Not CPU      │
│ signal_wait_percent     │ < 15%            │ Check I/O       │
│ runnable_tasks_count    │ 0-1              │ Focus elsewhere │
└─────────────────────────┴──────────────────┴─────────────────┘
```
ORDER BY runnable_tasks_count DESC
```

**Step 2: Identify Top CPU Consumers**
```sql
-- Top queries by CPU usage (currently running)
SELECT TOP 20
    r.session_id,
    s.login_name,
    s.host_name,
    s.program_name,
    DB_NAME(r.database_id) AS database_name,
    r.cpu_time AS current_cpu_ms,
    r.total_elapsed_time AS elapsed_time_ms,
    r.reads,
    r.writes,
    r.logical_reads,
    r.granted_query_memory * 8 / 1024 AS granted_memory_mb,
    t.text AS query_text,
    qp.query_plan,
    r.wait_type,
    r.wait_time,
    r.last_wait_type
FROM sys.dm_exec_requests r
INNER JOIN sys.dm_exec_sessions s ON r.session_id = s.session_id
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
CROSS APPLY sys.dm_exec_query_plan(r.plan_handle) qp
WHERE s.is_user_process = 1
ORDER BY r.cpu_time DESC

-- Top queries by total CPU (from cache)
SELECT TOP 20
    qs.execution_count,
    qs.total_worker_time AS total_cpu_time_ms,
    qs.total_worker_time / qs.execution_count AS avg_cpu_time_ms,
    qs.max_worker_time AS max_cpu_time_ms,
    qs.total_elapsed_time / 1000000 AS total_elapsed_time_sec,
    qs.total_logical_reads,
    qs.total_logical_reads / qs.execution_count AS avg_logical_reads,
    qs.last_execution_time,
    SUBSTRING(qt.text, (qs.statement_start_offset/2)+1,
        ((CASE qs.statement_end_offset
            WHEN -1 THEN DATALENGTH(qt.text)
            ELSE qs.statement_end_offset
        END - qs.statement_start_offset)/2) + 1) AS query_text,
    qp.query_plan
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) qt
CROSS APPLY sys.dm_exec_query_plan(qs.plan_handle) qp
ORDER BY qs.total_worker_time DESC

-- Check for compile/recompile CPU usage
SELECT
    @@SERVERNAME AS server_name,
    OBJECT_NAME(objectid, dbid) AS object_name,
    cp.usecounts,
    cp.size_in_bytes,
    cp.cacheobjtype,
    cp.objtype,
    st.text
FROM sys.dm_exec_cached_plans cp
CROSS APPLY sys.dm_exec_sql_text(cp.plan_handle) st
WHERE cp.cacheobjtype = 'Compiled Plan'
  AND cp.usecounts = 1  -- Plans only used once (excessive recompilation)
ORDER BY cp.size_in_bytes DESC
```

**Step 3: Analyze Execution Plans**
```sql
-- Look for these CPU-intensive operations in execution plans:
-- 1. Table Scans / Index Scans (instead of seeks)
-- 2. Missing indexes
-- 3. Implicit conversions
-- 4. Functions on columns in WHERE clause
-- 5. Excessive sorts
-- 6. Hash joins on large datasets
-- 7. Parallelism with high CXPACKET waits

-- Check for implicit conversions
SELECT TOP 20
    t.text AS query_text,
    qp.query_plan,
    qs.execution_count,
    qs.total_worker_time / qs.execution_count AS avg_cpu_ms
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) t
CROSS APPLY sys.dm_exec_query_plan(qs.plan_handle) qp
WHERE CAST(qp.query_plan AS NVARCHAR(MAX)) LIKE '%CONVERT_IMPLICIT%'
ORDER BY qs.total_worker_time / qs.execution_count DESC
```

**Resolution Strategies:**

**Resolution 1: Optimize Problematic Queries**
```sql
-- Fix missing indexes
SELECT
    migs.avg_user_impact * (migs.user_seeks + migs.user_scans) AS impact_score,
    mid.statement AS table_name,
    mid.equality_columns,
    mid.inequality_columns,
    mid.included_columns,
    migs.user_seeks,
    migs.user_scans,
    migs.last_user_seek,
    migs.last_user_scan,
    'CREATE INDEX IX_' + REPLACE(REPLACE(REPLACE(mid.equality_columns, ',', '_'), '[', ''), ']', '') +
    ' ON ' + mid.statement +
    ' (' + ISNULL(mid.equality_columns, mid.inequality_columns) + ')' +
    CASE WHEN mid.included_columns IS NOT NULL
        THEN ' INCLUDE (' + mid.included_columns + ')'
        ELSE ''
    END AS create_index_ddl
FROM sys.dm_db_missing_index_group_stats migs
INNER JOIN sys.dm_db_missing_index_groups mig ON migs.group_handle = mig.index_group_handle
INNER JOIN sys.dm_db_missing_index_details mid ON mig.index_handle = mid.index_handle
WHERE mid.database_id = DB_ID()
ORDER BY impact_score DESC

-- Add columnstore for large scan queries
CREATE NONCLUSTERED COLUMNSTORE INDEX NCCI_FactTable
ON dbo.FactTable (Col1, Col2, Col3, Col4)
```

**Resolution 2: Update Statistics**
```sql
-- Check stale statistics
SELECT
    OBJECT_NAME(s.object_id) AS table_name,
    s.name AS stats_name,
    STATS_DATE(s.object_id, s.stats_id) AS last_updated,
    sp.modification_counter,
    sp.rows,
    sp.modification_counter * 100.0 / NULLIF(sp.rows, 0) AS pct_modified
FROM sys.stats s
CROSS APPLY sys.dm_db_stats_properties(s.object_id, s.stats_id) sp
WHERE OBJECT_SCHEMA_NAME(s.object_id) NOT IN ('sys')
  AND sp.modification_counter * 100.0 / NULLIF(sp.rows, 0) > 20  -- > 20% changed
ORDER BY pct_modified DESC

-- Update statistics
UPDATE STATISTICS [TableName] WITH FULLSCAN
-- Or auto-update with trace flag
DBCC TRACEON(2371, -1)  -- Lower threshold for auto-update stats
```

**Resolution 3: Reduce Recompilations**
```sql
-- Identify excessive recompilations
SELECT
    OBJECT_NAME(objectid) AS object_name,
    usecounts,
    objtype,
    TEXT
FROM sys.dm_exec_cached_plans cp
CROSS APPLY sys.dm_exec_sql_text(cp.plan_handle)
WHERE usecounts = 1  -- Only executed once, then recompiled
  AND objtype = 'Adhoc'
ORDER BY usecounts

-- Enable "Optimize for Ad hoc Workloads"
EXEC sp_configure 'optimize for ad hoc workloads', 1
RECONFIGURE

-- Use sp_executesql instead of dynamic SQL
-- Bad:
EXEC ('SELECT * FROM Table WHERE ID = ' + @ID)
-- Good:
EXEC sp_executesql N'SELECT * FROM Table WHERE ID = @ID', N'@ID INT', @ID
```

**Resolution 4: Manage Parallelism**
```sql
-- Check CXPACKET waits (parallel queries)
SELECT
    wait_type,
    waiting_tasks_count,
    wait_time_ms,
    max_wait_time_ms,
    wait_time_ms * 100.0 / SUM(wait_time_ms) OVER() AS wait_pct
FROM sys.dm_os_wait_stats
WHERE wait_type IN ('CXPACKET', 'CXCONSUMER', 'CXSYNC_CONSUMER', 'CXSYNC_PORT')
ORDER BY wait_time_ms DESC

-- Adjust MAXDOP if excessive parallelism
-- Check current setting
SELECT value_in_use
FROM sys.configurations
WHERE name = 'max degree of parallelism'

-- Set optimal MAXDOP (general guideline)
-- NUMA nodes <= 1: MAXDOP = # of cores (up to 8)
-- NUMA nodes > 1: MAXDOP = # of cores per NUMA node (up to 8)
EXEC sp_configure 'max degree of parallelism', 4
RECONFIGURE

-- Set cost threshold for parallelism higher
EXEC sp_configure 'cost threshold for parallelism', 50
RECONFIGURE
```

**Resolution 5: Resource Governor (Limit CPU per Workload)**
```sql
-- Create resource pool with CPU limit
CREATE RESOURCE POOL LimitedCPUPool
WITH (
    MAX_CPU_PERCENT = 50,  -- Limit to 50% CPU
    MIN_CPU_PERCENT = 10
)

-- Create workload group
CREATE WORKLOAD GROUP ReportingGroup
USING LimitedCPUPool

-- Create classifier function
CREATE FUNCTION dbo.RGClassifier()
RETURNS SYSNAME
WITH SCHEMABINDING
AS
BEGIN
    DECLARE @WorkloadGroup SYSNAME

    IF (SUSER_NAME() = 'ReportingUser' OR APP_NAME() LIKE '%SSRS%')
        SET @WorkloadGroup = 'ReportingGroup'
    ELSE
        SET @WorkloadGroup = 'default'

    RETURN @WorkloadGroup
END
GO

-- Enable Resource Governor
ALTER RESOURCE GOVERNOR WITH (CLASSIFIER_FUNCTION = dbo.RGClassifier)
ALTER RESOURCE GOVERNOR RECONFIGURE
```

**Monitoring and Prevention:**
```sql
-- Create CPU alert
USE msdb
GO
EXEC sp_add_alert
    @name = N'High CPU Alert',
    @message_id = 0,
    @severity = 0,
    @enabled = 1,
    @delay_between_responses = 300,
    @include_event_description_in = 1,
    @performance_condition = N'SQLServer:Resource Pool Stats|CPU usage %|default|>|80'

-- Regular monitoring query
SELECT
    DATEADD(ms, -1 * (si.ms_ticks - ri.record_time), GETDATE()) AS event_time,
    100 - ri.SystemIdle - ri.SQLProcessUtilization AS OtherProcessCPU,
    ri.SQLProcessUtilization,
    ri.SystemIdle
FROM (
    SELECT
        timestamp,
        CONVERT(xml, record) as record,
        record.value('(Record/@time)[1]', 'bigint') AS record_time,
        record.value('(Record/SchedulerMonitorEvent/SystemHealth/SystemIdle)[1]', 'int') AS SystemIdle,
        record.value('(Record/SchedulerMonitorEvent/SystemHealth/ProcessUtilization)[1]', 'int') AS SQLProcessUtilization
    FROM sys.dm_os_ring_buffers
    WHERE ring_buffer_type = N'RING_BUFFER_SCHEDULER_MONITOR'
      AND record LIKE '%<SystemHealth>%'
) AS ri
CROSS JOIN sys.dm_os_sys_info si
ORDER BY event_time DESC
```

**Quick Actions:**
```sql
-- If immediate relief needed:
-- 1. Kill top CPU consumer (if appropriate)
KILL <session_id>

-- 2. Force query plan (if bad plan regression)
EXEC sp_query_store_force_plan @query_id = X, @plan_id = Y

-- 3. Clear procedure cache (last resort - causes recompiles)
DBCC FREEPROCCACHE

-- 4. Add MAXDOP hint to problematic query
SELECT * FROM LargeTable
OPTION (MAXDOP 1)
```

---

### Q40: You're experiencing severe PAGELATCH_UP waits specifically on page 2:1:1 (PFS) and 2:1:3 (SGAM) in tempdb. Explain the issue and provide solutions.

**Answer:**

**Root Cause:** Tempdb latch contention occurs when multiple sessions compete for allocation pages during object creation/destruction. This is a classic bottleneck in high-concurrency OLTP workloads.

**Diagnostic:**
```sql
-- Check tempdb contention
SELECT
    session_id,
    wait_type,
    wait_time AS wait_duration_ms,
    blocking_session_id,
    wait_resource
FROM sys.dm_exec_requests
WHERE wait_type LIKE 'PAGELATCH%'
  AND wait_resource LIKE '2:%'  -- Database ID 2 = tempdb
ORDER BY wait_time DESC

-- Check tempdb file configuration
SELECT
    name,
    physical_name,
    size * 8 / 1024 AS size_mb,
    (size * 8 / 1024) - (FILEPROPERTY(name, 'SpaceUsed') * 8 / 1024) AS free_mb
FROM sys.master_files
WHERE database_id = DB_ID('tempdb')

-- Identify workload creating temp objects
SELECT
    s.session_id,
    s.login_name,
    s.program_name,
    r.command,
    t.text AS query_text,
    tsu.user_objects_alloc_page_count,
    tsu.internal_objects_alloc_page_count
FROM sys.dm_db_task_space_usage tsu
INNER JOIN sys.dm_exec_sessions s ON tsu.session_id = s.session_id
INNER JOIN sys.dm_exec_requests r ON s.session_id = r.session_id
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
WHERE tsu.user_objects_alloc_page_count > 0
   OR tsu.internal_objects_alloc_page_count > 0
ORDER BY tsu.user_objects_alloc_page_count + tsu.internal_objects_alloc_page_count DESC
```

**Solution 1: Add Multiple Tempdb Data Files**
*(Based on mssqlwiki.com guidance on tempdb optimization)*
```sql
-- Rule: # of files = # of CPU cores (up to 8), then add 4 at a time if needed
-- All files should be EQUAL SIZE and EQUAL AUTOGROWTH

-- Check CPU count
SELECT cpu_count FROM sys.dm_os_sys_info

-- Add tempdb files (example for 8 cores)
USE master
GO
ALTER DATABASE tempdb ADD FILE (
    NAME = tempdev2,
    FILENAME = 'T:\tempdb\tempdev2.ndf',
    SIZE = 8192MB,  -- Match existing file size
    FILEGROWTH = 512MB
)
GO
-- Repeat for tempdev3 through tempdev8
```

**Solution 2: Use Trace Flag 1118 (Pre-SQL 2016) or Enable Proportional Fill**
```sql
-- SQL 2016+: Enabled by default
-- Pre-2016: Enable trace flag 1118
DBCC TRACEON(1118, -1)  -- Uniform extent allocations for all databases

-- Verify proportional fill algorithm
SELECT * FROM sys.dm_db_file_space_usage
```

**Solution 3: SQL Server 2019+ Metadata Optimization**
```sql
-- Enable memory-optimized tempdb metadata (SQL 2019+)
-- Reduces contention on system table latches
ALTER SERVER CONFIGURATION SET MEMORY_OPTIMIZED TEMPDB_METADATA = ON
-- Requires SQL Server restart
```

**Solution 4: Application-Level Optimizations**
```sql
-- Reduce temp table usage:
-- Option A: Use table variables for small datasets (< 100 rows)
DECLARE @temp TABLE (ID INT, Name VARCHAR(100))
INSERT INTO @temp VALUES (1, 'Test')

-- Option B: Use CTEs instead of temp tables where possible
WITH CTE_Results AS (
    SELECT * FROM LargeTable WHERE ...
)
SELECT * FROM CTE_Results

-- Option C: Keep temp tables for larger datasets or when indexes needed
CREATE TABLE #Results (
    ID INT PRIMARY KEY,
    Name VARCHAR(100)
)

-- Option D: Reduce temp table churn by reusing tables
-- Bad pattern: CREATE/DROP in loop
-- Good pattern: CREATE once, TRUNCATE in loop
```

**Prevention & Monitoring:**
```sql
-- Monitor tempdb latch waits over time
SELECT
    wait_type,
    waiting_tasks_count,
    wait_time_ms,
    max_wait_time_ms,
    signal_wait_time_ms,
    wait_time_ms / NULLIF(waiting_tasks_count, 0) AS avg_wait_ms
FROM sys.dm_os_wait_stats
WHERE wait_type LIKE 'PAGELATCH%'
  AND wait_type NOT IN ('PAGELATCH_NL')
ORDER BY wait_time_ms DESC
```

**Key Points from mssqlwiki.com:**
- PFS (Page Free Space) pages track extent allocation
- SGAM (Shared Global Allocation Map) tracks mixed extents
- Multiple files reduce contention by distributing allocation structures
- SQL 2019+ in-memory tempdb metadata eliminates most system table contention

---

### Q41: A query has parameter sniffing issues - performs well with one parameter value but times out with another. Explain the problem and provide multiple solutions.

**Answer:**

**Root Cause:** SQL Server creates an execution plan based on the FIRST parameter value used (or statistics-based estimation). If data distribution is skewed, this cached plan may be optimal for some values but terrible for others.

**Diagnostic:**
```sql
-- Find queries with multiple plans (indicator of parameter sniffing)
SELECT
    qs.query_hash,
    COUNT(DISTINCT qs.query_plan_hash) AS plan_count,
    MIN(qs.execution_count) AS min_executions,
    MAX(qs.execution_count) AS max_executions,
    MIN(qs.total_elapsed_time / qs.execution_count) AS min_avg_duration_us,
    MAX(qs.total_elapsed_time / qs.execution_count) AS max_avg_duration_us,
    CAST(SUBSTRING(st.text,
        (qs.statement_start_offset / 2) + 1,
        ((CASE qs.statement_end_offset
            WHEN -1 THEN DATALENGTH(st.text)
            ELSE qs.statement_end_offset
        END - qs.statement_start_offset) / 2) + 1) AS VARCHAR(MAX)) AS query_text
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st
GROUP BY qs.query_hash, st.text, qs.statement_start_offset, qs.statement_end_offset
HAVING COUNT(DISTINCT qs.query_plan_hash) > 1
ORDER BY plan_count DESC

-- Check actual parameters used vs estimated
SELECT
    qsp.query_id,
    qsp.plan_id,
    qsp.query_plan,
    qsrs.avg_duration / 1000 AS avg_duration_ms,
    qsrs.avg_rowcount,
    qsrs.last_execution_time
FROM sys.query_store_plan qsp
INNER JOIN sys.query_store_runtime_stats qsrs ON qsp.plan_id = qsrs.plan_id
WHERE qsp.query_id = @YourQueryId
ORDER BY qsrs.last_execution_time DESC

-- Examine plan for estimated vs actual rows
-- Look for "ParameterCompiledValue" vs "ParameterRuntimeValue" in XML
```

**Solution 1: RECOMPILE (Forces new plan each execution)**
*(From mssqlwiki.com parameter sniffing article)*
```sql
-- Option A: Query-level hint
SELECT *
FROM Orders o
WHERE o.CustomerID = @CustomerID
OPTION (RECOMPILE)

-- Option B: Stored procedure level
CREATE PROCEDURE usp_GetOrders
    @CustomerID INT
WITH RECOMPILE
AS
BEGIN
    SELECT * FROM Orders WHERE CustomerID = @CustomerID
END

-- Pros: Always optimal plan
-- Cons: Compilation overhead, plan cache bloat
```

**Solution 2: OPTIMIZE FOR (Hint for specific value)**
```sql
-- Optimize for most common parameter value
SELECT *
FROM Orders o
WHERE o.CustomerID = @CustomerID
OPTION (OPTIMIZE FOR (@CustomerID = 12345))

-- Optimize for UNKNOWN (use average distribution)
SELECT *
FROM Orders o
WHERE o.CustomerID = @CustomerID
OPTION (OPTIMIZE FOR (@CustomerID UNKNOWN))

-- Pros: Predictable behavior
-- Cons: May not be optimal for all values
```

**Solution 3: Local Variable Copy (Prevents sniffing)**
```sql
-- SQL Server doesn't sniff local variables, uses average statistics
CREATE PROCEDURE usp_GetOrders
    @CustomerID INT
AS
BEGIN
    DECLARE @LocalCustomerID INT = @CustomerID

    SELECT *
    FROM Orders o
    WHERE o.CustomerID = @LocalCustomerID
END

-- Pros: Consistent plans
-- Cons: May choose suboptimal plan (uses density vector, not histogram)
```

**Solution 4: Query Store Plan Forcing**
```sql
-- Identify best-performing plan
SELECT
    q.query_id,
    p.plan_id,
    qt.query_sql_text,
    rs.avg_duration / 1000 AS avg_duration_ms,
    rs.count_executions,
    CAST(p.query_plan AS XML) AS query_plan
FROM sys.query_store_query q
INNER JOIN sys.query_store_plan p ON q.query_id = p.query_id
INNER JOIN sys.query_store_runtime_stats rs ON p.plan_id = rs.plan_id
INNER JOIN sys.query_store_query_text qt ON q.query_text_id = qt.query_text_id
WHERE qt.query_sql_text LIKE '%CustomerID%'
ORDER BY rs.avg_duration

-- Force good plan
EXEC sp_query_store_force_plan @query_id = 123, @plan_id = 456

-- Remove forcing if needed
EXEC sp_query_store_unforce_plan @query_id = 123, @plan_id = 456
```

**Solution 5: Dynamic SQL (Nuclear option)**
```sql
CREATE PROCEDURE usp_GetOrders
    @CustomerID INT
AS
BEGIN
    DECLARE @SQL NVARCHAR(MAX)

    SET @SQL = N'
        SELECT *
        FROM Orders o
        WHERE o.CustomerID = @CustomerID'

    EXEC sp_executesql @SQL,
        N'@CustomerID INT',
        @CustomerID = @CustomerID
END

-- Pros: Gets recompiled with actual parameter
-- Cons: Security (SQL injection risk), plan cache bloat
```

**Solution 6: Plan Guides (Legacy approach)**
```sql
-- Create plan guide to force RECOMPILE
EXEC sp_create_plan_guide
    @name = N'PlanGuide_Orders',
    @stmt = N'SELECT * FROM Orders WHERE CustomerID = @CustomerID',
    @type = N'SQL',
    @module_or_batch = NULL,
    @params = N'@CustomerID INT',
    @hints = N'OPTION (RECOMPILE)'
```

**Solution 7: Refactor Query (Break into branches)**
```sql
-- Use IF/ELSE for different parameter ranges
CREATE PROCEDURE usp_GetOrders
    @CustomerID INT
AS
BEGIN
    -- High-volume customer: use index seek
    IF @CustomerID IN (SELECT CustomerID FROM HighVolumeCustomers)
    BEGIN
        SELECT * FROM Orders WHERE CustomerID = @CustomerID
        OPTION (OPTIMIZE FOR (@CustomerID = 1))  -- Large customer
    END
    -- Low-volume customer: different strategy
    ELSE
    BEGIN
        SELECT * FROM Orders WHERE CustomerID = @CustomerID
        OPTION (OPTIMIZE FOR (@CustomerID = 999999))  -- Small customer
    END
END
```

**Prevention:**
```sql
-- Monitor for parameter sniffing issues
-- Create XE session to capture compilation vs runtime stats
CREATE EVENT SESSION ParameterSniffing
ON SERVER
ADD EVENT sqlserver.sql_statement_recompile(
    ACTION(sqlserver.sql_text, sqlserver.query_hash, sqlserver.plan_handle)
),
ADD EVENT sqlserver.query_plan_profile(
    WHERE duration > 5000000  -- 5 seconds
)
ADD TARGET package0.event_file(SET filename=N'ParameterSniffing.xel')
WITH (MAX_DISPATCH_LATENCY = 5 SECONDS)

-- Enable Query Store for automatic plan regression detection
ALTER DATABASE YourDB SET QUERY_STORE = ON
ALTER DATABASE YourDB SET QUERY_STORE (
    OPERATION_MODE = READ_WRITE,
    DATA_FLUSH_INTERVAL_SECONDS = 900,
    INTERVAL_LENGTH_MINUTES = 60,
    QUERY_CAPTURE_MODE = AUTO
)
```

**Key Insight from mssqlwiki.com:**
Parameter sniffing is GOOD when it works (gives optimal plan), but problematic with skewed data distribution. Choose solution based on:
- Frequency: RECOMPILE if infrequent
- Predictability: OPTIMIZE FOR if value known
- Consistency: Local variables if consistent performance preferred
- Modern approach: Query Store plan forcing (best for SQL 2016+)

---

### Q42: You receive an alert for "Non-Yielding Scheduler" error. Explain what this means and how you troubleshoot it.

**Answer:**

**Error Message:**
```
A non-yielding scheduler was detected. This condition can indicate a CPU-intensive query,
insufficient parallelism, or a potential bug in SQL Server.
```

**Root Cause:** SQL Server uses cooperative scheduling (SQLOS). Threads should voluntarily yield after 4ms (quantum). If a thread doesn't yield for 60+ seconds, it's flagged as non-yielding. Common causes:
1. Infinite loop in CLR code
2. Stuck spinlock
3. Antivirus scanning SQL files
4. Driver issues (storage, network)
5. Hardware problems
6. Actual SQL Server bug

**Diagnostic Process:**
*(Based on mssqlwiki.com non-yielding scheduler analysis)*

**Step 1: Check Error Log and Dump Files**
```sql
-- Check for recent non-yielding scheduler events
EXEC xp_readerrorlog 0, 1, N'non-yielding'

-- List recent minidump files
EXEC xp_cmdshell 'dir C:\Program Files\Microsoft SQL Server\MSSQL*.MSSQLSERVER\MSSQL\LOG\SQLDUMP*.mdmp /O-D'
```

**Step 2: Analyze Scheduler State**
```sql
-- Check scheduler health
SELECT
    scheduler_id,
    cpu_id,
    status,
    is_online,
    is_idle,
    current_tasks_count,
    runnable_tasks_count,
    current_workers_count,
    active_workers_count,
    work_queue_count,
    pending_disk_io_count,
    load_factor,
    yield_count,
    last_timer_activity,
    failed_to_create_worker,
    quantum_length_us
FROM sys.dm_os_schedulers
WHERE scheduler_id < 255  -- User schedulers only
ORDER BY scheduler_id

-- Check visible scheduler pressure with documented columns
SELECT
    scheduler_id,
    status,
    current_tasks_count,
    runnable_tasks_count,
    active_workers_count,
    work_queue_count,
    pending_disk_io_count
FROM sys.dm_os_schedulers
WHERE status = 'VISIBLE ONLINE'
ORDER BY runnable_tasks_count DESC
```

**Step 3: Check for Resource Bottlenecks**
```sql
-- Check for I/O bottlenecks
SELECT
    database_id,
    file_id,
    num_of_reads,
    num_of_bytes_read,
    io_stall_read_ms,
    num_of_writes,
    num_of_bytes_written,
    io_stall_write_ms,
    io_stall,
    size_on_disk_bytes,
    io_stall_read_ms / NULLIF(num_of_reads, 0) AS avg_read_latency_ms,
    io_stall_write_ms / NULLIF(num_of_writes, 0) AS avg_write_latency_ms
FROM sys.dm_io_virtual_file_stats(NULL, NULL)
WHERE io_stall_read_ms / NULLIF(num_of_reads, 0) > 20  -- > 20ms is concerning
   OR io_stall_write_ms / NULLIF(num_of_writes, 0) > 20
ORDER BY io_stall DESC

-- Check for spinlock contention
SELECT
    name,
    collisions,
    spins,
    spins_per_collision,
    sleep_time,
    backoffs
FROM sys.dm_os_spinlock_stats
WHERE spins > 0
ORDER BY spins DESC, collisions DESC

-- Common problematic spinlocks:
-- SOS_CACHESTORE: Plan cache contention
-- LOCK_HASH: Locking system contention
-- LOGCACHE_ACCESS: Transaction log bottleneck
```

**Step 4: Analyze Memory Dumps**
```cmd
REM Use WinDbg or SQLDiag to analyze dump
REM Look for:
REM 1. Which thread was non-yielding
REM 2. Call stack of the stuck thread
REM 3. Wait chain analysis

REM In WinDbg:
.sympath SRV*c:\symbols*https://msdl.microsoft.com/download/symbols
.reload
!analyze -v
~*kb  -- Callstacks of all threads
!mex.sqlspinlock  -- Check spinlock contention (requires MEX extension)
```

**Common Resolutions:**

**Resolution 1: External Process Interference**
```sql
-- Exclude SQL Server files from antivirus scanning
-- Add to exclusions:
-- - Data files (*.mdf, *.ndf, *.ldf)
-- - Backup files (*.bak, *.trn)
-- - All SQL directories
```

**Resolution 2: Driver/Hardware Issues**
```powershell
# Check Windows Event Log for hardware errors
Get-EventLog -LogName System -EntryType Error -Newest 100 |
    Where-Object {$_.Source -like "*disk*" -or $_.Source -like "*storage*"}

# Update storage and network drivers
# Test hardware: memory (memtest), disk (chkdsk), CPU (stress tests)
```

**Resolution 3: CLR Code Issues**
```sql
-- Identify CLR assemblies
SELECT
    a.name,
    a.permission_set_desc,
    a.is_visible,
    a.create_date,
    a.modify_date
FROM sys.assemblies a
WHERE a.is_user_defined = 1

-- Review CLR code for:
-- 1. Infinite loops
-- 2. Long-running operations
-- 3. External calls
-- 4. Unmanaged code

-- Disable problematic CLR if identified
ALTER ASSEMBLY [AssemblyName] WITH PERMISSION_SET = SAFE
```

**Resolution 4: SQL Server Bug/Cumulative Update**
```sql
-- Check SQL Server version
SELECT @@VERSION

-- Check for known bugs in Connect/KB articles
-- Apply latest Cumulative Update
-- Test in non-production first
```

**Prevention:**
```sql
-- Set up alert for non-yielding scheduler
USE msdb
GO
EXEC sp_add_alert
    @name = N'Non-Yielding Scheduler Alert',
    @message_id = 0,
    @severity = 17,  -- Non-yielding errors are severity 17
    @enabled = 1,
    @delay_between_responses = 900,  -- 15 minutes
    @include_event_description_in = 1

-- Create XE session to track quantum violations
CREATE EVENT SESSION NonYieldingScheduler
ON SERVER
ADD EVENT sqlos.scheduler_monitor_non_yielding_ring_buffer_recorded(
    ACTION(sqlserver.sql_text, sqlserver.session_id)
)
ADD TARGET package0.event_file(SET filename=N'NonYieldingScheduler.xel')

-- Monitor scheduler health regularly
-- Schedule job to check sys.dm_os_schedulers every 15 minutes
```

**Key Points from mssqlwiki.com:**
- Non-yielding scheduler is SERIOUS - indicates thread hung for 60+ seconds
- Always generate memory dump when it occurs (automatic since SQL 2012)
- 90% of cases are external: antivirus, drivers, hardware
- 10% are SQL bugs - check KB articles and apply CUs
- Analyze dump files with debugger for root cause

---

### Q43: Explain memory pressure in SQL Server. How do you identify it and what are the resolution strategies?

**Answer:**

**Types of Memory Pressure:**
1. **Internal Memory Pressure:** SQL Server needs more memory than max server memory setting
2. **External Memory Pressure:** OS or other applications consuming memory
3. **Memory Clerk Pressure:** Specific component consuming excessive memory

**Diagnostic:**

**Step 1: Check Overall Memory State**
```sql
-- Check current memory clerks
SELECT TOP 20
    type AS clerk_type,
    name,
    SUM(pages_kb) / 1024 AS memory_mb,
    SUM(pages_kb) * 100.0 / (SELECT SUM(pages_kb) FROM sys.dm_os_memory_clerks) AS memory_pct
FROM sys.dm_os_memory_clerks
GROUP BY type, name
ORDER BY SUM(pages_kb) DESC

-- Check buffer pool distribution
SELECT
    CASE database_id
        WHEN 32767 THEN 'ResourceDB'
        ELSE DB_NAME(database_id)
    END AS database_name,
    COUNT(*) * 8 / 1024 AS buffer_mb,
    COUNT(*) * 100.0 / (SELECT COUNT(*) FROM sys.dm_os_buffer_descriptors) AS buffer_pct
FROM sys.dm_os_buffer_descriptors
GROUP BY database_id
ORDER BY COUNT(*) DESC

-- Check memory grants
SELECT
    mg.session_id,
    mg.request_id,
    mg.requested_memory_kb / 1024 AS requested_mb,
    mg.granted_memory_kb / 1024 AS granted_mb,
    mg.used_memory_kb / 1024 AS used_mb,
    mg.max_used_memory_kb / 1024 AS max_used_mb,
    mg.query_cost,
    mg.timeout_sec,
    mg.resource_semaphore_id,
    mg.wait_time_ms,
    mg.is_next_candidate,
    s.program_name,
    t.text AS query_text
FROM sys.dm_exec_query_memory_grants mg
INNER JOIN sys.dm_exec_sessions s ON mg.session_id = s.session_id
CROSS APPLY sys.dm_exec_sql_text(mg.sql_handle) t
ORDER BY mg.granted_memory_kb DESC
```

**Step 2: Check for Memory Pressure Indicators**
```sql
-- Check RESOURCE_SEMAPHORE waits (memory grant waits)
SELECT
    wait_type,
    waiting_tasks_count,
    wait_time_ms,
    max_wait_time_ms,
    signal_wait_time_ms
FROM sys.dm_os_wait_stats
WHERE wait_type = 'RESOURCE_SEMAPHORE'

-- Check memory notifications (memory pressure events)
SELECT
    CONVERT(XML, record) AS notification_xml
FROM sys.dm_os_ring_buffers
WHERE ring_buffer_type = 'RING_BUFFER_RESOURCE_MONITOR'
ORDER BY timestamp DESC

-- Parse for low memory notifications:
-- <MemoryRecord>
--   <MemoryUtilization>...</MemoryUtilization>
--   <IndicatorsProcess>...</IndicatorsProcess> (< 100 = memory pressure)
-- </MemoryRecord>

-- Check page life expectancy (PLE)
SELECT
    object_name,
    counter_name,
    instance_name,
    cntr_value AS page_life_expectancy_seconds,
    cntr_value / 60 AS page_life_expectancy_minutes
FROM sys.dm_os_performance_counters
WHERE object_name LIKE '%Buffer Manager%'
  AND counter_name = 'Page life expectancy'

-- PLE < 300 seconds (5 min) indicates memory pressure
-- Modern guideline: PLE should be >= (Max Server Memory GB) * 5
```

**Step 3: Identify Memory Consumers**
```sql
-- Check plan cache size
SELECT
    objtype AS cached_object_type,
    COUNT(*) AS number_of_plans,
    SUM(CAST(size_in_bytes AS BIGINT)) / 1024 / 1024 AS size_mb,
    AVG(usecounts) AS avg_use_count
FROM sys.dm_exec_cached_plans
GROUP BY objtype
ORDER BY SUM(CAST(size_in_bytes AS BIGINT)) DESC

-- Find large plans
SELECT TOP 20
    cp.objtype,
    cp.cacheobjtype,
    cp.size_in_bytes / 1024 AS size_kb,
    cp.usecounts,
    SUBSTRING(st.text, 1, 500) AS query_text
FROM sys.dm_exec_cached_plans cp
CROSS APPLY sys.dm_exec_sql_text(cp.plan_handle) st
ORDER BY cp.size_in_bytes DESC

-- Check for memory-consuming indexes (columnstore, in-memory OLTP)
SELECT
    OBJECT_NAME(i.object_id) AS table_name,
    i.name AS index_name,
    i.type_desc,
    SUM(ps.used_page_count) * 8 / 1024 AS used_mb
FROM sys.dm_db_partition_stats ps
INNER JOIN sys.indexes i ON ps.object_id = i.object_id AND ps.index_id = i.index_id
WHERE i.type IN (5, 6)  -- Columnstore indexes
GROUP BY i.object_id, i.name, i.type_desc
ORDER BY SUM(ps.used_page_count) DESC
```

**Resolution Strategies:**

**Resolution 1: Increase max server memory (if possible)**
```sql
-- Check current setting
SELECT
    name,
    value,
    value_in_use,
    minimum,
    maximum,
    description
FROM sys.configurations
WHERE name = 'max server memory (MB)'

-- Set appropriate max server memory
-- Leave 4-8 GB for OS on servers with < 32 GB RAM
-- Leave 10-15% for OS on servers with > 32 GB RAM
EXEC sp_configure 'max server memory (MB)', 61440  -- 60 GB
RECONFIGURE
```

**Resolution 2: Clear caches (temporary relief)**
```sql
-- Clear procedure cache (causes recompilations)
DBCC FREEPROCCACHE

-- Clear specific database from buffer pool
DBCC FLUSHPROCINDB(database_id)

-- Clear all clean pages from buffer pool (DANGEROUS in production)
CHECKPOINT
DBCC DROPCLEANBUFFERS

-- Better: Clear specific cache store
DBCC FREESYSTEMCACHE('SQL Plans')
```

**Resolution 3: Optimize memory-consuming queries**
```sql
-- Find queries with large memory grants
SELECT TOP 20
    qs.sql_handle,
    qs.plan_handle,
    qs.total_grant_kb / 1024 AS total_grant_mb,
    qs.last_grant_kb / 1024 AS last_grant_mb,
    qs.max_grant_kb / 1024 AS max_grant_mb,
    qs.execution_count,
    SUBSTRING(st.text,
        (qs.statement_start_offset / 2) + 1,
        ((CASE qs.statement_end_offset
            WHEN -1 THEN DATALENGTH(st.text)
            ELSE qs.statement_end_offset
        END - qs.statement_start_offset) / 2) + 1) AS query_text,
    qp.query_plan
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st
CROSS APPLY sys.dm_exec_query_plan(qs.plan_handle) qp
ORDER BY qs.max_grant_kb DESC

-- Reduce memory grants by:
-- 1. Updating statistics
-- 2. Adding appropriate indexes
-- 3. Using OPTION (MAXDOP 1) to reduce parallel plan memory
-- 4. Breaking large queries into smaller chunks
```

**Resolution 4: Resource Governor (limit memory per workload)**
```sql
-- Create resource pool with memory limits
CREATE RESOURCE POOL ReportingPool
WITH (
    MAX_MEMORY_PERCENT = 25,  -- Limit to 25% of SQL memory
    MIN_MEMORY_PERCENT = 5
)

-- Create workload group
CREATE WORKLOAD GROUP ReportingGroup
WITH (
    REQUEST_MAX_MEMORY_GRANT_PERCENT = 10  -- Max 10% per query
)
USING ReportingPool

-- Apply classifier function (shown in Q39)
ALTER RESOURCE GOVERNOR RECONFIGURE
```

**Resolution 5: Enable Resource Governor Memory Grant Feedback (SQL 2019+)**
```sql
-- Automatic adjustment of memory grants based on actual usage
-- Enabled by default in SQL 2019+ compatibility level 150
ALTER DATABASE SCOPED CONFIGURATION SET ROW_MODE_MEMORY_GRANT_FEEDBACK = ON
ALTER DATABASE SCOPED CONFIGURATION SET BATCH_MODE_MEMORY_GRANT_FEEDBACK = ON
```

**Prevention:**
```sql
-- Set up monitoring
CREATE EVENT SESSION MemoryPressure
ON SERVER
ADD EVENT sqlserver.memory_broker_ring_buffer_record,
ADD EVENT sqlserver.query_memory_grant_blocking,
ADD EVENT sqlserver.query_memory_grant_timeout
ADD TARGET package0.event_file(SET filename=N'MemoryPressure.xel')

-- Create alert for low page life expectancy
EXEC sp_add_alert
    @name = N'Low Page Life Expectancy',
    @message_id = 0,
    @severity = 0,
    @enabled = 1,
    @delay_between_responses = 600,
    @performance_condition = N'SQLServer:Buffer Manager|Page life expectancy||<|300'
```

---

### Q44: Your application reports slowness. You check and find Query Store shows plan regression for a critical query. How do you handle this?

**Answer:**

**Scenario:** Query that normally runs in 2 seconds suddenly takes 45 seconds due to plan change.

**Step 1: Identify Regressed Query**
```sql
-- Use standard Query Store catalog views for regression analysis; vendor helper views and columns vary by SQL Server release.
-- Alternative: Manual comparison
SELECT
    q.query_id,
    qt.query_sql_text,
    p.plan_id,
    rs.last_execution_time,
    rs.avg_duration / 1000.0 AS avg_duration_ms,
    rs.avg_cpu_time / 1000.0 AS avg_cpu_ms,
    rs.avg_logical_io_reads,
    rs.avg_physical_io_reads,
    rs.count_executions,
    CAST(p.query_plan AS XML) AS query_plan
FROM sys.query_store_query q
INNER JOIN sys.query_store_query_text qt ON q.query_text_id = qt.query_text_id
INNER JOIN sys.query_store_plan p ON q.query_id = p.query_id
INNER JOIN sys.query_store_runtime_stats rs ON p.plan_id = rs.plan_id
WHERE qt.query_sql_text LIKE '%YourCriticalQuery%'
ORDER BY q.query_id, rs.last_execution_time DESC
```

**Step 2: Analyze Plans**
```sql
-- Get plan details
SELECT
    p.plan_id,
    p.query_id,
    p.plan_type,
    p.compatibility_level,
    p.plan_forcing_type_desc,
    p.is_forced_plan,
    p.force_failure_count,
    p.last_force_failure_reason_desc,
    CAST(p.query_plan AS XML) AS query_plan,
    TRY_CAST(p.query_plan AS XML).value('(//StmtSimple/@StatementOptmLevel)[1]', 'VARCHAR(50)') AS optimization_level,
    TRY_CAST(p.query_plan AS XML).value('(//StmtSimple/@StatementEstRows)[1]', 'FLOAT') AS estimated_rows
FROM sys.query_store_plan p
WHERE p.query_id = @YourQueryId

-- Compare execution stats between plans
WITH PlanStats AS (
    SELECT
        p.plan_id,
        p.query_id,
        AVG(rs.avg_duration) / 1000 AS avg_duration_ms,
        AVG(rs.avg_cpu_time) / 1000 AS avg_cpu_ms,
        AVG(rs.avg_logical_io_reads) AS avg_logical_reads,
        AVG(rs.avg_rowcount) AS avg_rows,
        SUM(rs.count_executions) AS total_executions,
        MAX(rs.last_execution_time) AS last_used
    FROM sys.query_store_plan p
    INNER JOIN sys.query_store_runtime_stats rs ON p.plan_id = rs.plan_id
    WHERE p.query_id = @YourQueryId
    GROUP BY p.plan_id, p.query_id
)
SELECT * FROM PlanStats
ORDER BY last_used DESC
```

**Step 3: Force Good Plan**
```sql
-- Force the better-performing plan
EXEC sp_query_store_force_plan
    @query_id = 12345,
    @plan_id = 67890

-- Verify forcing
SELECT
    q.query_id,
    p.plan_id,
    p.is_forced_plan,
    p.force_failure_count,
    p.last_force_failure_reason_desc,
    qt.query_sql_text
FROM sys.query_store_query q
INNER JOIN sys.query_store_plan p ON q.query_id = p.query_id
INNER JOIN sys.query_store_query_text qt ON q.query_text_id = qt.query_text_id
WHERE p.is_forced_plan = 1
```

**Step 4: Root Cause Analysis**
```sql
-- Why did the plan regress? Check for:

-- 1. Statistics updates
SELECT
    OBJECT_NAME(s.object_id) AS table_name,
    s.name AS stats_name,
    sp.last_updated,
    sp.rows,
    sp.rows_sampled,
    sp.modification_counter
FROM sys.stats s
CROSS APPLY sys.dm_db_stats_properties(s.object_id, s.stats_id) sp
WHERE OBJECT_NAME(s.object_id) IN ('YourTables')
ORDER BY sp.modification_counter DESC

-- 2. Index changes
SELECT
    i.name AS index_name,
    OBJECT_NAME(i.object_id) AS table_name,
    i.type_desc,
    i.create_date,
    i.modify_date,
    i.is_disabled
FROM sys.indexes i
WHERE OBJECT_NAME(i.object_id) IN ('YourTables')
ORDER BY i.modify_date DESC

-- 3. Data volume changes
SELECT
    OBJECT_NAME(ps.object_id) AS table_name,
    SUM(ps.row_count) AS total_rows,
    SUM(ps.used_page_count) * 8 / 1024 AS used_mb
FROM sys.dm_db_partition_stats ps
WHERE OBJECT_NAME(ps.object_id) IN ('YourTables')
GROUP BY ps.object_id

-- 4. Parameter sniffing (check compiled vs runtime parameters in plan XML)
```

**Step 5: Long-term Fix (Optional)**
```sql
-- If plan forcing is temporary workaround, implement permanent fix:

-- Option A: Update statistics more frequently
CREATE STATISTICS stat_CustomerId ON Orders(CustomerId)
WITH FULLSCAN

UPDATE STATISTICS Orders WITH FULLSCAN

-- Option B: Add missing index (if recommended by plan)
CREATE NONCLUSTERED INDEX IX_Orders_CustomerDate
ON Orders(CustomerID, OrderDate)
INCLUDE (OrderTotal, Status)

-- Option C: Add query hint to code
-- OPTION (OPTIMIZE FOR (@CustomerID UNKNOWN))
-- OPTION (RECOMPILE)
-- OPTION (USE HINT('FORCE_LEGACY_CARDINALITY_ESTIMATION'))

-- Option D: Change compatibility level (if CE 120/130/140 issue)
ALTER DATABASE YourDB SET COMPATIBILITY_LEVEL = 130

-- Then unforce plan
EXEC sp_query_store_unforce_plan @query_id = 12345, @plan_id = 67890
```

**Prevention:**
```sql
-- Enable automatic plan correction (SQL 2017+)
ALTER DATABASE YourDB
SET AUTOMATIC_TUNING (FORCE_LAST_GOOD_PLAN = ON)

-- Query Store configuration
ALTER DATABASE YourDB SET QUERY_STORE = ON
ALTER DATABASE YourDB SET QUERY_STORE (
    OPERATION_MODE = READ_WRITE,
    DATA_FLUSH_INTERVAL_SECONDS = 900,
    INTERVAL_LENGTH_MINUTES = 60,
    MAX_STORAGE_SIZE_MB = 1024,
    QUERY_CAPTURE_MODE = AUTO,  -- Capture significant queries
    SIZE_BASED_CLEANUP_MODE = AUTO,  -- Auto cleanup when space low
    MAX_PLANS_PER_QUERY = 200,
    WAIT_STATS_CAPTURE_MODE = ON  -- SQL 2017+
)

-- Monitor regressions by comparing time windows in sys.query_store_runtime_stats joined to
-- sys.query_store_plan and sys.query_store_query. Avoid undocumented helper views.
```

**Query Store Maintenance:**
```sql
-- Clear stale data
ALTER DATABASE YourDB SET QUERY_STORE CLEAR ALL

-- Rebuild Query Store (corruption recovery)
ALTER DATABASE YourDB SET QUERY_STORE = OFF
ALTER DATABASE YourDB SET QUERY_STORE = ON

-- Check Query Store space usage
SELECT
    current_storage_size_mb,
    max_storage_size_mb,
    (current_storage_size_mb * 100.0 / max_storage_size_mb) AS pct_full,
    readonly_reason,
    actual_state_desc
FROM sys.database_query_store_options
```

**Best Practices:**
1. Always analyze WHY the plan regressed before forcing
2. Plan forcing is a temporary fix - find root cause
3. Use automatic plan correction in SQL 2017+
4. Keep Query Store size adequate (1-2 GB minimum for busy systems)
5. Monitor Query Store regularly for forced plans and failures

---

*[Questions 45-65 continue with topics including: Columnstore indexes, In-Memory OLTP, index fragmentation, missing index recommendations, MAXDOP tuning, TempDB optimization, wait statistics analysis, lock escalation, snapshot isolation, large data loads, partition switching, and advanced query optimization techniques]*

---

## Section 3: Wait Statistics, Blocking & Deadlocks

### Q66: Explain the top 10 wait types you encounter and how you troubleshoot each.

**Answer:**

**1. CXPACKET / CXCONSUMER (Parallel Query Coordination)**

**What it means:** Threads waiting to synchronize during parallel query execution

**Diagnostic:**
```sql
SELECT
    wait_type,
    wait_time_ms / 1000.0 / 60 AS wait_time_minutes,
    waiting_tasks_count,
    wait_time_ms / NULLIF(waiting_tasks_count, 0) AS avg_wait_ms
FROM sys.dm_os_wait_stats
WHERE wait_type IN ('CXPACKET', 'CXCONSUMER')
```

**Resolution:**
```sql
-- Check MAXDOP setting
SELECT name, value_in_use
FROM sys.configurations
WHERE name IN ('max degree of parallelism', 'cost threshold for parallelism')

-- Adjust MAXDOP (don't exceed 8 typically)
EXEC sp_configure 'max degree of parallelism', 4
EXEC sp_configure 'cost threshold for parallelism', 50
RECONFIGURE

-- Or add query hint
SELECT * FROM LargeTable
OPTION (MAXDOP 1)
```

---

**2. PAGEIOLATCH_SH / PAGEIOLATCH_EX (I/O Bottleneck)**

**What it means:** Waiting for data pages to be read from disk into memory

**Diagnostic:**
```sql
-- Check I/O latency
SELECT
    DB_NAME(vfs.database_id) AS database_name,
    mf.physical_name,
    vfs.num_of_reads,
    vfs.io_stall_read_ms,
    vfs.io_stall_read_ms / NULLIF(vfs.num_of_reads, 0) AS avg_read_latency_ms,
    vfs.num_of_writes,
    vfs.io_stall_write_ms,
    vfs.io_stall_write_ms / NULLIF(vfs.num_of_writes, 0) AS avg_write_latency_ms
FROM sys.dm_io_virtual_file_stats(NULL, NULL) vfs
JOIN sys.master_files mf ON vfs.database_id = mf.database_id
    AND vfs.file_id = mf.file_id
ORDER BY avg_read_latency_ms DESC

-- Target: < 10ms for data, < 5ms for log
```

**Resolution:**
- Move to faster storage (SSD/NVMe)
- Add more memory to cache more data
- Create missing indexes to reduce I/O
- Partition large tables
- Archive old data

---

**3. LCK_M_X / LCK_M_S (Lock Waits)**

**What it means:** Blocked by another session holding incompatible lock

**Diagnostic:**
```sql
-- Find blocking chains
SELECT
    blocking.session_id AS blocking_session,
    blocked.session_id AS blocked_session,
    blocked.wait_type,
    blocked.wait_time / 1000 AS wait_time_sec,
    blocked.wait_resource,
    blocking_text.text AS blocking_query,
    blocked_text.text AS blocked_query
FROM sys.dm_exec_requests blocked
INNER JOIN sys.dm_exec_requests blocking
    ON blocked.blocking_session_id = blocking.session_id
CROSS APPLY sys.dm_exec_sql_text(blocking.sql_handle) blocking_text
CROSS APPLY sys.dm_exec_sql_text(blocked.sql_handle) blocked_text
WHERE blocked.blocking_session_id > 0
```

**Resolution:**
```sql
-- Keep transactions short
BEGIN TRANSACTION
    UPDATE Table SET Col = Value WHERE ID = 1  -- Quick update
COMMIT

-- Use WITH (NOLOCK) for read queries (if dirty reads acceptable)
SELECT * FROM Table WITH (NOLOCK)

-- Enable READ_COMMITTED_SNAPSHOT for row versioning
ALTER DATABASE YourDB SET READ_COMMITTED_SNAPSHOT ON

-- Add index to reduce lock duration
CREATE INDEX IX_Table_FilterColumn ON Table(FilterColumn)
```

---

**4. WRITELOG (Transaction Log Hardening)**

**What it means:** Waiting for transaction log records to be written to disk

**Diagnostic:**
```sql
-- Check log file I/O latency
SELECT
    DB_NAME(vfs.database_id) AS database_name,
    mf.physical_name AS log_file_path,
    vfs.num_of_writes,
    vfs.io_stall_write_ms,
    vfs.io_stall_write_ms / NULLIF(vfs.num_of_writes, 0) AS avg_write_latency_ms
FROM sys.dm_io_virtual_file_stats(NULL, NULL) vfs
JOIN sys.master_files mf ON vfs.database_id = mf.database_id
    AND vfs.file_id = mf.file_id
WHERE mf.type = 1  -- Log files only
ORDER BY avg_write_latency_ms DESC

-- Target: < 5ms
```

**Resolution:**
- Move transaction log to dedicated fast storage (SSD/NVMe)
- Reduce VLF count:
```sql
-- Check VLF count
DBCC LOGINFO

-- If > 50 VLFs, rebuild log:
USE master
ALTER DATABASE YourDB SET RECOVERY SIMPLE
DBCC SHRINKFILE (YourDB_log, 1)
ALTER DATABASE YourDB SET RECOVERY FULL
ALTER DATABASE YourDB MODIFY FILE (NAME = YourDB_log, SIZE = 25GB, FILEGROWTH = 8GB)
```
- Consider delayed durability for non-critical workloads:
```sql
ALTER DATABASE YourDB SET DELAYED_DURABILITY = ALLOWED
COMMIT TRANSACTION WITH (DELAYED_DURABILITY = ON)
```

---

**5. ASYNC_NETWORK_IO (Client not consuming results)**

**What it means:** SQL Server waiting for client application to consume result set

**Diagnostic:**
```sql
SELECT
    s.session_id,
    s.login_name,
    s.host_name,
    s.program_name,
    r.wait_type,
    r.wait_time / 1000 AS wait_seconds,
    t.text AS query_text
FROM sys.dm_exec_requests r
INNER JOIN sys.dm_exec_sessions s ON r.session_id = s.session_id
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
WHERE r.wait_type = 'ASYNC_NETWORK_IO'
```

**Resolution:**
- Application should process results faster
- Use paging (OFFSET/FETCH) instead of returning millions of rows:
```sql
-- Bad: SELECT * FROM LargeTable (returns 10M rows)
-- Good:
SELECT * FROM LargeTable
ORDER BY ID
OFFSET 0 ROWS FETCH NEXT 1000 ROWS ONLY
```
- Check for network bandwidth issues
- Use appropriate data types (don't return VARCHAR(MAX) if VARCHAR(50) suffices)

---

**6. SOS_SCHEDULER_YIELD (CPU Pressure)**

**What it means:** Thread yielding CPU to other threads (CPU saturation)

**Diagnostic:**
```sql
-- Check runnable queue
SELECT
    scheduler_id,
    current_tasks_count,
    runnable_tasks_count,  -- Should be near 0
    current_workers_count
FROM sys.dm_os_schedulers
WHERE scheduler_id < 255
ORDER BY runnable_tasks_count DESC

-- Check signal wait percentage (CPU pressure indicator)
SELECT
    CAST(SUM(signal_wait_time_ms) * 100.0 / SUM(wait_time_ms) AS NUMERIC(20,2)) AS signal_wait_pct
FROM sys.dm_os_wait_stats
-- Goal: < 10-15%
```

**Resolution:**
- Optimize CPU-intensive queries (see Q39)
- Add indexes
- Reduce parallelism (MAXDOP)
- Add more CPU cores
- Implement Resource Governor

---

**7. PAGELATCH_UP (Allocation Contention)**

**What it means:** Contention on allocation pages (PFS, SGAM, GAM) - often tempdb

**Diagnostic:**
```sql
SELECT
    session_id,
    wait_type,
    wait_duration_ms / 1000.0 AS wait_seconds,
    blocking_session_id,
    resource_description
FROM sys.dm_os_waiting_tasks
WHERE wait_type LIKE 'PAGELATCH%'
ORDER BY wait_duration_ms DESC

-- Check which database
-- wait_resource format: DatabaseID:FileID:PageID
```

**Resolution:**
- For tempdb: Add more tempdb files (see Q38)
- Enable trace flags 1117 and 1118 (default SQL 2016+)
- For user database: Check for hotspot inserts (sequential key inserts)
```sql
-- Instead of IDENTITY(1,1), use:
-- 1. NEWSEQUENTIALID() for GUIDs
-- 2. SEQUENCE with CYCLE
-- 3. Hash partitioning
```

---

**8. RESOURCE_SEMAPHORE (Memory Grant Wait)**

**What it means:** Query waiting for memory grant to execute

**Diagnostic:**
```sql
SELECT
    r.session_id,
    r.wait_type,
    r.wait_time / 1000 AS wait_seconds,
    r.granted_query_memory * 8 / 1024 AS granted_mb,
    mg.requested_memory_kb / 1024 AS requested_mb,
    mg.ideal_memory_kb / 1024 AS ideal_mb,
    t.text AS query_text,
    qp.query_plan
FROM sys.dm_exec_requests r
LEFT JOIN sys.dm_exec_query_memory_grants mg ON r.session_id = mg.session_id
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
CROSS APPLY sys.dm_exec_query_plan(r.plan_handle) qp
WHERE r.wait_type = 'RESOURCE_SEMAPHORE'
```

**Resolution:**
```sql
-- Add more memory to server
-- Or optimize queries to need less memory:
-- 1. Add indexes (reduce sorts)
-- 2. Reduce result set size
-- 3. Use appropriate data types
-- 4. Add MIN_GRANT_PERCENT hint
SELECT * FROM LargeTable
OPTION (MIN_GRANT_PERCENT = 5)
```

---

**9. PREEMPTIVE_OS_PIPEOPS (Backup/Restore)**

**What it means:** Backup or restore operation in progress

**Diagnostic:**
```sql
-- Check backup progress
SELECT
    session_id,
    command,
    percent_complete,
    CAST(((estimated_completion_time / 1000.0) / 60.0) AS NUMERIC(10,2)) AS est_minutes_remaining,
    start_time,
    database_id,
    DB_NAME(database_id) AS database_name
FROM sys.dm_exec_requests
WHERE command IN ('BACKUP DATABASE', 'RESTORE DATABASE', 'BACKUP LOG')
```

**Resolution:**
- Use backup compression
- Backup to multiple files (parallel)
- Use faster storage for backups
```sql
-- Compressed backup to 4 files
BACKUP DATABASE YourDB
TO DISK = 'Path1\backup1.bak',
   DISK = 'Path2\backup2.bak',
   DISK = 'Path3\backup3.bak',
   DISK = 'Path4\backup4.bak'
WITH COMPRESSION, STATS = 10
```

---

**10. OLEDB (Linked Server / External Resource)**

**What it means:** Waiting for response from linked server or external resource

**Diagnostic:**
```sql
SELECT
    s.session_id,
    r.wait_type,
    r.wait_time / 1000 AS wait_seconds,
    r.command,
    t.text AS query_text
FROM sys.dm_exec_requests r
INNER JOIN sys.dm_exec_sessions s ON r.session_id = s.session_id
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
WHERE r.wait_type = 'OLEDB'
```

**Resolution:**
- Optimize linked server queries
- Use OPENQUERY instead of 4-part names:
```sql
-- Bad (causes full table scan on linked server):
SELECT * FROM LinkedServer.DB.dbo.Table WHERE ID = 1

-- Good (pushes WHERE to linked server):
SELECT * FROM OPENQUERY(LinkedServer,
    'SELECT * FROM DB.dbo.Table WHERE ID = 1'
)
```
- Create indexed views on linked server
- Consider importing data instead of querying live

---

**General Wait Statistics Query:**
```sql
-- Comprehensive wait stats analysis
WITH Waits AS (
    SELECT
        wait_type,
        wait_time_ms / 1000.0 AS wait_time_seconds,
        wait_time_ms / 1000.0 / 60.0 AS wait_time_minutes,
        waiting_tasks_count,
        wait_time_ms / NULLIF(waiting_tasks_count, 0) AS avg_wait_ms,
        100.0 * wait_time_ms / SUM(wait_time_ms) OVER() AS wait_pct,
        ROW_NUMBER() OVER(ORDER BY wait_time_ms DESC) AS rn
    FROM sys.dm_os_wait_stats
    WHERE wait_type NOT IN (  -- Filter benign waits
        'CLR_SEMAPHORE', 'LAZYWRITER_SLEEP', 'RESOURCE_QUEUE',
        'SLEEP_TASK', 'SLEEP_SYSTEMTASK', 'SQLTRACE_BUFFER_FLUSH',
        'WAITFOR', 'LOGMGR_QUEUE', 'CHECKPOINT_QUEUE',
        'REQUEST_FOR_DEADLOCK_SEARCH', 'XE_TIMER_EVENT', 'BROKER_TO_FLUSH',
        'BROKER_TASK_STOP', 'CLR_MANUAL_EVENT', 'CLR_AUTO_EVENT',
        'DISPATCHER_QUEUE_SEMAPHORE', 'FT_IFTS_SCHEDULER_IDLE_WAIT',
        'XE_DISPATCHER_WAIT', 'XE_DISPATCHER_JOIN', 'SQLTRACE_INCREMENTAL_FLUSH_SLEEP',
        'HADR_FILESTREAM_IOMGR_IOCOMPLETION', 'DIRTY_PAGE_POLL', 'SP_SERVER_DIAGNOSTICS_SLEEP'
    )
    AND wait_time_ms > 0
)
SELECT
    wait_type,
    CAST(wait_time_seconds AS DECIMAL(12,2)) AS wait_seconds,
    CAST(wait_time_minutes AS DECIMAL(12,2)) AS wait_minutes,
    waiting_tasks_count AS wait_count,
    CAST(avg_wait_ms AS DECIMAL(12,2)) AS avg_wait_ms,
    CAST(wait_pct AS DECIMAL(5,2)) AS pct_of_total,
    CAST(SUM(wait_pct) OVER(ORDER BY wait_time_ms DESC) AS DECIMAL(5,2)) AS running_pct
FROM Waits
WHERE rn <= 20
ORDER BY wait_time_ms DESC
```

---

---

### Q67: You have a blocking chain with 50+ sessions waiting. Walk through your immediate response and long-term prevention.

**Answer:**

**Immediate Response:**

**Step 1: Identify Blocking Chain Leader (Head Blocker)**
```sql
-- Quick view of blocking chain
SELECT
    blocking.session_id AS blocking_spid,
    blocked.session_id AS blocked_spid,
    blocking.wait_type AS blocking_wait,
    blocked.wait_type AS blocked_wait,
    blocked.wait_time / 1000 AS blocked_seconds,
    blocking_text.text AS blocking_query,
    blocked_text.text AS blocked_query,
    blocking_session.login_name AS blocking_user,
    blocking_session.program_name AS blocking_app,
    blocking_session.host_name AS blocking_host
FROM sys.dm_exec_requests blocked
INNER JOIN sys.dm_exec_requests blocking ON blocked.blocking_session_id = blocking.session_id
INNER JOIN sys.dm_exec_sessions blocking_session ON blocking.session_id = blocking_session.session_id
CROSS APPLY sys.dm_exec_sql_text(blocking.sql_handle) blocking_text
CROSS APPLY sys.dm_exec_sql_text(blocked.sql_handle) blocked_text
ORDER BY blocked.wait_time DESC

-- Find ultimate head blocker (SPID with blocking_session_id = 0)
WITH BlockingChain AS (
    SELECT
        session_id,
        blocking_session_id,
        wait_type,
        wait_time,
        wait_resource,
        1 AS level
    FROM sys.dm_exec_requests
    WHERE blocking_session_id <> 0

    UNION ALL

    SELECT
        r.session_id,
        r.blocking_session_id,
        r.wait_type,
        r.wait_time,
        r.wait_resource,
        bc.level + 1
    FROM sys.dm_exec_requests r
    INNER JOIN BlockingChain bc ON r.session_id = bc.blocking_session_id
)
SELECT
    bc.session_id,
    bc.blocking_session_id,
    bc.wait_type,
    bc.wait_time / 1000 AS wait_seconds,
    bc.level AS chain_depth,
    s.login_name,
    s.program_name,
    s.host_name,
    t.text AS current_query,
    r.status,
    r.command
FROM BlockingChain bc
INNER JOIN sys.dm_exec_sessions s ON bc.session_id = s.session_id
LEFT JOIN sys.dm_exec_requests r ON bc.session_id = r.session_id
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
ORDER BY bc.level, bc.wait_time DESC
```

**Step 2: Assess Impact**
```sql
-- Count blocked sessions and wait time
SELECT
    blocking_session_id,
    COUNT(*) AS blocked_count,
    SUM(wait_time) / 1000 AS total_blocked_seconds,
    MAX(wait_time) / 1000 AS max_blocked_seconds
FROM sys.dm_exec_requests
WHERE blocking_session_id <> 0
GROUP BY blocking_session_id
ORDER BY blocked_count DESC
```

**Step 3: Decision - Kill or Wait**
```sql
-- Check if head blocker is active or idle with open transaction
SELECT
    s.session_id,
    s.status,
    s.last_request_start_time,
    s.last_request_end_time,
    DATEDIFF(SECOND, s.last_request_end_time, GETDATE()) AS idle_seconds,
    t.open_transaction_count,
    r.command,
    r.percent_complete,
    r.estimated_completion_time / 1000 / 60 AS est_minutes_remaining,
    qt.text AS last_query
FROM sys.dm_exec_sessions s
LEFT JOIN sys.dm_exec_requests r ON s.session_id = r.session_id
LEFT JOIN sys.dm_exec_connections c ON s.session_id = c.session_id
LEFT JOIN (
        SELECT session_id, COUNT(*) AS open_transaction_count
        FROM sys.dm_tran_session_transactions
        GROUP BY session_id
    ) t ON s.session_id = t.session_id
OUTER APPLY sys.dm_exec_sql_text(c.most_recent_sql_handle) qt
WHERE s.session_id = @HeadBlockerSPID

-- Decision logic:
-- If idle with open transaction: KILL immediately
-- If running active query with high percent_complete: WAIT
-- If running long without progress: KILL after stakeholder approval
```

**Step 4: Kill Session (if appropriate)**
```sql
-- Before killing, capture state for analysis
SELECT * INTO #BlockingState FROM sys.dm_exec_requests
SELECT * INTO #SessionState FROM sys.dm_exec_sessions

-- Kill the head blocker
KILL @HeadBlockerSPID

-- WITH STATUSONLY to check rollback progress
KILL @HeadBlockerSPID WITH STATUSONLY
-- Output: "SPID 123: transaction rollback in progress. Estimated rollback completion: 15%"

-- Note: Rollback can take LONGER than original transaction
-- Large UPDATE with 1 million rows might take 30 min to rollback
```

**Long-term Prevention:**

**Prevention 1: Identify Root Cause Queries**
```sql
-- Use Extended Events to capture blocking (better than Profiler)
CREATE EVENT SESSION Blocking_Tracker
ON SERVER
ADD EVENT sqlserver.blocked_process_report(
    WHERE duration > 30000000  -- 30 seconds (in microseconds)
),
ADD EVENT sqlserver.lock_escalation(
    ACTION(sqlserver.sql_text, sqlserver.session_id, sqlserver.database_name)
),
ADD EVENT sqlserver.lock_acquired(
    WHERE mode > 2  -- Exclude Sch-S and IS locks
    ACTION(sqlserver.sql_text, sqlserver.session_id)
)
ADD TARGET package0.ring_buffer(SET max_memory = 4096),
ADD TARGET package0.event_file(SET filename=N'Blocking_Tracker.xel', max_file_size=20)
WITH (MAX_DISPATCH_LATENCY = 5 SECONDS)

ALTER EVENT SESSION Blocking_Tracker ON SERVER STATE = START

-- Enable blocked process threshold (required for blocked_process_report)
EXEC sp_configure 'blocked process threshold (s)', 30  -- Alert after 30 sec
RECONFIGURE
```

**Prevention 2: Code Optimization**
```sql
-- Common blocking patterns to fix:

-- Pattern 1: Missing index causing scan locks entire table
-- Bad: SELECT * FROM Orders WHERE OrderDate = '2026-01-01'
-- Fix: CREATE INDEX IX_Orders_OrderDate ON Orders(OrderDate)

-- Pattern 2: Explicit transactions held too long
-- Bad:
BEGIN TRANSACTION
    -- User interaction here (waiting for input)
    UPDATE Inventory SET Qty = Qty - 1
    -- More user interaction
COMMIT TRANSACTION

-- Good:
-- Prepare all data first, then quick transaction
BEGIN TRANSACTION
    UPDATE Inventory SET Qty = Qty - 1
COMMIT TRANSACTION

-- Pattern 3: SELECT with UPDLOCK unnecessarily
-- Bad: SELECT * FROM Orders WITH (UPDLOCK) WHERE ...
-- Good: Only use UPDLOCK if you're actually updating later

-- Pattern 4: Large batch updates without chunking
-- Bad: UPDATE Orders SET Status = 'Archived' WHERE OrderDate < '2020-01-01'  -- 10M rows
-- Good: Chunk it
DECLARE @BatchSize INT = 1000
WHILE 1 = 1
BEGIN
    UPDATE TOP (@BatchSize) Orders
    SET Status = 'Archived'
    WHERE OrderDate < '2020-01-01'
      AND Status <> 'Archived'

    IF @@ROWCOUNT < @BatchSize BREAK
    WAITFOR DELAY '00:00:01'  -- Breathing room
END
```

**Prevention 3: Isolation Level Tuning**
```sql
-- Consider READ COMMITTED SNAPSHOT ISOLATION (RCSI)
-- Readers don't block writers, writers don't block readers
ALTER DATABASE YourDB SET READ_COMMITTED_SNAPSHOT ON

-- Or SNAPSHOT isolation for point-in-time consistency
ALTER DATABASE YourDB SET ALLOW_SNAPSHOT_ISOLATION ON

-- In queries:
SET TRANSACTION ISOLATION LEVEL SNAPSHOT
SELECT * FROM Orders WHERE ...

-- Caution: Increases tempdb usage (version store)
```

**Prevention 4: Proactive Monitoring**
```sql
-- Create alert for blocking > threshold
USE msdb
GO
EXEC sp_add_alert
    @name = N'Blocking Alert - 30+ Sessions',
    @message_id = 0,
    @severity = 0,
    @enabled = 1,
    @delay_between_responses = 300,  -- 5 minutes
    @performance_condition = N'SQLServer:General Statistics|Processes blocked||>|30'

-- Schedule job to check blocking every 5 minutes
CREATE PROCEDURE dbo.usp_CheckBlocking
AS
BEGIN
    DECLARE @BlockedCount INT

    SELECT @BlockedCount = COUNT(*)
    FROM sys.dm_exec_requests
    WHERE blocking_session_id <> 0
      AND wait_time > 60000  -- 60 seconds

    IF @BlockedCount > 10
    BEGIN
        -- Send alert email
        DECLARE @Body VARCHAR(MAX)
        SET @Body = 'Blocking detected: ' + CAST(@BlockedCount AS VARCHAR(10)) + ' sessions blocked'

        EXEC msdb.dbo.sp_send_dbmail
            @recipients = 'dba@example.invalid',
            @subject = 'SQL Server Blocking Alert',
            @body = @Body
    END
END
```

**Analysis of Blocking History:**
```sql
-- Parse Extended Events file for patterns
SELECT
    event_xml.value('(event/@timestamp)[1]', 'DATETIME') AS event_time,
    event_xml.value('(event/data[@name="blocked_process"]/value/blocked-process-report/blocked-process/process/@waitresource)[1]', 'VARCHAR(100)') AS wait_resource,
    event_xml.value('(event/data[@name="blocked_process"]/value/blocked-process-report/blocked-process/process/@waittime)[1]', 'BIGINT') / 1000 AS wait_seconds,
    event_xml.value('(event/data[@name="blocked_process"]/value/blocked-process-report/blocking-process/process/@spid)[1]', 'INT') AS blocking_spid,
    event_xml.value('(event/data[@name="blocked_process"]/value/blocked-process-report/blocking-process/process/inputbuf)[1]', 'VARCHAR(MAX)') AS blocking_query,
    event_xml.value('(event/data[@name="blocked_process"]/value/blocked-process-report/blocked-process/process/inputbuf)[1]', 'VARCHAR(MAX)') AS blocked_query
FROM (
    SELECT CAST(event_data AS XML) AS event_xml
    FROM sys.fn_xe_file_target_read_file('Blocking_Tracker*.xel', NULL, NULL, NULL)
) AS events
WHERE event_xml.exist('/event[@name="blocked_process_report"]') = 1
ORDER BY event_time DESC
```

---

### Q68: Explain the difference between blocking and deadlocking. How do you troubleshoot a deadlock?

**Answer:**

**Definitions:**
- **Blocking:** Session A holds lock on Resource 1; Session B waits for Resource 1. Session B is blocked but will eventually proceed when A releases lock.
- **Deadlock:** Session A holds Resource 1, waits for Resource 2; Session B holds Resource 2, waits for Resource 1. Circular dependency - SQL Server must kill one session (deadlock victim).

**Deadlock Example:**
```
Time    Session 1                       Session 2
----    ---------                       ---------
T1      BEGIN TRAN
T2      UPDATE Orders SET ...           BEGIN TRAN
         WHERE OrderID = 100
T3                                      UPDATE OrderDetails SET ...
                                         WHERE OrderID = 200
T4      UPDATE OrderDetails SET ...
         WHERE OrderID = 200
         (WAITS for Session 2)
T5                                      UPDATE Orders SET ...
                                         WHERE OrderID = 100
                                         (WAITS for Session 1)
T6      DEADLOCK DETECTED!
        Session 2 chosen as victim
        Msg 1205: Deadlock victim
```

**Troubleshooting Deadlocks:**

**Step 1: Capture Deadlock Graphs**
```sql
-- Method 1: Enable trace flag 1222 (text format in errorlog)
DBCC TRACEON(1222, -1)

-- Method 2: Use Extended Events (preferred - XML format)
CREATE EVENT SESSION Deadlock_Tracker
ON SERVER
ADD EVENT sqlserver.xml_deadlock_report(
    ACTION(sqlserver.session_id, sqlserver.sql_text, sqlserver.database_name)
)
ADD TARGET package0.event_file(SET filename=N'Deadlock_Tracker.xel', max_file_size=50)
WITH (MAX_DISPATCH_LATENCY = 5 SECONDS)

ALTER EVENT SESSION Deadlock_Tracker ON SERVER STATE = START

-- Method 3: System Health session (enabled by default)
SELECT
    XEvent.query('(event/data/value/deadlock)[1]') AS DeadlockGraph,
    XEvent.value('(event/@timestamp)[1]', 'DATETIME') AS event_time
FROM (
    SELECT CAST(target_data AS XML) AS TargetData
    FROM sys.dm_xe_session_targets st
    INNER JOIN sys.dm_xe_sessions s ON s.address = st.event_session_address
    WHERE s.name = 'system_health'
      AND st.target_name = 'ring_buffer'
) AS Data
CROSS APPLY TargetData.nodes('//RingBufferTarget/event[@name="xml_deadlock_report"]') AS XEventData(XEvent)
ORDER BY event_time DESC
```

**Step 2: Analyze Deadlock Graph**
```xml
<!-- Example deadlock graph structure -->
<deadlock>
  <victim-list>
    <victimProcess id="process123"/>  <!-- This session was killed -->
  </victim-list>
  <process-list>
    <process id="process123" ...>
      <inputbuf>UPDATE Orders SET Status = 'Shipped' WHERE OrderID = @P1</inputbuf>
      <executionStack>
        <frame procname="dbo.usp_ShipOrder" .../>
      </executionStack>
    </process>
    <process id="process456" ...>
      <inputbuf>UPDATE OrderDetails SET Qty = @P1 WHERE OrderDetailID = @P2</inputbuf>
    </process>
  </process-list>
  <resource-list>
    <keylock hobtid="72057594051690496" dbid="7" objectname="Orders" indexname="PK_Orders" mode="X" ...>
      <owner-list>
        <owner id="process456"/>
      </owner-list>
      <waiter-list>
        <waiter id="process123" mode="X"/>
      </waiter-list>
    </keylock>
    <keylock hobtid="72057594051755008" dbid="7" objectname="OrderDetails" indexname="PK_OrderDetails" mode="X" ...>
      <owner-list>
        <owner id="process123"/>
      </owner-list>
      <waiter-list>
        <waiter id="process456" mode="X"/>
      </waiter-list>
    </keylock>
  </resource-list>
</deadlock>
```

**Step 3: Parse Deadlock Graph Programmatically**
```sql
-- Read and parse deadlock graphs from Extended Events
;WITH DeadlockData AS (
    SELECT
        CAST(event_data AS XML) AS DeadlockGraph,
        CAST(event_data AS XML).value('(event/@timestamp)[1]', 'DATETIME') AS DeadlockTime
    FROM sys.fn_xe_file_target_read_file('Deadlock_Tracker*.xel', NULL, NULL, NULL)
    WHERE object_name = 'xml_deadlock_report'
)
SELECT
    DeadlockTime,
    DeadlockGraph.value('(/event/data/value/deadlock/victim-list/victimProcess/@id)[1]', 'VARCHAR(50)') AS VictimProcess,
    Process.value('(@id)[1]', 'VARCHAR(50)') AS ProcessID,
    Process.value('(@hostname)[1]', 'VARCHAR(100)') AS HostName,
    Process.value('(@loginname)[1]', 'VARCHAR(100)') AS LoginName,
    Process.value('(@isolationlevel)[1]', 'VARCHAR(50)') AS IsolationLevel,
    Process.value('(inputbuf)[1]', 'VARCHAR(MAX)') AS QueryText,
    ResourceLock.value('(@objectname)[1]', 'VARCHAR(200)') AS LockedObject,
    ResourceLock.value('(@indexname)[1]', 'VARCHAR(200)') AS LockedIndex,
    ResourceLock.value('(@mode)[1]', 'VARCHAR(10)') AS LockMode
FROM DeadlockData
CROSS APPLY DeadlockGraph.nodes('//process-list/process') AS Processes(Process)
CROSS APPLY DeadlockGraph.nodes('//resource-list/keylock') AS Resources(ResourceLock)
ORDER BY DeadlockTime DESC
```

**Common Deadlock Resolutions:**

**Resolution 1: Access Resources in Same Order**
```sql
-- CAUSE: Transactions access tables in different order
-- Session 1: Orders → OrderDetails
-- Session 2: OrderDetails → Orders

-- FIX: Both sessions access in same order
-- Both: Orders → OrderDetails

-- Bad Procedure 1:
CREATE PROCEDURE usp_UpdateOrder_Bad
AS
BEGIN
    UPDATE Orders SET ... WHERE OrderID = @OrderID
    UPDATE OrderDetails SET ... WHERE OrderID = @OrderID
END

-- Bad Procedure 2:
CREATE PROCEDURE usp_UpdateOrderDetails_Bad
AS
BEGIN
    UPDATE OrderDetails SET ... WHERE OrderID = @OrderID
    UPDATE Orders SET ... WHERE OrderID = @OrderID  -- Different order!
END

-- Good: Both procedures access Orders first, then OrderDetails
```

**Resolution 2: Reduce Transaction Scope**
```sql
-- Bad: Long transaction
BEGIN TRANSACTION
    SELECT @Count = COUNT(*) FROM Orders  -- Read 1
    -- Business logic...
    WAITFOR DELAY '00:00:05'  -- Simulated processing
    UPDATE Orders SET Status = 'Processed'  -- Write
    -- More business logic...
COMMIT TRANSACTION

-- Good: Minimal transaction scope
SELECT @Count = COUNT(*) FROM Orders  -- Outside transaction
-- Business logic...

BEGIN TRANSACTION
    UPDATE Orders SET Status = 'Processed'  -- Only critical writes in transaction
COMMIT TRANSACTION
```

**Resolution 3: Use Appropriate Indexes**
```sql
-- Deadlock due to range lock on non-indexed column
-- Query: UPDATE Orders SET Status = 'Shipped' WHERE OrderDate = '2026-01-01'
-- Without index, takes range lock on entire table
-- With index, takes key lock on specific rows

CREATE NONCLUSTERED INDEX IX_Orders_OrderDate
ON Orders(OrderDate)
INCLUDE (Status)
```

**Resolution 4: Lower Isolation Level**
```sql
-- READ COMMITTED SNAPSHOT ISOLATION prevents reader/writer deadlocks
ALTER DATABASE YourDB SET READ_COMMITTED_SNAPSHOT ON

-- Or use NOLOCK hint (dirty reads acceptable)
SELECT * FROM Orders WITH (NOLOCK)
WHERE OrderDate = @Date

-- Or use READPAST (skip locked rows)
SELECT * FROM Orders WITH (READPAST)
WHERE Status = 'Pending'
```

**Resolution 5: Implement Retry Logic**
```sql
-- In application code:
CREATE PROCEDURE usp_ProcessOrder
    @OrderID INT,
    @MaxRetries INT = 3
AS
BEGIN
    DECLARE @Attempt INT = 0
    DECLARE @Error INT

    WHILE @Attempt < @MaxRetries
    BEGIN
        BEGIN TRY
            BEGIN TRANSACTION
                -- Your logic here
                UPDATE Orders SET Status = 'Processed' WHERE OrderID = @OrderID
            COMMIT TRANSACTION

            BREAK  -- Success, exit loop
        END TRY
        BEGIN CATCH
            IF ERROR_NUMBER() = 1205  -- Deadlock
            BEGIN
                SET @Attempt = @Attempt + 1
                ROLLBACK TRANSACTION
                WAITFOR DELAY '00:00:00.100'  -- 100ms delay
            END
            ELSE
            BEGIN
                THROW  -- Re-raise non-deadlock errors
            END
        END CATCH
    END
END
```

**Prevention & Monitoring:**
```sql
-- Create alert for frequent deadlocks
USE msdb
GO
EXEC sp_add_alert
    @name = N'Deadlock Alert',
    @message_id = 1205,  -- Deadlock victim error
    @severity = 0,
    @enabled = 1,
    @delay_between_responses = 60

-- Monitor deadlock frequency
SELECT
    CAST(XEventData.XEvent.value('(event/@timestamp)[1]', 'DATETIME') AS DATETIME) AS DeadlockTime
FROM (
    SELECT CAST(target_data AS XML) AS TargetData
    FROM sys.dm_xe_session_targets st
    INNER JOIN sys.dm_xe_sessions s ON s.address = st.event_session_address
    WHERE s.name = 'system_health'
) AS Data
CROSS APPLY TargetData.nodes('//RingBufferTarget/event[@name="xml_deadlock_report"]') AS XEventData(XEvent)
WHERE XEventData.XEvent.value('(event/@timestamp)[1]', 'DATETIME') > DATEADD(HOUR, -24, GETDATE())
ORDER BY DeadlockTime DESC
```

**Deadlock Priority:**
```sql
-- Control which session becomes victim (lower priority dies first)
SET DEADLOCK_PRIORITY LOW   -- -5
SET DEADLOCK_PRIORITY NORMAL  -- 0 (default)
SET DEADLOCK_PRIORITY HIGH  -- 5

-- Or numeric value
SET DEADLOCK_PRIORITY -10  -- Most likely victim
SET DEADLOCK_PRIORITY 10   -- Least likely victim

-- Use in low-priority background jobs
SET DEADLOCK_PRIORITY LOW
BEGIN TRANSACTION
    -- Archival or reporting query
COMMIT TRANSACTION
```

---

## Section 4: Indexing & Execution Plans

### Q86: You find a query with a key lookup (bookmark lookup) in the execution plan costing 60% of the query. Explain what this is and how to fix it.

**Answer:**

**What is a Key Lookup:**
A key lookup (or RID lookup) occurs when:
1. Non-clustered index is used for initial seek/scan
2. Query needs additional columns not in that index
3. SQL Server must go back to clustered index (or heap) to get missing columns
4. Results in extra I/O - often major performance bottleneck

**Example:**
```sql
-- Table structure
CREATE TABLE Orders (
    OrderID INT PRIMARY KEY,  -- Clustered index
    CustomerID INT,
    OrderDate DATETIME,
    OrderTotal MONEY,
    Status VARCHAR(20),
    ShipAddress VARCHAR(500)
)

-- Existing index
CREATE NONCLUSTERED INDEX IX_Orders_CustomerID ON Orders(CustomerID)

-- Problem query
SELECT OrderID, CustomerID, OrderDate, OrderTotal, Status
FROM Orders
WHERE CustomerID = 12345

-- Execution plan:
-- 1. Index Seek on IX_Orders_CustomerID (finds matching rows) - 10% cost
-- 2. Key Lookup on PK_Orders (gets OrderDate, OrderTotal, Status) - 60% cost  ← PROBLEM
-- 3. Nested Loops Join - 30% cost
```

**Diagnostic:**
```sql
-- Find queries with key lookups
SELECT
    qs.execution_count,
    qs.total_worker_time / 1000 AS total_cpu_ms,
    qs.total_elapsed_time / 1000 AS total_duration_ms,
    SUBSTRING(st.text,
        (qs.statement_start_offset / 2) + 1,
        ((CASE qs.statement_end_offset
            WHEN -1 THEN DATALENGTH(st.text)
            ELSE qs.statement_end_offset
        END - qs.statement_start_offset) / 2) + 1) AS query_text,
    qp.query_plan,
    -- Check for Key Lookup in plan
    qp.query_plan.value('(//RelOp[@PhysicalOp="Key Lookup"]/@EstimatedTotalSubtreeCost)[1]', 'FLOAT') AS KeyLookupCost
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st
CROSS APPLY sys.dm_exec_query_plan(qs.plan_handle) qp
WHERE qp.query_plan.exist('//RelOp[@PhysicalOp="Key Lookup"]') = 1
ORDER BY qs.total_worker_time DESC
```

**Fix Option 1: Add INCLUDE Columns (Covering Index)**
```sql
-- Add needed columns to INCLUDE clause
DROP INDEX IX_Orders_CustomerID ON Orders
GO

CREATE NONCLUSTERED INDEX IX_Orders_CustomerID_Covering
ON Orders(CustomerID)
INCLUDE (OrderDate, OrderTotal, Status)

-- Now plan is:
-- 1. Index Seek on IX_Orders_CustomerID_Covering - 100% cost
-- No key lookup needed!

-- Pros: Eliminates key lookup completely
-- Cons: Larger index size, more maintenance overhead on writes
```

**Fix Option 2: Make Index Covering with Key Columns**
```sql
-- Alternative: Add columns to key (if they're useful for seeks/sorts)
CREATE NONCLUSTERED INDEX IX_Orders_CustomerID_OrderDate
ON Orders(CustomerID, OrderDate)
INCLUDE (OrderTotal, Status)

-- Benefits:
-- 1. Can seek on CustomerID AND OrderDate
-- 2. Can sort by OrderDate without extra sort operation
-- 3. Covers the query
```

**Fix Option 3: Accept Key Lookup (if appropriate)**
```sql
-- Key lookups are acceptable when:
-- 1. Query returns very few rows (< 1% of table)
-- 2. Creating covering index would be too large
-- 3. Index maintenance cost outweighs benefit

-- Example: If query returns 1-10 rows from 10M row table
-- Key lookup is efficient (10 seeks vs scanning 10M rows)

-- Check tipping point
SELECT
    i.name AS index_name,
    SUM(ps.row_count) AS total_rows,
    SUM(ps.used_page_count) * 8 / 1024 AS index_size_mb
FROM sys.dm_db_partition_stats ps
INNER JOIN sys.indexes i ON ps.object_id = i.object_id AND ps.index_id = i.index_id
WHERE i.object_id = OBJECT_ID('Orders')
GROUP BY i.name

-- General guideline:
-- < 1-2% of rows: Key lookup is fine
-- > 5% of rows: Create covering index
-- Between: Test both approaches
```

**Fix Option 4: Clustered Index Redesign (rare)**
```sql
-- If table has many queries with key lookups, consider:
-- Changing clustered index to most common access pattern

-- Current: Clustered on OrderID (identity)
-- Problem: Most queries filter by CustomerID

-- Solution: Cluster on CustomerID (if appropriate)
-- Caution: Major change, affects all queries and inserts!

CREATE UNIQUE CLUSTERED INDEX IX_Orders_CustomerID_OrderID
ON Orders(CustomerID, OrderID)  -- OrderID for uniqueness

DROP INDEX PK_Orders ON Orders  -- Remove old clustered PK
GO

-- Now queries by CustomerID are clustered seeks (very fast)
-- Trade-off: Inserts are scattered instead of sequential
```

**Monitoring Impact:**
```sql
-- Before and after comparison
SET STATISTICS IO ON
SET STATISTICS TIME ON

-- Before fix:
SELECT OrderID, CustomerID, OrderDate, OrderTotal, Status
FROM Orders
WHERE CustomerID = 12345

-- Output might show:
-- Table 'Orders'. Scan count 1, logical reads 100
-- (Key lookup causes extra reads)

-- After fix (covering index):
-- Table 'Orders'. Scan count 0, logical reads 3
-- (Only index reads, no key lookup)
```

**Index Usage Stats:**
```sql
-- Verify index is being used after creation
SELECT
    OBJECT_NAME(ius.object_id) AS table_name,
    i.name AS index_name,
    ius.user_seeks,
    ius.user_scans,
    ius.user_lookups,
    ius.user_updates,
    ius.last_user_seek,
    ius.last_user_scan,
    ius.last_user_lookup
FROM sys.dm_db_index_usage_stats ius
INNER JOIN sys.indexes i ON ius.object_id = i.object_id AND ius.index_id = i.index_id
WHERE ius.database_id = DB_ID()
  AND OBJECT_NAME(ius.object_id) = 'Orders'
ORDER BY ius.user_seeks + ius.user_scans + ius.user_lookups DESC
```

**Best Practices:**
1. Don't blindly add all columns to INCLUDE - increases index size
2. Prioritize frequently executed queries for covering indexes
3. Monitor index maintenance overhead (fragmentation, update cost)
4. Use Query Store to validate improvement before/after
5. Consider filtered indexes for subset of data:
```sql
CREATE NONCLUSTERED INDEX IX_Orders_Active
ON Orders(CustomerID)
INCLUDE (OrderDate, OrderTotal)
WHERE Status IN ('Pending', 'Processing')  -- Only active orders
```

---

### Q87: Explain index fragmentation. When should you rebuild vs reorganize an index?

**Answer:**

**Index Fragmentation Types:**

1. **Logical Fragmentation (External):** Pages in index are not in correct physical order. SQL Server must jump around disk to read sequential pages.

2. **Internal Fragmentation (Page Fullness):** Pages are not fully utilized. If page is only 50% full, SQL Server reads twice as many pages as needed.

**Causes:**
- INSERT/UPDATE/DELETE operations
- Page splits (when new row doesn't fit on page)
- Fill factor settings
- Random GUID clustered keys (bad practice)

**Check Fragmentation:**
```sql
-- Check fragmentation for all indexes in database
SELECT
    OBJECT_NAME(ips.object_id) AS table_name,
    i.name AS index_name,
    ips.index_type_desc,
    ips.alloc_unit_type_desc,
    ips.index_depth,
    ips.index_level,
    ips.page_count,
    ips.record_count,
    ips.avg_fragmentation_in_percent,
    ips.avg_page_space_used_in_percent,
    ips.fragment_count,
    ips.avg_fragment_size_in_pages
FROM sys.dm_db_index_physical_stats(
    DB_ID(), NULL, NULL, NULL, 'DETAILED'  -- 'LIMITED' for faster scan
) ips
INNER JOIN sys.indexes i ON ips.object_id = i.object_id AND ips.index_id = i.index_id
WHERE ips.index_id > 0  -- Exclude heaps
  AND ips.page_count > 100  -- Ignore small indexes
ORDER BY ips.avg_fragmentation_in_percent DESC
```

**Rebuild vs Reorganize Decision Matrix:**

| Fragmentation % | Action | Method | Impact |
|-----------------|--------|--------|--------|
| < 10% | None | - | - |
| 10-30% | Reorganize | ALTER INDEX REORGANIZE | Online, but brief blocking is possible |
| > 30% | Rebuild | ALTER INDEX REBUILD | Faster, more thorough |
| > 60% | Rebuild (priority) | ALTER INDEX REBUILD | Critical |

**Reorganize (Online Operation with Locking Caveats):**
```sql
-- Reorganize single index
ALTER INDEX IX_Orders_CustomerID ON Orders REORGANIZE

-- Reorganize all indexes on table
ALTER INDEX ALL ON Orders REORGANIZE

-- Pros:
-- - Online, but schema locks and lock contention can still cause blocking
-- - Uses minimal log space
-- - Can be stopped/resumed
-- - Good for smaller fragmentation (10-30%)

-- Cons:
-- - Less thorough than rebuild
-- - Doesn't update statistics
-- - Slower than rebuild for high fragmentation
```

**Rebuild (Can Be Online or Offline):**
```sql
-- Rebuild single index (offline - locks table)
ALTER INDEX IX_Orders_CustomerID ON Orders REBUILD

-- Rebuild online only when supported by the exact SQL Server edition,
-- version, index type, and options in use. Verify current product documentation.
ALTER INDEX IX_Orders_CustomerID ON Orders
REBUILD WITH (ONLINE = ON)

-- Rebuild with options
ALTER INDEX IX_Orders_CustomerID ON Orders
REBUILD WITH (
    ONLINE = ON,
    MAXDOP = 4,  -- Limit parallelism
    SORT_IN_TEMPDB = ON,  -- Use tempdb for sort (faster if tempdb on fast storage)
    FILLFACTOR = 90,  -- Leave 10% free space to reduce future splits
    DATA_COMPRESSION = PAGE  -- Compress to save space
)

-- Rebuild all indexes on table
ALTER INDEX ALL ON Orders REBUILD

-- Pros:
-- - Most thorough defragmentation
-- - Updates statistics automatically
-- - Faster than reorganize for high fragmentation
-- - Can apply compression and change fillfactor

-- Cons:
-- - Offline rebuild locks table (blocks queries)
-- - Online rebuild requires Enterprise Edition (pre-2019)
-- - Uses significant log space (full logging)
-- - Requires free space (roughly 1.2x index size)
```

**Resumable Index Rebuild (SQL 2017+):**
```sql
-- Start resumable rebuild
ALTER INDEX IX_Orders_CustomerID ON Orders
REBUILD WITH (
    ONLINE = ON,
    RESUMABLE = ON,
    MAX_DURATION = 60  -- Auto-pause after 60 minutes
)

-- Pause rebuild (if needed during business hours)
ALTER INDEX IX_Orders_CustomerID ON Orders PAUSE

-- Resume rebuild (during maintenance window)
ALTER INDEX IX_Orders_CustomerID ON Orders RESUME

-- Abort rebuild
ALTER INDEX IX_Orders_CustomerID ON Orders ABORT

-- Check resumable operations
SELECT
    name AS index_name,
    OBJECT_NAME(object_id) AS table_name,
    state_desc,
    percent_complete,
    page_count,
    start_time,
    last_pause_time
FROM sys.index_resumable_operations
```

**Automated Maintenance Script:**
```sql
-- Intelligent index maintenance based on fragmentation level
DECLARE @Database VARCHAR(255) = DB_NAME()
DECLARE @Table VARCHAR(255)
DECLARE @Index VARCHAR(255)
DECLARE @Fragmentation FLOAT
DECLARE @PageCount INT
DECLARE @SQL VARCHAR(4000)

DECLARE index_cursor CURSOR FOR
SELECT
    OBJECT_NAME(ips.object_id) AS table_name,
    i.name AS index_name,
    ips.avg_fragmentation_in_percent,
    ips.page_count
FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') ips
INNER JOIN sys.indexes i ON ips.object_id = i.object_id AND ips.index_id = i.index_id
WHERE ips.index_id > 0
  AND ips.page_count > 100  -- Skip small indexes
  AND ips.avg_fragmentation_in_percent > 10
  AND i.type IN (1, 2)  -- Clustered and non-clustered only
ORDER BY ips.avg_fragmentation_in_percent DESC

OPEN index_cursor

FETCH NEXT FROM index_cursor INTO @Table, @Index, @Fragmentation, @PageCount

WHILE @@FETCH_STATUS = 0
BEGIN
    SET @SQL = 'ALTER INDEX [' + @Index + '] ON [' + @Table + '] '

    IF @Fragmentation < 30
    BEGIN
        SET @SQL = @SQL + 'REORGANIZE'
        PRINT 'Reorganizing: ' + @Table + '.' + @Index + ' (' + CAST(@Fragmentation AS VARCHAR(10)) + '% fragmented)'
    END
    ELSE
    BEGIN
        SET @SQL = @SQL + 'REBUILD WITH (ONLINE = ON, MAXDOP = 4, SORT_IN_TEMPDB = ON)'
        PRINT 'Rebuilding: ' + @Table + '.' + @Index + ' (' + CAST(@Fragmentation AS VARCHAR(10)) + '% fragmented)'
    END

    EXEC(@SQL)

    -- Update statistics after reorganize (rebuild does it automatically)
    IF @Fragmentation < 30
    BEGIN
        EXEC('UPDATE STATISTICS [' + @Table + '] [' + @Index + '] WITH FULLSCAN')
    END

    FETCH NEXT FROM index_cursor INTO @Table, @Index, @Fragmentation, @PageCount
END

CLOSE index_cursor
DEALLOCATE index_cursor
```

**Special Considerations:**

**Columnstore Indexes:**
```sql
-- Check columnstore fragmentation
SELECT
    OBJECT_NAME(rgs.object_id) AS table_name,
    i.name AS index_name,
    rgs.partition_number,
    rgs.row_group_id,
    rgs.state_desc,  -- COMPRESSED, OPEN, CLOSED, TOMBSTONE
    rgs.total_rows,
    rgs.deleted_rows,
    CAST(rgs.deleted_rows * 100.0 / NULLIF(rgs.total_rows, 0) AS DECIMAL(5,2)) AS deleted_pct,
    rgs.size_in_bytes / 1024 / 1024 AS size_mb
FROM sys.dm_db_column_store_row_group_physical_stats rgs
INNER JOIN sys.indexes i ON rgs.object_id = i.object_id AND rgs.index_id = i.index_id
WHERE OBJECT_NAME(rgs.object_id) = 'FactSales'
ORDER BY deleted_pct DESC

-- Rebuild columnstore index
ALTER INDEX IX_FactSales_CCI ON FactSales
REBUILD WITH (MAXDOP = 4)

-- Or reorganize to compress OPEN row groups
ALTER INDEX IX_FactSales_CCI ON FactSales
REORGANIZE WITH (COMPRESS_ALL_ROW_GROUPS = ON)
```

**Preventing Fragmentation:**
```sql
-- Set appropriate fill factor on high-write indexes
CREATE INDEX IX_Orders_CustomerID ON Orders(CustomerID)
WITH (FILLFACTOR = 80)  -- Leave 20% free space for future inserts

-- Avoid GUID clustered keys (causes random page splits)
-- Bad:
CREATE TABLE Orders (
    OrderGUID UNIQUEIDENTIFIER DEFAULT NEWID() PRIMARY KEY CLUSTERED  -- Random!
)

-- Good:
CREATE TABLE Orders (
    OrderID INT IDENTITY PRIMARY KEY CLUSTERED,  -- Sequential
    OrderGUID UNIQUEIDENTIFIER DEFAULT NEWID() UNIQUE NONCLUSTERED
)

-- Or use NEWSEQUENTIALID() for GUIDs
CREATE TABLE Orders (
    OrderGUID UNIQUEIDENTIFIER DEFAULT NEWSEQUENTIALID() PRIMARY KEY CLUSTERED
)
```

**Monitoring:**
```sql
-- Create job to check fragmentation weekly
-- Alert if critical indexes exceed 60% fragmentation
SELECT
    OBJECT_NAME(ips.object_id) AS table_name,
    i.name AS index_name,
    ips.avg_fragmentation_in_percent
FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') ips
INNER JOIN sys.indexes i ON ips.object_id = i.object_id AND ips.index_id = i.index_id
WHERE ips.avg_fragmentation_in_percent > 60
  AND ips.page_count > 1000  -- Only large indexes
ORDER BY ips.avg_fragmentation_in_percent DESC
```

**Best Practices:**
1. Schedule maintenance during off-peak hours
2. Rebuild large indexes during weekends (use resumable if needed)
3. Reorganize during weekdays for maintenance
4. Always use SORT_IN_TEMPDB if tempdb is on fast storage
5. Monitor log file growth during rebuild operations
6. Consider online rebuilds for 24/7 systems (requires Enterprise Edition pre-2019)
7. Don't rebuild indexes smaller than 100-1000 pages (waste of resources)

---

*[Questions 88-100 continue with advanced topics including filtered indexes, indexed views, missing index recommendations, index usage statistics, partitioned indexes, full-text indexing, spatial indexes, XML indexes, execution plan operators, query hints, plan guides, and statistics maintenance]*

---

## Section 5: System Database Corruption & Recovery

### Q88: SQL Server cannot start. Error log shows "master database cannot be opened." How do you recover?

**Answer:**

**Critical Scenario:** Master database corruption prevents SQL Server from starting. This is a Level 1 emergency requiring immediate action.

**Symptoms:**
```
Error: 17204, Severity: 16, State: 1.
FCB::Open failed: Could not open file C:\...\master.mdf for file number 1.
OS error: 2(The system cannot find the path specified.).

Error: 5120, Severity: 16, State: 101.
Unable to open the physical file "C:\...\master.mdf". Operating system error 2.

Error: 17207, Severity: 16, State: 1.
FileMgr::StartPrimaryDataFiles: Operating system error 2(The system cannot find the path specified.)
occurred while creating or opening file 'C:\...\master.mdf'.
```

**Root Causes:**
- Hardware failure (disk corruption, bad sectors)
- Sudden system shutdown during write operations
- Malware or virus infection
- Accidental file deletion
- Storage subsystem failure

**Recovery Strategy:**

**Option 1: Restore Master Database from Backup (Preferred Method)**

**Step 1: Start SQL Server in Single-User Mode**
```cmd
REM Method A: Using net start
net start MSSQL$INSTANCENAME /mSQLCMD /T3608

REM Method B: Using sqlservr.exe directly
cd "C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\Binn"
sqlservr.exe -m -T3608

REM -m: Single-user mode (only one connection allowed)
REM -T3608: Do not recover any database except master
```

**Step 2: Connect via SQLCMD**
```cmd
sqlcmd -S localhost -E
```

**Step 3: Restore Master Database**
```sql
-- Restore master from backup
RESTORE DATABASE master
FROM DISK = 'C:\Backup\master_backup.bak'
WITH REPLACE

-- SQL Server will automatically shut down after restore completes
-- Message: "Server is shutting down to recover master database"
```

**Step 4: Restart SQL Server Normally**
```cmd
net start MSSQLSERVER
```

**Step 5: Verify System Objects**
```sql
-- Check system databases
SELECT name, state_desc, recovery_model_desc
FROM sys.databases
WHERE database_id <= 4

-- Verify logins
SELECT name, type_desc, create_date, modify_date
FROM sys.server_principals
WHERE type IN ('S', 'U')

-- Check linked servers
EXEC sp_linkedservers

-- Verify SQL Agent jobs (stored in msdb)
EXEC msdb.dbo.sp_help_job
```

---

**Option 2: Rebuild System Databases (When No Backup Available)**

**Critical Warning:** Rebuilding system databases will:
- Drop and recreate master, model, msdb, and tempdb
- **LOSE all user logins, linked servers, SQL Agent jobs, maintenance plans**
- Require restoration of msdb and model backups afterward
- All user databases will become "suspect" and need to be reattached

**Step 1: Locate Setup Media**
```cmd
REM Find SQL Server setup.exe
REM Typical locations:
REM C:\SQLServerInstallMedia\Setup.exe
REM D:\SQLServer2019\Setup.exe
```

**Step 2: Stop SQL Server Service**
```cmd
net stop MSSQLSERVER
net stop SQLSERVERAGENT
```

**Step 3: Run Rebuild Command**
```cmd
REM For default instance:
Setup.exe /QUIET /ACTION=REBUILDDATABASE /INSTANCENAME=MSSQLSERVER /SQLSYSADMINACCOUNTS="DOMAIN\Account"

REM For named instance:
Setup.exe /QUIET /ACTION=REBUILDDATABASE /INSTANCENAME=SQL2019 /SQLSYSADMINACCOUNTS="DOMAIN\Account"

REM Parameters:
REM /QUIET - Minimal UI
REM /ACTION=REBUILDDATABASE - Rebuild system databases
REM /INSTANCENAME - Instance to rebuild
REM /SQLSYSADMINACCOUNTS - Admin account(s)
REM /SAPWD - SA password (if using SQL authentication)
```

**Step 4: Rebuild Process Output**
```
Microsoft SQL Server Setup
Rebuilding system databases...
Progress: [################] 100%

System databases have been rebuilt successfully.
The following databases were rebuilt:
- master
- model
- msdb
- tempdb

WARNING: All customizations have been lost.
Please restore msdb and model from backups.
```

**Step 5: Start SQL Server**
```cmd
net start MSSQLSERVER
```

**Step 6: Restore MSDB and Model**
```sql
-- Restore msdb (contains jobs, maintenance plans, backup history)
USE master
GO
RESTORE DATABASE msdb
FROM DISK = 'C:\Backup\msdb_backup.bak'
WITH REPLACE
GO

-- Restore model (template for new databases)
RESTORE DATABASE model
FROM DISK = 'C:\Backup\model_backup.bak'
WITH REPLACE
GO
```

**Step 7: Reattach or Restore User Databases**
```sql
-- Option A: Attach existing user database files
CREATE DATABASE YourDatabase
ON (FILENAME = 'D:\Data\YourDatabase.mdf'),
   (FILENAME = 'D:\Data\YourDatabase_log.ldf')
FOR ATTACH
GO

-- Option B: Restore from backup
RESTORE DATABASE YourDatabase
FROM DISK = 'C:\Backup\YourDatabase.bak'
WITH RECOVERY
GO
```

**Step 8: Recreate Logins (from script backup)**
```sql
-- Recreate SQL logins
-- SQLCMD variable must be injected securely; keep password policy enabled
CREATE LOGIN [AppUser] WITH PASSWORD = '$(AppLoginPassword)', CHECK_POLICY = ON
GO

-- Recreate Windows logins
CREATE LOGIN [DOMAIN\WindowsUser] FROM WINDOWS
GO

-- Recreate linked servers
EXEC sp_addlinkedserver @server='LinkedServerName',
    @srvproduct='',
    @provider='SQLNCLI',
    @datasrc='RemoteServer'
GO
```

**Step 9: Synchronize Logins and Users**
```sql
-- Fix orphaned users (SIDs don't match after rebuild)
USE YourDatabase
GO

-- Show orphaned users
EXEC sp_change_users_login 'Report'

-- Fix orphaned users
EXEC sp_change_users_login 'Auto_Fix', 'UserName'

-- Or use ALTER USER (SQL 2012+)
ALTER USER [UserName] WITH LOGIN = [LoginName]
GO
```

---

**Option 3: Emergency Recovery Using Master.mdf Copy**

If you have a file-level backup of master.mdf and mastlog.ldf:

**Step 1: Stop SQL Server**
```cmd
net stop MSSQLSERVER
```

**Step 2: Replace Files**
```cmd
REM Navigate to data directory
cd "C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\DATA"

REM Backup corrupted files
move master.mdf master.mdf.corrupt
move mastlog.ldf mastlog.ldf.corrupt

REM Copy backup files
copy "\\BackupServer\SQLBackups\master.mdf" master.mdf
copy "\\BackupServer\SQLBackups\mastlog.ldf" mastlog.ldf
```

**Step 3: Start SQL Server**
```cmd
net start MSSQLSERVER
```

---

**Prevention:**

**1. Regular Backups**
```sql
-- Schedule daily master database backups
BACKUP DATABASE master
TO DISK = 'C:\Backup\master_' + CONVERT(VARCHAR(8), GETDATE(), 112) + '.bak'
WITH COMPRESSION, INIT

-- Backup after any configuration change:
-- - Creating/dropping logins
-- - Adding linked servers
-- - Changing server configuration
-- - Installing service packs/CUs
```

**2. File-Level Backups**
```powershell
# PowerShell script for file-level backup
$dataPath = "C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\DATA"
$backupPath = "\\BackupServer\SQLSystemDB"
$date = Get-Date -Format "yyyyMMdd"

# Stop SQL Server
Stop-Service MSSQLSERVER

# Copy system database files
Copy-Item "$dataPath\master.mdf" "$backupPath\master_$date.mdf"
Copy-Item "$dataPath\mastlog.ldf" "$backupPath\mastlog_$date.ldf"
Copy-Item "$dataPath\model.mdf" "$backupPath\model_$date.mdf"
Copy-Item "$dataPath\modellog.ldf" "$backupPath\modellog_$date.ldf"
Copy-Item "$dataPath\msdbdata.mdf" "$backupPath\msdbdata_$date.mdf"
Copy-Item "$dataPath\msdblog.ldf" "$backupPath\msdblog_$date.ldf"

# Start SQL Server
Start-Service MSSQLSERVER
```

**3. Document Configuration**
```sql
-- Script out logins
-- Use SSMS: Right-click server > Tasks > Generate Scripts > Logins

-- Document linked servers
SELECT * FROM sys.servers

-- Export SQL Agent jobs
-- Use SSMS: Right-click jobs > Script Job as > CREATE To > File

-- Keep rebuild script handy with documented parameters
```

**4. Test Recovery Procedures**
```
Schedule quarterly DR tests:
1. Restore master database in test environment
2. Practice rebuild procedure
3. Verify documentation accuracy
4. Update runbooks
```

---

### Q89: A user database is in SUSPECT mode. Walk through your complete troubleshooting and recovery process.

**Answer:**

**Symptoms:**
- Database shows "SUSPECT" status in SSMS
- Error accessing database: "Database 'DBName' cannot be opened due to inaccessible files or insufficient memory or disk space."
- Error 926, Level 14: "Database 'DBName' cannot be opened. It has been marked SUSPECT by recovery."

**Root Causes:**
- Database files corrupted (I/O errors, bad sectors)
- Transaction log corruption
- Insufficient disk space during recovery
- Unexpected shutdown during write operations
- Hardware failure

**Complete Recovery Process:**

**Step 1: Identify the Problem**
```sql
-- Check database status
SELECT
    name,
    state_desc,
    user_access_desc,
    recovery_model_desc,
    is_read_only
FROM sys.databases
WHERE name = 'YourDatabase'

-- Check error log for details
EXEC xp_readerrorlog 0, 1, N'YourDatabase'

-- Check for I/O errors
SELECT * FROM sys.dm_io_virtual_file_stats(DB_ID('YourDatabase'), NULL)

-- Review event log errors
EXEC xp_readerrorlog 0, 1, N'I/O error'
EXEC xp_readerrorlog 0, 1, N'Operating system error'
```

**Step 2: Set Database to EMERGENCY Mode**
```sql
-- EMERGENCY mode allows read-only access even when database is damaged
ALTER DATABASE YourDatabase SET EMERGENCY
GO

-- Verify
SELECT name, state_desc FROM sys.databases WHERE name = 'YourDatabase'
-- Output: state_desc = EMERGENCY
```

**Step 3: Run DBCC CHECKDB (Assessment)**
```sql
-- Check database integrity
DBCC CHECKDB('YourDatabase', NOINDEX) WITH NO_INFOMSGS, ALL_ERRORMSGS
GO

-- Example output with errors:
/*
Msg 8928, Level 16, State 1, Line 1
Object ID 245575913, index ID 0, partition ID 72057594038976512, alloc unit ID 72057594043170816 (type In-row data):
Page (1:156) could not be processed. See other errors for details.

Msg 8939, Level 16, State 98, Line 1
Table error: Object ID 245575913, index ID 0, partition ID 72057594038976512, alloc unit ID 72057594043170816 (type In-row data), page (1:156).
Test (IS_OFF (BUF_IOERR, pBUF->bstat)) failed. Values are 2057 and -4.

CHECKDB found 0 allocation errors and 2 consistency errors in database 'YourDatabase'.
repair_allow_data_loss is the minimum repair level for the errors found by DBCC CHECKDB.
*/
```

**Recovery Path Decision Tree:**

```
Has Valid Backup?
├─ YES → Restore from backup (OPTION A - BEST)
└─ NO → Does CHECKDB show errors?
    ├─ YES → Repair with data loss (OPTION B - DATA LOSS RISK)
    └─ NO → Simple mode reset (OPTION C)
```

---

**OPTION A: Restore from Backup (Preferred - No Data Loss)**

```sql
-- Set to single user to disconnect all users
ALTER DATABASE YourDatabase SET SINGLE_USER WITH ROLLBACK IMMEDIATE
GO

-- Restore full backup
RESTORE DATABASE YourDatabase
FROM DISK = 'C:\Backup\YourDatabase_Full.bak'
WITH NORECOVERY, REPLACE
GO

-- Restore latest differential (if available)
RESTORE DATABASE YourDatabase
FROM DISK = 'C:\Backup\YourDatabase_Diff.bak'
WITH NORECOVERY
GO

-- Restore transaction log backups
RESTORE LOG YourDatabase
FROM DISK = 'C:\Backup\YourDatabase_Log1.trn'
WITH NORECOVERY
GO

RESTORE LOG YourDatabase
FROM DISK = 'C:\Backup\YourDatabase_Log2.trn'
WITH RECOVERY  -- Final restore with RECOVERY
GO

-- Set to multi-user
ALTER DATABASE YourDatabase SET MULTI_USER
GO

-- Verify
SELECT name, state_desc FROM sys.databases WHERE name = 'YourDatabase'
-- state_desc should be ONLINE

-- Run CHECKDB to verify integrity
DBCC CHECKDB('YourDatabase') WITH NO_INFOMSGS
```

---

**OPTION B: Repair with Data Loss (Emergency Only)**

**Critical Warnings:**
- REPAIR_ALLOW_DATA_LOSS can delete rows, pages, or entire tables
- Data loss is permanent and unrecoverable
- Should ONLY be used when no backup exists
- Always try to export data first before repair

**Step 1: Export What You Can**
```sql
-- While in EMERGENCY mode, try to export critical tables
USE YourDatabase
GO

-- Check which tables are accessible
SELECT
    t.name AS table_name,
    t.object_id,
    SUM(p.rows) AS row_count
FROM sys.tables t
INNER JOIN sys.partitions p ON t.object_id = p.object_id
WHERE p.index_id IN (0,1)
GROUP BY t.name, t.object_id
ORDER BY t.name

-- Export accessible tables to new database
SELECT * INTO NewDatabase.dbo.Table1 FROM YourDatabase.dbo.Table1
SELECT * INTO NewDatabase.dbo.Table2 FROM YourDatabase.dbo.Table2
-- Repeat for all critical tables
```

**Step 2: Set to Single User Mode**
```sql
-- Required for repair operations
ALTER DATABASE YourDatabase SET SINGLE_USER WITH ROLLBACK IMMEDIATE
GO
```

**Step 3: Execute Repair**
```sql
-- Run repair (THIS WILL CAUSE DATA LOSS)
DBCC CHECKDB('YourDatabase', REPAIR_ALLOW_DATA_LOSS) WITH NO_INFOMSGS, ALL_ERRORMSGS
GO

-- Example output:
/*
Repair: Page (1:156) deallocated from object ID 245575913, index ID 0, partition ID 72057594038976512, alloc unit ID 72057594043170816 (type In-row data).
The page had test (IS_OFF (BUF_IOERR, pBUF->bstat)) failed. Values are 2057 and -4.

Repair: Deleted 145 rows from object ID 245575913, index ID 0, partition ID 72057594038976512.

DBCC results for 'YourDatabase'.
CHECKDB found 0 allocation errors and 0 consistency errors in database 'YourDatabase'.
Repair statement processed. Database is repaired.
*/
```

**Step 4: Verify Repair**
```sql
-- Run CHECKDB again to verify
DBCC CHECKDB('YourDatabase') WITH NO_INFOMSGS
GO

-- Should return: CHECKDB found 0 allocation errors and 0 consistency errors
```

**Step 5: Set Database Online**
```sql
-- Set back to normal mode
ALTER DATABASE YourDatabase SET MULTI_USER
GO

ALTER DATABASE YourDatabase SET ONLINE
GO

-- Verify
SELECT name, state_desc FROM sys.databases WHERE name = 'YourDatabase'
```

**Step 6: Assess Data Loss**
```sql
-- Compare row counts before/after
-- Check for missing tables or indexes
SELECT
    t.name AS table_name,
    SUM(p.rows) AS current_rows
FROM sys.tables t
INNER JOIN sys.partitions p ON t.object_id = p.object_id
WHERE p.index_id IN (0,1)
GROUP BY t.name
ORDER BY t.name

-- Check for missing indexes
SELECT
    OBJECT_NAME(object_id) AS table_name,
    name AS index_name,
    type_desc,
    is_disabled
FROM sys.indexes
WHERE object_id IN (SELECT object_id FROM sys.tables)
ORDER BY OBJECT_NAME(object_id), name

-- Rebuild all indexes (repair may have marked some as disabled)
EXEC sp_MSforeachtable 'ALTER INDEX ALL ON ? REBUILD'
GO

-- Update all statistics
EXEC sp_MSforeachtable 'UPDATE STATISTICS ? WITH FULLSCAN'
GO
```

---

**OPTION C: Simple Mode Reset (No Corruption Found)**

If CHECKDB shows no errors but database is still SUSPECT:

```sql
-- Take database offline
ALTER DATABASE YourDatabase SET OFFLINE WITH ROLLBACK IMMEDIATE
GO

-- Bring database back online
ALTER DATABASE YourDatabase SET ONLINE
GO

-- Or try emergency mode then online
ALTER DATABASE YourDatabase SET EMERGENCY
GO
ALTER DATABASE YourDatabase SET MULTI_USER
GO
ALTER DATABASE YourDatabase SET ONLINE
GO

-- Verify
DBCC CHECKDB('YourDatabase') WITH NO_INFOMSGS
```

---

**Post-Recovery Actions:**

**1. Immediate Backup**
```sql
-- Take full backup immediately after successful recovery
BACKUP DATABASE YourDatabase
TO DISK = 'C:\Backup\YourDatabase_PostRecovery.bak'
WITH COMPRESSION, INIT, STATS = 10
```

**2. Investigate Root Cause**
```sql
-- Check for hardware issues
-- Review Windows Event Log
EXEC xp_readerrorlog 0, 1, N'I/O error'
EXEC xp_readerrorlog 0, 1, N'sector'
EXEC xp_readerrorlog 0, 1, N'failed'

-- Check disk health
-- Run CHKDSK on affected drives (schedule during maintenance window)
```

**3. Monitor for Recurrence**
```sql
-- Create alert for database state changes
USE msdb
GO
EXEC sp_add_alert
    @name = N'Database Suspect Alert',
    @message_id = 926,  -- Database SUSPECT error
    @severity = 0,
    @enabled = 1,
    @include_event_description_in = 1

-- Schedule regular CHECKDB
-- Create SQL Agent job to run weekly:
EXEC sp_add_job @job_name = 'Weekly_CHECKDB_YourDatabase'
EXEC sp_add_jobstep
    @job_name = 'Weekly_CHECKDB_YourDatabase',
    @step_name = 'Run CHECKDB',
    @command = 'DBCC CHECKDB(''YourDatabase'') WITH NO_INFOMSGS'
```

**4. Document Incident**
```
Document in runbook:
- Date/time of incident
- Error messages observed
- Recovery method used
- Data loss assessment (if any)
- Root cause (if identified)
- Preventive measures implemented
```

---

### Q90: SQL Server won't start due to model database corruption. How do you recover when you can't restore model database normally?

**Answer:**

**Problem:** Model database is corrupted, and SQL Server cannot start because model is required for creating tempdb and recovering other databases.

**Error Messages:**
```
Error: 945, Severity: 14, State: 2.
Database 'model' cannot be opened due to inaccessible files or insufficient memory or disk space.

Error: 5123, Severity: 16, State: 1.
CREATE FILE encountered operating system error 3(The system cannot find the path specified.)
while attempting to open or create the physical file 'C:\...\model.mdf'.

System databases cannot be recovered. SQL Server cannot start.
```

**Recovery Process Using Trace Flag 3608:**

**Step 1: Start SQL Server with Trace Flag 3608**

Trace Flag 3608 makes SQL Server skip recovery of all databases except master.

```cmd
REM Method A: Start from command line
cd "C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\Binn"
sqlservr.exe -c -m -T3608

REM Method B: Add as startup parameter
REM 1. Open SQL Server Configuration Manager
REM 2. Right-click SQL Server service > Properties
REM 3. Startup Parameters tab > Add: -T3608
REM 4. Start service

REM Parameters:
REM -c: Start independently of Windows Service Control Manager
REM -m: Single-user mode
REM -T3608: Skip database recovery (except master)
```

**Step 2: Connect via SQLCMD**
```cmd
REM Open new command prompt
sqlcmd -S localhost -E
```

**Step 3: Check Database Status**
```sql
-- Check which databases are online
SELECT name, state_desc FROM sys.databases
GO

/* Expected output:
name      state_desc
-------   ----------
master    ONLINE
tempdb    <not created yet due to TF 3608>
model     RECOVERY_PENDING or SUSPECT
msdb      RECOVERY_PENDING (won't recover due to TF 3608)
*/
```

**Step 4: Set Model to EMERGENCY Mode**
```sql
-- Allow access to corrupted model database
ALTER DATABASE model SET EMERGENCY
GO

-- Set to single user
ALTER DATABASE model SET SINGLE_USER WITH ROLLBACK IMMEDIATE
GO
```

**Step 5: Restore Model Database**
```sql
-- Restore model from backup
RESTORE DATABASE model
FROM DISK = 'C:\Backup\model_backup.bak'
WITH REPLACE, RECOVERY
GO

-- Success message:
-- Processed 160 pages for database 'model', file 'modeldev' on file 1.
-- Processed 2 pages for database 'model', file 'modellog' on file 1.
-- RESTORE DATABASE successfully processed 162 pages in 0.123 seconds
```

**Step 6: Verify Model Database**
```sql
-- Check model status
SELECT name, state_desc FROM sys.databases WHERE name = 'model'
GO

-- Run CHECKDB
DBCC CHECKDB('model') WITH NO_INFOMSGS
GO

-- Check model objects
USE model
GO
SELECT name, type_desc FROM sys.objects WHERE is_ms_shipped = 1
GO
```

**Step 7: Shutdown SQL Server**
```sql
-- Shutdown to remove trace flag
SHUTDOWN WITH NOWAIT
GO
```

**Step 8: Start SQL Server Normally**
```cmd
REM Remove -T3608 from startup parameters
REM Start SQL Server service normally
net start MSSQLSERVER
```

**Step 9: Verify All Databases**
```sql
-- Check all databases came online
SELECT name, state_desc, recovery_model_desc
FROM sys.databases
GO

-- Test creating new database (uses model as template)
CREATE DATABASE TestDB
GO

DROP DATABASE TestDB
GO
```

---

**Alternative: Rebuild When No Backup Exists**

If you don't have a model database backup:

**Option 1: Copy Model from Another SQL Server Instance**

```powershell
# Prerequisites:
# - Another SQL Server instance with SAME VERSION and BUILD
# - Matching SQL Server version (e.g., both SQL Server 2019 RTM)

# Step 1: Stop both SQL Server instances
Stop-Service MSSQLSERVER

# Step 2: Copy model files from working instance
$sourcePath = "C:\SQLServer_Working\DATA"
$destPath = "C:\SQLServer_Corrupt\DATA"

Copy-Item "$sourcePath\model.mdf" "$destPath\model.mdf" -Force
Copy-Item "$sourcePath\modellog.ldf" "$destPath\modellog.ldf" -Force

# Step 3: Start SQL Server
Start-Service MSSQLSERVER
```

**Important:** SQL Server versions and build numbers MUST match exactly:
```sql
-- Check SQL Server version
SELECT @@VERSION
GO

-- Example output:
-- Microsoft SQL Server 2019 (RTM-CU14) (KB5007182) - 15.0.4188.2 (X64)
--                                                     ^^^^^^^^^^^^
--                                                     Must match exactly
```

---

**Option 2: Extract Model from SQL Server Installation Media**

```cmd
REM SQL Server setup includes pristine system database files

REM Step 1: Locate SQL Server installation templates
cd "C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\Binn\Templates"
dir model*.*

REM Step 2: Stop SQL Server
net stop MSSQLSERVER

REM Step 3: Copy template files to data directory
copy modeldev.mdf "C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\DATA\model.mdf" /Y
copy modellog.ldf "C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\DATA\modellog.ldf" /Y

REM Step 4: Start SQL Server
net start MSSQLSERVER
```

**Warning:** This gives you a "clean" model database, but you'll lose any customizations:
- User-defined objects in model
- Custom data types
- Default collation changes
- Filegroup modifications

---

**Option 3: Rebuild All System Databases**

If model is severely corrupted and above methods don't work:

```cmd
REM This will rebuild ALL system databases (master, model, msdb, tempdb)
REM WARNING: Requires restore of master and msdb afterward

Setup.exe /QUIET /ACTION=REBUILDDATABASE /INSTANCENAME=MSSQLSERVER /SQLSYSADMINACCOUNTS="DOMAIN\Admin"

REM After rebuild:
REM 1. Restore master database
REM 2. Restore msdb database
REM 3. Model will be fresh from setup
REM 4. Reattach/restore user databases
```

---

**Prevention:**

**1. Regular Backups**
```sql
-- Backup model after any customization
BACKUP DATABASE model
TO DISK = 'C:\Backup\model_backup.bak'
WITH COMPRESSION, INIT

-- Backup model after:
-- - Adding objects to model (tables, stored procedures)
-- - Changing default database options
-- - Modifying database files
```

**2. File-Level Backup**
```powershell
# Backup model files during maintenance
$backupPath = "\\BackupServer\SQL_SystemDB\model"
$date = Get-Date -Format "yyyyMMdd"

Stop-Service MSSQLSERVER
Copy-Item "C:\DATA\model.mdf" "$backupPath\model_$date.mdf"
Copy-Item "C:\DATA\modellog.ldf" "$backupPath\modellog_$date.ldf"
Start-Service MSSQLSERVER
```

**3. Document Model Customizations**
```sql
-- Script out all user objects in model
USE model
GO

-- List custom objects
SELECT name, type_desc, create_date
FROM sys.objects
WHERE is_ms_shipped = 0
ORDER BY type_desc, name

-- Script each object for disaster recovery
-- Keep scripts in version control
```

**4. Test Trace Flag 3608 Recovery**
```
Practice recovery process in test environment:
1. Simulate model corruption
2. Start with TF 3608
3. Restore model database
4. Verify recovery steps work
5. Document any issues
```

---

### Q91: The Resource database (mssqlsystemresource) is corrupted or missing. How do you recover it?

**Answer:**

**Background:**
The Resource database (mssqlsystemresource.mdf/mssqlsystemresource.ldf) is a hidden, read-only system database containing all system objects (DMVs, system stored procedures, system functions). It's critical for SQL Server operation but cannot be backed up using normal BACKUP commands.

**Error Messages:**
```
Error: 945, Severity: 14, State: 2.
Database 'mssqlsystemresource' cannot be opened due to inaccessible files.

Error: 922, Severity: 14, State: 1.
Database 'mssqlsystemresource' is being recovered. Waiting until recovery is finished.

SQL Server cannot start because the Resource database is missing or corrupt.
```

**Root Causes:**
- Accidental deletion of mssqlsystemresource files
- Disk corruption affecting Binn folder
- Incomplete SQL Server update/patch installation
- Installing multiple SQL Server updates without restart
- Storage subsystem failure

**Location:**
```
Default location:
C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\Binn\
Files:
- mssqlsystemresource.mdf
- mssqlsystemresource.ldf
```

**Recovery Methods:**

**Method 1: Repair SQL Server Installation**

```cmd
REM Run SQL Server setup in repair mode
REM This will restore pristine system files including resource database

Setup.exe /Q /ACTION=Repair /INSTANCENAME=MSSQLSERVER

REM Parameters:
REM /Q: Quiet mode (minimal UI)
REM /ACTION=Repair: Repair corrupted installation
REM /INSTANCENAME: Instance to repair

REM Repair process will:
REM 1. Validate installation files
REM 2. Replace corrupt/missing resource database
REM 3. Fix any other damaged system components
REM 4. Preserve user databases and configuration
```

**Method 2: Extract from Cumulative Update**

If setup media not available, extract resource DB from latest CU:

**Step 1: Download Matching Cumulative Update**
```powershell
# Important: Must match exact SQL Server build
# Check current build:
# SELECT @@VERSION

# Download matching CU from Microsoft Download Center
# Example: SQL Server 2019 CU14 - KB5007182
```

**Step 2: Extract CU Files**
```cmd
REM CU files are self-extracting executables
REM Extract to temporary location

SQLServer2019-KB5007182-x64.exe /x:C:\Temp\CU14Extract

REM Navigate to extracted files
cd C:\Temp\CU14Extract
```

**Step 3: Locate Resource Database Files**
```cmd
REM Resource DB files are in setup bootstrap folder
dir /s mssqlsystemresource.*

REM Typical location in extract:
REM C:\Temp\CU14Extract\x64\Setup\sql_engine_core_inst_msi\PFiles\SqlServr\MSSQL.X\MSSQL\Binn\
```

**Step 4: Stop SQL Server**
```cmd
net stop MSSQLSERVER
net stop SQLSERVERAGENT
```

**Step 5: Replace Resource Database**
```cmd
REM Backup existing (corrupt) files first
cd "C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\Binn"
rename mssqlsystemresource.mdf mssqlsystemresource.mdf.corrupt
rename mssqlsystemresource.ldf mssqlsystemresource.ldf.corrupt

REM Copy new files from extracted CU
copy "C:\Temp\CU14Extract\...\mssqlsystemresource.mdf" mssqlsystemresource.mdf
copy "C:\Temp\CU14Extract\...\mssqlsystemresource.ldf" mssqlsystemresource.ldf
```

**Step 6: Verify File Permissions**
```cmd
REM Resource DB files must have same permissions as other SQL files
REM SQL Server service account needs Read & Execute permissions

icacls mssqlsystemresource.mdf
REM Should show: NT SERVICE\MSSQLSERVER:(RX)
```

**Step 7: Start SQL Server**
```cmd
net start MSSQLSERVER
```

**Step 8: Verify Recovery**
```sql
-- Test system objects are accessible
SELECT @@VERSION
GO

-- Query system DMVs
SELECT * FROM sys.dm_exec_requests
GO

-- Test system stored procedures
EXEC sp_who2
GO

-- Verify resource database version matches master
SELECT SERVERPROPERTY('ResourceVersion') AS ResourceDBVersion,
       SERVERPROPERTY('ProductVersion') AS SQLServerVersion
GO

/* Output should show matching versions:
ResourceDBVersion    SQLServerVersion
-----------------    ----------------
15.0.4188.2         15.0.4188.2
*/
```

---

**Method 3: Copy from Another SQL Server Instance**

**Critical Requirements:**
- Same SQL Server major version (e.g., both 2019)
- **EXACT same build number (critical!)**
- Same edition (Standard, Enterprise)

```powershell
# Step 1: Verify build numbers match EXACTLY
# On source server:
sqlcmd -S SourceServer -Q "SELECT @@VERSION"

# On target server (if it starts):
sqlcmd -S TargetServer -Q "SELECT @@VERSION"

# Example:
# Both must show: 15.0.4188.2 (same down to patch level)

# Step 2: Stop target SQL Server
Stop-Service MSSQLSERVER -Force

# Step 3: Copy files
$sourcePath = "\\SourceServer\C$\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\Binn"
$targetPath = "C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\Binn"

Copy-Item "$sourcePath\mssqlsystemresource.mdf" "$targetPath\mssqlsystemresource.mdf" -Force
Copy-Item "$sourcePath\mssqlsystemresource.ldf" "$targetPath\mssqlsystemresource.ldf" -Force

# Step 4: Start SQL Server
Start-Service MSSQLSERVER
```

**Warning:** Mismatched versions will cause errors:
```
Error: 912, Severity: 21, State: 2.
Script level upgrade for database 'master' failed because upgrade step 'sqlagent100_msdb_upgrade.sql' encountered error 598.

The system cannot start because the Resource database version does not match this SQL Server executable.
```

---

**Method 4: File-Level Restore (If You Have Backup)**

Resource database **cannot** be backed up using T-SQL BACKUP command, but can be copied at file level:

```powershell
# If you have file-level backup of Binn folder:

# Stop SQL Server
Stop-Service MSSQLSERVER

# Restore files
$backupPath = "\\BackupServer\SQL_Binn_Backup\20260308"
$binnPath = "C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\Binn"

Copy-Item "$backupPath\mssqlsystemresource.mdf" "$binnPath\mssqlsystemresource.mdf" -Force
Copy-Item "$backupPath\mssqlsystemresource.ldf" "$binnPath\mssqlsystemresource.ldf" -Force

# Start SQL Server
Start-Service MSSQLSERVER
```

---

**Prevention:**

**1. File-Level Backup After Patches**
```powershell
# After applying CU/SP, backup resource database
$date = Get-Date -Format "yyyyMMdd_HHmmss"
$binnPath = "C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\Binn"
$backupPath = "\\BackupServer\SQL_ResourceDB_Backups"

# Create versioned backup
$version = (Invoke-Sqlcmd -Query "SELECT SERVERPROPERTY('ProductVersion') AS Ver").Ver
$backupFolder = "$backupPath\$version"
New-Item -Path $backupFolder -ItemType Directory -Force

Copy-Item "$binnPath\mssqlsystemresource.mdf" "$backupFolder\mssqlsystemresource_$date.mdf"
Copy-Item "$binnPath\mssqlsystemresource.ldf" "$backupFolder\mssqlsystemresource_$date.ldf"
```

**2. Verify Resource DB After Updates**
```sql
-- After every CU/SP installation:
-- Verify resource database version matches SQL Server
SELECT
    SERVERPROPERTY('ProductVersion') AS SQL_Version,
    SERVERPROPERTY('ProductLevel') AS Patch_Level,
    SERVERPROPERTY('ProductUpdateLevel') AS Update_Level,
    SERVERPROPERTY('ResourceVersion') AS Resource_DB_Version,
    SERVERPROPERTY('ResourceLastUpdateDateTime') AS Resource_Last_Update
GO

-- Versions should match:
-- SQL_Version = Resource_DB_Version
```

**3. Document Installed CUs/SPs**
```sql
-- Keep record of installed updates
SELECT
    SERVERPROPERTY('ProductVersion') AS Version,
    SERVERPROPERTY('ProductLevel') AS Service_Pack,
    SERVERPROPERTY('ProductUpdateLevel') AS Cumulative_Update,
    SERVERPROPERTY('ProductUpdateReference') AS KB_Article,
    SERVERPROPERTY('Edition') AS Edition
GO

-- Save output to documentation for disaster recovery
```

**4. Protect Binn Folder**
```cmd
REM Configure antivirus exclusions
REM Exclude from real-time scanning:
REM C:\Program Files\Microsoft SQL Server\MSSQL*.MSSQLSERVER\MSSQL\Binn\

REM Set folder permissions (prevent accidental deletion)
REM Remove Delete permission for administrators on:
REM - mssqlsystemresource.mdf
REM - mssqlsystemresource.ldf
```

**5. Test Recovery Procedure**
```
Quarterly DR drill:
1. Copy resource DB files to safe location
2. Simulate corruption (rename files)
3. Practice recovery using repair/extract method
4. Document time to recover
5. Update runbooks
```

---

---

## Section 6: Advanced Backup, Restore & Disaster Recovery

### Q92: A critical production server has crashed at 3:15 PM. You have full backup from 2 AM, differential from 2 PM, and transaction log backups every 15 minutes. Walk through the complete point-in-time recovery process to restore to 3:14 PM (one minute before the crash).

**Answer:**

**Scenario Context:**
- Database: ProductionDB (Full Recovery Model)
- Crash time: 3:15 PM
- Recovery target: 3:14 PM (before corrupting transaction)
- Available backups:
  - Full: 2:00 AM (ProductionDB_Full_0200.bak)
  - Differential: 2:00 PM (ProductionDB_Diff_1400.bak)
  - Transaction Logs: Every 15 minutes (latest: 3:00 PM)
  - Server crashed at 3:15 PM

**Critical Challenge:** The tail of the log (3:00 PM to 3:15 PM) has not been backed up yet!

---

**Step-by-Step Recovery Process:**

**Step 1: Assess the Situation**
```sql
-- Try to connect to SQL Server
-- If SQL Server is running, check database status
SELECT
    name,
    state_desc,
    log_reuse_wait_desc,
    recovery_model_desc
FROM sys.databases
WHERE name = 'ProductionDB'
GO

-- Possible states:
-- ONLINE: Database accessible (best case - can backup tail-log)
-- SUSPECT/RECOVERY_PENDING: Database damaged but server running
-- ERROR: Cannot connect - server completely down
```

**Step 2: Backup the Tail of the Log (Critical!)**

**Scenario A: SQL Server is Running (Database ONLINE or SUSPECT)**
```sql
-- Take tail-log backup WITH NORECOVERY
-- This prevents new transactions and preserves uncommitted work
BACKUP LOG ProductionDB
TO DISK = 'C:\Backup\ProductionDB_TailLog_20260309_1515.trn'
WITH NORECOVERY, NO_TRUNCATE, COMPRESSION, INIT, STATS = 10
GO

-- Success message:
-- Processed X pages for database 'ProductionDB', file 'ProductionDB_log' on file 1.
-- BACKUP LOG successfully processed pages in X seconds

-- The database is now in RESTORING state
```

**Scenario B: Database is SUSPECT or Inaccessible**
```sql
-- Use NO_TRUNCATE option (even if database suspect)
BACKUP LOG ProductionDB
TO DISK = 'C:\Backup\ProductionDB_TailLog_20260309_1515.trn'
WITH NO_TRUNCATE, NORECOVERY, COMPRESSION, INIT
GO

-- NO_TRUNCATE allows backup even when database files are inaccessible
```

**Scenario C: SQL Server Won't Start (Hardware Failure)**
```powershell
# If SQL Server won't start but files are accessible:
# Copy transaction log file to safe location
$dataPath = "E:\SQLData\ProductionDB_log.ldf"
$backupPath = "\\BackupServer\Emergency\ProductionDB_log_emergency.ldf"

Copy-Item $dataPath $backupPath

# Start SQL Server in single-user mode later to attempt tail-log backup
# sqlservr.exe -m -T3608
```

---

**Step 3: Set Database to RESTORING State (if not already)**
```sql
-- If database is ONLINE and you couldn't take tail-log backup:
ALTER DATABASE ProductionDB SET OFFLINE WITH ROLLBACK IMMEDIATE
GO

-- Or use RESTORE with NORECOVERY to put in restoring state
RESTORE DATABASE ProductionDB
FROM DISK = 'NUL'  -- Dummy restore to set state
WITH NORECOVERY
GO
```

---

**Step 4: Verify Backup Chain LSN Sequence**
```sql
-- Critical: Verify LSN chain is intact
RESTORE HEADERONLY
FROM DISK = 'C:\Backup\ProductionDB_Full_0200.bak'
GO

RESTORE HEADERONLY
FROM DISK = 'C:\Backup\ProductionDB_Diff_1400.bak'
GO

RESTORE HEADERONLY
FROM DISK = 'C:\Backup\ProductionDB_Log_1500.trn'
GO

RESTORE HEADERONLY
FROM DISK = 'C:\Backup\ProductionDB_TailLog_20260309_1515.trn'
GO

/* Key columns to check:
DatabaseBackupLSN: Starting LSN for this backup
FirstLSN: First LSN in this backup
LastLSN: Last LSN in this backup
CheckpointLSN: Checkpoint at backup time

Verify chain:
Full backup: DatabaseBackupLSN = 0 (or very low)
Differential: DatabaseBackupLSN = Full's CheckpointLSN
Log backups: FirstLSN <= Previous LastLSN (overlapping sequence)
*/
```

**Example Output Analysis:**
```
Full Backup (2 AM):
BackupType       FirstLSN          LastLSN           CheckpointLSN
1 (Full)         45000000000500    45000020000700    45000020000700

Differential (2 PM):
BackupType       FirstLSN          LastLSN           DatabaseBackupLSN
5 (Diff)         45000020000700    45012050000900    45000020000700  ✓ Matches Full

Log Backup (3 PM):
BackupType       FirstLSN          LastLSN
2 (Log)          45012050000900    45015070000300    ✓ Continuous

Tail-Log:
BackupType       FirstLSN          LastLSN
2 (Log)          45015070000300    45015090000800    ✓ Continuous
```

---

**Step 5: Restore Full Backup**
```sql
-- Restore full backup with NORECOVERY
RESTORE DATABASE ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Full_0200.bak'
WITH NORECOVERY,
     REPLACE,  -- Overwrite existing database
     STATS = 10,  -- Progress updates every 10%
     MOVE 'ProductionDB' TO 'E:\SQLData\ProductionDB.mdf',
     MOVE 'ProductionDB_log' TO 'F:\SQLLogs\ProductionDB_log.ldf'
GO

-- Expected output:
-- Processed 25000 pages for database 'ProductionDB', file 'ProductionDB' on file 1.
-- Processed 5 pages for database 'ProductionDB', file 'ProductionDB_log' on file 1.
-- RESTORE DATABASE successfully processed 25005 pages in 120 seconds (1.625 MB/sec).

-- Database is now in RESTORING state at 2:00 AM point in time
```

---

**Step 6: Restore Differential Backup**
```sql
-- Restore differential (brings us to 2 PM, skips all logs from 2 AM to 2 PM)
RESTORE DATABASE ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Diff_1400.bak'
WITH NORECOVERY,
     STATS = 10
GO

-- Processed 8000 pages (only changed pages since full backup)
-- Database now at 2:00 PM point in time
```

---

**Step 7: Restore Transaction Log Backups in Sequence**
```sql
-- Restore first log backup (2:15 PM)
RESTORE LOG ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Log_1415.trn'
WITH NORECOVERY, STATS = 10
GO

-- Restore second log backup (2:30 PM)
RESTORE LOG ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Log_1430.trn'
WITH NORECOVERY, STATS = 10
GO

-- Restore third log backup (2:45 PM)
RESTORE LOG ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Log_1445.trn'
WITH NORECOVERY, STATS = 10
GO

-- Restore fourth log backup (3:00 PM)
RESTORE LOG ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Log_1500.trn'
WITH NORECOVERY, STATS = 10
GO

-- Database now at 3:00 PM
```

---

**Step 8: Restore Tail-Log to Specific Point in Time**
```sql
-- Final restore: Tail-log backup with STOPAT clause
RESTORE LOG ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_TailLog_20260309_1515.trn'
WITH RECOVERY,  -- ← RECOVERY (not NORECOVERY) - this is the final restore
     STOPAT = '2026-03-09 15:14:00',  -- Stop at 3:14 PM (before crash)
     STATS = 10
GO

-- Critical messages:
-- Roll forward start: 45015070000300
-- Roll forward transactions: 234 transactions rolled forward
-- Roll forward stop: 45015088500600 (corresponds to 3:14 PM)
-- 15 uncommitted transactions rolled back
-- RESTORE LOG successfully processed X pages

-- Database is now ONLINE at exactly 3:14 PM
```

---

**Step 9: Verify Recovery**
```sql
-- Check database is online
SELECT name, state_desc, recovery_model_desc
FROM sys.databases
WHERE name = 'ProductionDB'
GO

-- Verify last transaction time
SELECT
    MAX(transaction_date) AS last_transaction
FROM ProductionDB.dbo.TransactionLog  -- Your transaction audit table
GO
-- Should show: 2026-03-09 15:14:00 or earlier

-- Check row counts in critical tables
SELECT COUNT(*) AS order_count FROM ProductionDB.dbo.Orders
SELECT COUNT(*) AS customer_count FROM ProductionDB.dbo.Customers
GO

-- Compare with known counts before crash
-- Verify expected data is present

-- Check for any corruption
DBCC CHECKDB('ProductionDB') WITH NO_INFOMSGS
GO
-- Should return: CHECKDB found 0 allocation errors and 0 consistency errors
```

---

**Step 10: Update Application Connection Strings**
```powershell
# Update application config files
# Redirect connections back to restored database

# Test application connectivity
Test-NetConnection -ComputerName SQLServer -Port 1433

# Verify application can query database
Invoke-Sqlcmd -ServerInstance SQLServer -Database ProductionDB -Query "SELECT @@VERSION"
```

---

**Step 11: Resume Operations & Monitor**
```sql
-- Re-create SQL Agent jobs if needed (after system DB restore)
EXEC msdb.dbo.sp_help_job

-- Verify backup schedule is active
SELECT
    j.name AS job_name,
    js.next_run_date,
    js.next_run_time
FROM msdb.dbo.sysjobs j
INNER JOIN msdb.dbo.sysjobschedules js ON j.job_id = js.job_id
WHERE j.name LIKE '%Backup%'

-- Immediately take new full backup
BACKUP DATABASE ProductionDB
TO DISK = 'C:\Backup\ProductionDB_Full_PostRecovery.bak'
WITH COMPRESSION, INIT, STATS = 10
GO

-- Resume transaction log backups (15-minute schedule)
```

---

**Troubleshooting Common Issues:**

**Issue 1: "The log in this backup set begins at LSN X, which is too recent to apply to the database"**
```sql
-- Problem: Trying to restore log backup that doesn't match LSN chain
-- Solution: Verify you restored the correct differential or previous log backup

-- Check current database LSN
RESTORE DATABASE ProductionDB
FROM DISK = 'NUL'
WITH FILE = 1, NORECOVERY  -- Get current restore position

-- Output shows: "Database was restored to LSN 45012050000900"
-- Next log backup must have FirstLSN <= 45012050000900
```

**Issue 2: "Cannot restore tail-log backup - SQL Server won't start"**
```powershell
# If server hardware failed completely:

# Option A: Attach log file to different SQL Server instance (same version)
# 1. Copy ProductionDB_log.ldf to working server
# 2. Create dummy database with same name/structure
# 3. Stop SQL Server
# 4. Replace log file with copied file
# 5. Start SQL Server in single-user mode
# 6. Backup tail-log

# Option B: Accept data loss from last log backup (3:00 PM)
# Restore up to last available log backup
# Lose 15 minutes of transactions (3:00 PM to 3:15 PM)
```

**Issue 3: "STOPAT time is before earliest transaction in log backup"**
```sql
-- Error: The point in time '2026-03-09 14:30:00' is too early
-- This occurs when STOPAT time is before the FirstLSN in log backup

-- Solution: Use previous log backup
RESTORE LOG ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Log_1415.trn'  -- Earlier backup
WITH NORECOVERY, STOPAT = '2026-03-09 14:30:00'
GO
```

---

**Best Practices Learned:**

1. **Always backup tail-log first** - This is the most critical step in disaster recovery
2. **Verify LSN chain** before starting restore to avoid wasting time
3. **Test STOPAT precision** - Use seconds-level precision: 'YYYY-MM-DD HH:MM:SS'
4. **Document restore steps** - Have runbook ready with exact file paths
5. **Practice recovery** - Monthly DR drills in test environment
6. **Monitor restore progress** - Use STATS = 10 to see progress on large restores
7. **Automate verification** - Script post-restore checks (row counts, CHECKDB)

---

### Q93: You need to restore a 5TB database but the PRIMARY filegroup is intact - only a secondary filegroup with historical data is corrupted. Explain piecemeal restore strategy to minimize downtime.

**Answer:**

**Scenario:**
- Database: WarehouseDB (5 TB)
- Primary filegroup (PRIMARY): 500 GB - **INTACT**
- Current data filegroup (FG_Current): 1.5 TB - **INTACT**
- Historical filegroup (FG_History): 3 TB - **CORRUPTED**
- Goal: Restore database quickly with critical data accessible

**Piecemeal Restore Concept:**
Restore and recover filegroups in stages, bringing critical filegroups online first while secondary filegroups remain offline and are restored later.

---

**Architecture Overview:**
```sql
-- Database filegroup structure
USE WarehouseDB
GO

-- Check filegroup configuration
SELECT
    fg.name AS filegroup_name,
    df.name AS file_logical_name,
    df.physical_name,
    df.size * 8 / 1024 AS size_mb,
    fg.is_read_only,
    df.state_desc
FROM sys.filegroups fg
INNER JOIN sys.database_files df ON fg.data_space_id = df.data_space_id
GO

/* Example output:
filegroup_name  file_logical_name     size_mb    is_read_only  state_desc
PRIMARY         WarehouseDB_Primary   500000     0             ONLINE
FG_Current      WarehouseDB_Current   1500000    0             ONLINE
FG_History      WarehouseDB_History   3000000    0             RECOVERY_PENDING  ← Problem!
*/
```

---

**Step-by-Step Piecemeal Restore:**

**Step 1: Verify Corruption Scope**
```sql
-- Check which filegroup is corrupted
SELECT
    f.name AS file_name,
    f.physical_name,
    f.state_desc,
    f.size * 8 / 1024 AS size_mb
FROM sys.master_files f
WHERE f.database_id = DB_ID('WarehouseDB')
  AND f.state_desc <> 'ONLINE'
GO

-- Run DBCC CHECKDB on specific filegroup
DBCC CHECKDB('WarehouseDB', NOINDEX) WITH PHYSICAL_ONLY, NO_INFOMSGS
GO

-- Or check specific filegroup
DBCC CHECKFILEGROUP('FG_History', NOINDEX) WITH PHYSICAL_ONLY
GO

/* Example error:
Msg 824, Level 24, State 2
SQL Server detected a logical consistency-based I/O error: incorrect checksum
(expected: 0x12345678; actual: 0xabcdefab).
It occurred during a read of page (1:156234) in database ID 7, file 'WarehouseDB_History'
*/
```

**Step 2: Take Tail-Log Backup**
```sql
-- Critical: Backup tail-log before any restore
BACKUP LOG WarehouseDB
TO DISK = 'C:\Backup\WarehouseDB_TailLog.trn'
WITH NORECOVERY, NO_TRUNCATE, COMPRESSION, INIT
GO

-- Database is now in RESTORING state
```

---

**Step 3: Partial Restore (PRIMARY + Critical Filegroups)**

**Phase 1: Restore PRIMARY Filegroup**
```sql
-- Restore only PRIMARY filegroup (required - contains system tables)
RESTORE DATABASE WarehouseDB FILEGROUP = 'PRIMARY'
FROM DISK = 'C:\Backup\WarehouseDB_Full.bak'
WITH PARTIAL,  -- ← PARTIAL keyword enables piecemeal restore
     NORECOVERY,
     REPLACE,
     STATS = 10
GO

-- PARTIAL keyword tells SQL Server:
-- "I'm only restoring some filegroups now, others later"
```

**Phase 2: Restore FG_Current (Critical Business Data)**
```sql
-- Restore current data filegroup
RESTORE DATABASE WarehouseDB FILEGROUP = 'FG_Current'
FROM DISK = 'C:\Backup\WarehouseDB_Full.bak'
WITH NORECOVERY,
     STATS = 10
GO

-- Note: No PARTIAL keyword here (only on first restore)
```

**Phase 3: Apply Differential Backup (if available)**
```sql
-- Restore differential for PRIMARY and FG_Current
RESTORE DATABASE WarehouseDB FILEGROUP = 'PRIMARY'
FROM DISK = 'C:\Backup\WarehouseDB_Diff.bak'
WITH NORECOVERY, STATS = 10
GO

RESTORE DATABASE WarehouseDB FILEGROUP = 'FG_Current'
FROM DISK = 'C:\Backup\WarehouseDB_Diff.bak'
WITH NORECOVERY, STATS = 10
GO
```

**Phase 4: Apply Transaction Log Backups**
```sql
-- Apply all log backups since differential
RESTORE LOG WarehouseDB
FROM DISK = 'C:\Backup\WarehouseDB_Log1.trn'
WITH NORECOVERY, STATS = 10
GO

RESTORE LOG WarehouseDB
FROM DISK = 'C:\Backup\WarehouseDB_Log2.trn'
WITH NORECOVERY, STATS = 10
GO

-- Apply tail-log backup
RESTORE LOG WarehouseDB
FROM DISK = 'C:\Backup\WarehouseDB_TailLog.trn'
WITH RECOVERY  -- ← RECOVERY brings database online
GO
```

**Database is Now ONLINE!**
```
Messages:
RESTORE LOG successfully processed X pages in X seconds.
Database WarehouseDB is now online with filegroups [PRIMARY] and [FG_Current].
Filegroup [FG_History] remains offline.

Total restore time: ~2 hours (instead of 8+ hours for full 5TB restore)
```

---

**Step 4: Verify Partial Database Accessibility**
```sql
-- Check database status
SELECT
    name,
    state_desc,
    user_access_desc
FROM sys.databases
WHERE name = 'WarehouseDB'
GO
-- Output: state_desc = ONLINE

-- Check filegroup status
SELECT
    name AS filegroup_name,
    state_desc
FROM sys.filegroups
WHERE data_space_id IN (SELECT data_space_id FROM sys.database_files)
GO

/* Output:
filegroup_name  state_desc
PRIMARY         ONLINE        ✓ Accessible
FG_Current      ONLINE        ✓ Accessible
FG_History      OFFLINE       ✗ Not accessible yet
*/

-- Test queries against online filegroups
SELECT COUNT(*) FROM WarehouseDB.dbo.CurrentOrders  -- Works! (on FG_Current)
SELECT COUNT(*) FROM WarehouseDB.dbo.Customers      -- Works! (on PRIMARY)
SELECT COUNT(*) FROM WarehouseDB.dbo.HistoricalOrders  -- FAILS (on FG_History - offline)
GO

-- Error accessing offline filegroup:
-- Msg 8653, Level 16, State 1
-- The query processor is unable to produce a plan for the table 'HistoricalOrders'
-- because the filegroup 'FG_History' is offline.
```

**Application Can Now Resume Operations!**
- 80% of database (current data) is accessible
- Downtime reduced from 8 hours to 2 hours
- Historical queries fail gracefully (can handle in app)

---

**Step 5: Restore Offline Filegroup (Background Operation)**

This can be done while application is running:

```sql
-- Verify database is online before filegroup restore
SELECT state_desc FROM sys.databases WHERE name = 'WarehouseDB'
-- Must be ONLINE for online filegroup restore

-- Restore offline filegroup (FG_History)
RESTORE DATABASE WarehouseDB FILEGROUP = 'FG_History'
FROM DISK = 'C:\Backup\WarehouseDB_Full.bak'
WITH NORECOVERY,
     STATS = 5  -- More frequent updates for large filegroup
GO

-- This takes several hours (3 TB) but database remains ONLINE
```

**Apply Differential (if available)**
```sql
RESTORE DATABASE WarehouseDB FILEGROUP = 'FG_History'
FROM DISK = 'C:\Backup\WarehouseDB_Diff.bak'
WITH NORECOVERY, STATS = 5
GO
```

**Apply Transaction Logs**
```sql
-- Apply same log sequence that was applied to PRIMARY/FG_Current
RESTORE LOG WarehouseDB
FROM DISK = 'C:\Backup\WarehouseDB_Log1.trn'
WITH NORECOVERY
GO

RESTORE LOG WarehouseDB
FROM DISK = 'C:\Backup\WarehouseDB_Log2.trn'
WITH NORECOVERY
GO

-- Apply tail-log
RESTORE LOG WarehouseDB
FROM DISK = 'C:\Backup\WarehouseDB_TailLog.trn'
WITH RECOVERY  -- Bring filegroup online
GO

-- Messages:
-- Filegroup [FG_History] is now online.
-- All filegroups in database WarehouseDB are now online.
```

---

**Step 6: Verify Complete Restore**
```sql
-- Verify all filegroups online
SELECT
    fg.name AS filegroup_name,
    fg.state_desc,
    COUNT(df.file_id) AS file_count,
    SUM(df.size) * 8 / 1024 AS total_size_mb
FROM sys.filegroups fg
INNER JOIN sys.database_files df ON fg.data_space_id = df.data_space_id
GROUP BY fg.name, fg.state_desc
GO

/* Expected output:
filegroup_name  state_desc  file_count  total_size_mb
PRIMARY         ONLINE      1           500000
FG_Current      ONLINE      4           1500000
FG_History      ONLINE      8           3000000
*/

-- Test historical queries now work
SELECT COUNT(*) FROM WarehouseDB.dbo.HistoricalOrders
GO
-- Success!

-- Run full CHECKDB to verify integrity
DBCC CHECKDB('WarehouseDB') WITH NO_INFOMSGS
GO
-- CHECKDB found 0 allocation errors and 0 consistency errors
```

---

**Backup Strategy After Piecemeal Restore:**

```sql
-- Immediately take new full backup
BACKUP DATABASE WarehouseDB
TO DISK = 'C:\Backup\WarehouseDB_Full_PostRestore.bak'
WITH COMPRESSION, INIT, STATS = 10
GO

-- Resume regular backup schedule
-- Full: Weekly
-- Differential: Daily
-- Transaction log: Every 15 minutes
```

---

**Advanced Scenarios:**

**Scenario 1: Read-Only Filegroups**
```sql
-- If historical filegroup is read-only (best practice for old data)
ALTER DATABASE WarehouseDB
MODIFY FILEGROUP FG_History READ_ONLY
GO

-- Benefit: Read-only filegroups don't need log restores
-- Can restore read-only filegroup at any time without log chain

-- Restore read-only filegroup independently
RESTORE DATABASE WarehouseDB FILEGROUP = 'FG_History'
FROM DISK = 'C:\Backup\WarehouseDB_Full.bak'
WITH RECOVERY  -- ← Direct to RECOVERY (no log backups needed)
GO
```

**Scenario 2: Multiple Secondary Filegroups**
```sql
-- Restore filegroups in priority order:
-- Priority 1: PRIMARY (always required)
-- Priority 2: FG_Current (active data)
-- Priority 3: FG_RecentHistory (6 months)
-- Priority 4: FG_Archive (older data)

-- Restore plan:
-- Hour 0-2: PRIMARY + FG_Current → Database ONLINE (90% of queries work)
-- Hour 2-6: FG_RecentHistory → 98% of queries work
-- Hour 6-12: FG_Archive → 100% functionality restored
```

**Scenario 3: Filegroup Corruption During Operation**
```sql
-- If filegroup corruption occurs on live database:

-- 1. Take filegroup offline (database stays online)
ALTER DATABASE WarehouseDB
MODIFY FILE (NAME = 'WarehouseDB_History_01', OFFLINE)
GO

-- 2. Queries against FG_History fail, but PRIMARY/FG_Current work
-- 3. Restore corrupt filegroup online (piecemeal online restore)
-- 4. Database continues serving requests during restore
```

---

**Monitoring Piecemeal Restore Progress:**

```sql
-- Monitor restore progress
SELECT
    r.session_id,
    r.command,
    r.percent_complete,
    r.total_elapsed_time / 1000 / 60 AS elapsed_minutes,
    r.estimated_completion_time / 1000 / 60 AS remaining_minutes,
    DB_NAME(r.database_id) AS database_name
FROM sys.dm_exec_requests r
WHERE r.command LIKE 'RESTORE%'
GO

-- Check restore history
SELECT TOP 10
    restore_date,
    destination_database_name,
    restore_type,
    backup_set_id,
    (DATEDIFF(SECOND, restore_date, GETDATE()) / 60) AS minutes_ago
FROM msdb.dbo.restorehistory
WHERE destination_database_name = 'WarehouseDB'
ORDER BY restore_date DESC
GO
```

---

**Benefits of Piecemeal Restore:**

| Aspect | Full Restore | Piecemeal Restore |
|--------|--------------|-------------------|
| **Total restore time** | 8+ hours | 2 hours (critical data) |
| **Database availability** | After 8 hours | After 2 hours |
| **Application downtime** | 8+ hours | 2 hours |
| **Business impact** | High | Low |
| **Query functionality** | 0% until complete | 80% immediately, 100% after 8 hours |

---

**Best Practices:**

1. **Filegroup design** - Separate current and historical data into different filegroups
2. **Mark old data read-only** - Read-only filegroups don't need log restore
3. **Test piecemeal restore** - Practice in non-production environment
4. **Document filegroup priority** - Which filegroups are mission-critical?
5. **Monitor filegroup health** - Regular CHECKDB with PHYSICAL_ONLY
6. **Size filegroups appropriately** - Balance between granularity and complexity

---

### Q94: During a restore operation, you encounter error 3013: "RESTORE DATABASE is terminating abnormally" with underlying error 824 (I/O error). The backup file has CHECKSUM. How do you recover data?

**Answer:**

**Error Messages:**
```
Msg 824, Level 24, State 2, Line 1
SQL Server detected a logical consistency-based I/O error: incorrect checksum
(expected: 0xa4b6c3d2; actual: 0x00000000).
It occurred during a read of page (1:156234) in database ID 0, file 'C:\Backup\ProductionDB.bak'
at offset 0x000004e12f000 in file 'C:\Backup\ProductionDB.bak'.

Msg 3013, Level 16, State 1, Line 1
RESTORE DATABASE is terminating abnormally.
```

**Root Causes:**
- Backup file corruption on disk
- Network corruption during backup file copy
- Storage media failure
- Incomplete backup file write
- Antivirus interference during backup

---

**Recovery Strategy Decision Tree:**

```
Can restore from different backup?
├─ YES → Use alternate backup (best option)
└─ NO → How critical is the data?
    ├─ CRITICAL → Attempt advanced recovery
    └─ NON-CRITICAL → Restore older backup, accept data loss
```

---

**Option 1: Use CONTINUE_AFTER_ERROR (Last Resort)**

```sql
-- WARNING: This will skip corrupt pages and mark them as suspect
-- Database will be online but with data loss on corrupt pages

-- Attempt restore with CONTINUE_AFTER_ERROR
RESTORE DATABASE ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Corrupt.bak'
WITH CONTINUE_AFTER_ERROR,
     REPLACE,
     STATS = 10
GO

-- Messages you'll see:
/*
Warning: Page (1:156234) in database ID 5 is unreadable. Skipped.
Warning: Page (1:156235) in database ID 5 is unreadable. Skipped.
...
Processed 25000 pages for database 'ProductionDB', file 'ProductionDB'.
22 pages were skipped due to I/O errors.
RESTORE DATABASE successfully completed, but with errors.
The database has been marked SUSPECT on some pages.
*/

-- Database is now ONLINE but damaged
SELECT state_desc FROM sys.databases WHERE name = 'ProductionDB'
-- state_desc = ONLINE (but contains corrupt pages)
```

**Check Suspect Pages:**
```sql
-- View which pages were skipped/corrupted
SELECT
    database_id,
    DB_NAME(database_id) AS database_name,
    file_id,
    page_id,
    event_type,
    error_count,
    last_update_date
FROM msdb.dbo.suspect_pages
WHERE database_id = DB_ID('ProductionDB')
ORDER BY last_update_date DESC
GO

/* Example output:
database_name  file_id  page_id  event_type  error_count  last_update_date
ProductionDB   1        156234   1           1            2026-03-09 15:30:45
ProductionDB   1        156235   1           1            2026-03-09 15:30:45

event_type values:
1 = 823 or 824 error (checksum/torn page)
2 = Bad checksum
3 = Torn page
4 = Restored (page repaired)
5 = Repaired (DBCC fixed)
7 = Deallocated by DBCC
*/
```

**Identify Affected Objects:**
```sql
-- Find which tables/indexes are affected by corrupt pages
DBCC PAGE('ProductionDB', 1, 156234, 3) WITH TABLERESULTS
GO

-- Or use DBCC CHECKDB to identify affected objects
DBCC CHECKDB('ProductionDB', NOINDEX) WITH TABLERESULTS, NO_INFOMSGS
GO

/* Output will show:
Object ID: 245575913
Index ID: 1
Partition ID: 72057594038976512
Allocation Unit ID: 72057594043170816
Object name: dbo.Orders

Error: Page (1:156234) could not be processed.
Repair: Page deallocated (data loss).
*/

-- Query affected table to see data loss
SELECT * FROM ProductionDB.dbo.Orders
GO
-- Some rows will be missing (those on corrupt pages)
```

---

**Option 2: Page Restore (If You Have Recent Log Backups)**

If you have:
- A good full/differential backup
- Transaction log backups after the corruption

You can restore just the corrupt pages:

**Step 1: Identify Corrupt Pages**
```sql
-- List suspect pages from failed restore
SELECT
    file_id,
    page_id
FROM msdb.dbo.suspect_pages
WHERE database_id = DB_ID('ProductionDB')
  AND event_type IN (1, 2, 3)  -- Corruption errors
GO
```

**Step 2: Take Tail-Log Backup**
```sql
-- Backup current transaction log
BACKUP LOG ProductionDB
TO DISK = 'C:\Backup\ProductionDB_TailLog.trn'
WITH NORECOVERY, COMPRESSION
GO
```

**Step 3: Restore Corrupt Pages**
```sql
-- Restore specific pages from good backup
RESTORE DATABASE ProductionDB
PAGE = '1:156234, 1:156235'  -- Comma-separated list of pages
FROM DISK = 'C:\Backup\ProductionDB_Good.bak'
WITH NORECOVERY
GO

-- Restore differential if available
RESTORE DATABASE ProductionDB
PAGE = '1:156234, 1:156235'
FROM DISK = 'C:\Backup\ProductionDB_Diff.bak'
WITH NORECOVERY
GO

-- Apply transaction logs to bring pages up to date
RESTORE LOG ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Log1.trn'
WITH NORECOVERY
GO

RESTORE LOG ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Log2.trn'
WITH NORECOVERY
GO

-- Apply tail-log and recover
RESTORE LOG ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_TailLog.trn'
WITH RECOVERY
GO

-- Pages are now repaired!
-- Database is ONLINE with all data intact
```

**Verify Page Repair:**
```sql
-- Check suspect_pages table
SELECT * FROM msdb.dbo.suspect_pages
WHERE database_id = DB_ID('ProductionDB')
  AND page_id IN (156234, 156235)
GO

-- event_type should now be 4 (Restored) or 5 (Repaired)

-- Verify data integrity
DBCC CHECKDB('ProductionDB') WITH NO_INFOMSGS
GO
-- Should report: CHECKDB found 0 allocation errors and 0 consistency errors

-- Query affected table
SELECT COUNT(*) FROM ProductionDB.dbo.Orders
GO
-- All rows should be present
```

---

**Option 3: Verify and Repair Backup File**

**Verify Backup Integrity:**
```sql
-- Check if backup file is valid
RESTORE VERIFYONLY
FROM DISK = 'C:\Backup\ProductionDB.bak'
WITH CHECKSUM
GO

-- If successful: Backup file structure is valid
-- If error 824: Backup file has physical corruption
```

**Attempt to Extract Good Pages:**
```powershell
# Use third-party tools to extract readable data from corrupt backup
# Examples:
# - ApexSQL Recover
# - Stellar Repair for SQL Server
# - Redgate SQL Backup Pro (if encrypted backup)

# These tools can sometimes skip corrupt sectors and extract partial data
```

---

**Option 4: Restore Older Backup + Forward Log Backups**

If primary backup is corrupt but you have older backup:

```sql
-- Use older full backup (e.g., from yesterday)
RESTORE DATABASE ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Full_Yesterday.bak'
WITH NORECOVERY, REPLACE
GO

-- Roll forward with today's differential (if available and not corrupt)
RESTORE DATABASE ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Diff_Today.bak'
WITH NORECOVERY
GO

-- Roll forward with all transaction logs
RESTORE LOG ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_Log_*.trn'
WITH NORECOVERY
GO

-- Recover database
RESTORE LOG ProductionDB
FROM DISK = 'C:\Backup\ProductionDB_TailLog.trn'
WITH RECOVERY
GO

-- Result: Database recovered with minimal data loss (since yesterday's backup)
```

---

**Option 5: Investigate Backup File Corruption**

**Check File System:**
```cmd
REM Verify backup file integrity at OS level
chkdsk D: /F /R

REM Check file attributes
attrib "C:\Backup\ProductionDB.bak"

REM Verify file size matches expected
dir "C:\Backup\ProductionDB.bak"
```

**Check Backup History:**
```sql
-- Verify backup completed successfully
SELECT
    database_name,
    backup_start_date,
    backup_finish_date,
    DATEDIFF(MINUTE, backup_start_date, backup_finish_date) AS duration_minutes,
    backup_size / 1024 / 1024 AS backup_size_mb,
    compressed_backup_size / 1024 / 1024 AS compressed_size_mb,
    type,
    is_damaged,  -- ← Check this!
    has_backup_checksums
FROM msdb.dbo.backupset
WHERE database_name = 'ProductionDB'
  AND backup_start_date >= DATEADD(DAY, -7, GETDATE())
ORDER BY backup_start_date DESC
GO

-- If is_damaged = 1, backup was created with errors
-- If has_backup_checksums = 0, backup wasn't protected with CHECKSUM
```

**Test Backup on Another Server:**
```sql
-- Try restoring to test server to isolate issue
-- If restore works on test server:
--   → Corruption occurred during file copy/network transfer
-- If restore fails on test server too:
--   → Backup file itself is corrupt
```

---

**Prevention Strategies:**

**1. Enable Backup CHECKSUM**
```sql
-- Always use CHECKSUM for backup integrity
BACKUP DATABASE ProductionDB
TO DISK = 'C:\Backup\ProductionDB.bak'
WITH COMPRESSION, CHECKSUM, INIT
GO

-- Verify backup after creation
RESTORE VERIFYONLY
FROM DISK = 'C:\Backup\ProductionDB.bak'
WITH CHECKSUM
GO
```

**2. Enable Page CHECKSUM on Database**
```sql
-- Set page verification to CHECKSUM (detect corruption on read)
ALTER DATABASE ProductionDB
SET PAGE_VERIFY CHECKSUM
GO

-- Verify setting
SELECT name, page_verify_option_desc
FROM sys.databases
WHERE name = 'ProductionDB'
GO
-- Should show: CHECKSUM
```

**3. Automated Backup Verification**
```sql
-- Create job to verify backups nightly
CREATE PROCEDURE dbo.VerifyRecentBackups
AS
BEGIN
    DECLARE @BackupFile VARCHAR(500)
    DECLARE @SQL VARCHAR(MAX)

    DECLARE backup_cursor CURSOR FOR
    SELECT physical_device_name
    FROM msdb.dbo.backupmediafamily bmf
    INNER JOIN msdb.dbo.backupset bs ON bmf.media_set_id = bs.media_set_id
    WHERE bs.backup_finish_date >= DATEADD(DAY, -1, GETDATE())
      AND bs.type = 'D'  -- Full backups only

    OPEN backup_cursor
    FETCH NEXT FROM backup_cursor INTO @BackupFile

    WHILE @@FETCH_STATUS = 0
    BEGIN
        BEGIN TRY
            SET @SQL = 'RESTORE VERIFYONLY FROM DISK = ''' + @BackupFile + ''' WITH CHECKSUM'
            EXEC(@SQL)
            PRINT 'Verified: ' + @BackupFile
        END TRY
        BEGIN CATCH
            PRINT 'FAILED: ' + @BackupFile + ' - ' + ERROR_MESSAGE()
            -- Send alert email
            EXEC msdb.dbo.sp_send_dbmail
                @recipients = 'dba@example.invalid',
                @subject = 'Backup Verification Failed',
                @body = @BackupFile
        END CATCH

        FETCH NEXT FROM backup_cursor INTO @BackupFile
    END

    CLOSE backup_cursor
    DEALLOCATE backup_cursor
END
GO
```

**4. Multiple Backup Copies**
```sql
-- Create backup to multiple locations simultaneously
BACKUP DATABASE ProductionDB
TO DISK = 'C:\Backup\Local\ProductionDB.bak',
   DISK = '\\BackupServer\Backups\ProductionDB.bak'
WITH COMPRESSION, CHECKSUM, INIT, FORMAT, MEDIANAME = 'ProductionBackup'
GO

-- Benefit: If one copy is corrupt, you have another
```

**5. Test Restores Regularly**
```powershell
# Weekly automated restore test to isolated server
# PowerShell script:

$ErrorActionPreference = "Stop"
$backupFile = "\\BackupServer\Backups\ProductionDB.bak"
$testServer = "SQLTest01"
$testDB = "ProductionDB_RestoreTest"

try {
    # Restore to an isolated test server.
    Invoke-Sqlcmd -ServerInstance $testServer -ErrorAction Stop -Query @"
RESTORE DATABASE [$testDB]
FROM DISK = '$backupFile'
WITH REPLACE, RECOVERY,
     MOVE 'ProductionDB' TO 'D:\SQLData\$testDB.mdf',
     MOVE 'ProductionDB_log' TO 'E:\SQLLogs\$testDB_log.ldf'
"@

    # A CHECKDB error stops the script and preserves the restored database
    # for investigation instead of reporting a false success.
    Invoke-Sqlcmd -ServerInstance $testServer -ErrorAction Stop `
        -Query "DBCC CHECKDB('$testDB') WITH NO_INFOMSGS"

    # Clean up only after restore and integrity validation both succeed.
    Invoke-Sqlcmd -ServerInstance $testServer -ErrorAction Stop `
        -Query "ALTER DATABASE [$testDB] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [$testDB]"
}
catch {
    Write-Error "Restore validation failed; [$testDB] was preserved for investigation. $($_.Exception.Message)"
    throw
}
```

---

**Summary Decision Matrix:**

| Situation | Best Option | Data Loss | Complexity |
|-----------|-------------|-----------|------------|
| Have good older backup + logs | Option 4 | Minimal | Low |
| Have recent good backup | Page Restore (Option 2) | None | Medium |
| No other backups available | CONTINUE_AFTER_ERROR (Option 1) | High | High |
| Backup file partially readable | Extract good pages (Option 3) | Variable | Very High |

---

---

### Q95: You need to migrate a 2TB TDE-encrypted database to a new server. Walk through the complete process including certificate migration and validation.

**Answer:**

**Scenario:**
- Source Server: SQL-PROD01 (SQL Server 2019)
- Target Server: SQL-PROD02 (SQL Server 2019)
- Database: FinanceDB (2 TB, TDE-encrypted)
- Goal: Migrate with zero data loss

**Background:** TDE (Transparent Data Encryption) encrypts data at rest using a Database Encryption Key (DEK), which is encrypted by a certificate stored in the master database. Without the certificate, encrypted backup cannot be restored.

---

**Step-by-Step Migration Process:**

**Phase 1: Verify TDE Configuration on Source**

```sql
-- Connect to SOURCE server: SQL-PROD01
USE master
GO

-- Verify database is encrypted
SELECT
    db.name AS database_name,
    db.is_encrypted,
    dm.encryption_state,
    CASE dm.encryption_state
        WHEN 0 THEN 'No encryption'
        WHEN 1 THEN 'Unencrypted'
        WHEN 2 THEN 'Encryption in progress'
        WHEN 3 THEN 'Encrypted'
        WHEN 4 THEN 'Key change in progress'
        WHEN 5 THEN 'Decryption in progress'
        WHEN 6 THEN 'Protection change in progress'
    END AS encryption_state_desc,
    dm.encryptor_type,
    c.name AS certificate_name,
    c.thumbprint,
    c.subject
FROM sys.databases db
LEFT JOIN sys.dm_database_encryption_keys dm ON db.database_id = dm.database_id
LEFT JOIN sys.certificates c ON dm.encryptor_thumbprint = c.thumbprint
WHERE db.name = 'FinanceDB'
GO

/* Example output:
database_name  is_encrypted  encryption_state  encryption_state_desc  certificate_name         thumbprint
FinanceDB      1             3                 Encrypted              TDE_Cert_FinanceDB      0x6A7F8E9D2B...
*/

-- Verify certificate details
SELECT
    name AS certificate_name,
    certificate_id,
    pvt_key_encryption_type_desc,
    subject,
    start_date,
    expiry_date,
    thumbprint,
    pvt_key_last_backup_date
FROM sys.certificates
WHERE name = 'TDE_Cert_FinanceDB'
GO

/* Critical: Check pvt_key_last_backup_date
If NULL, certificate private key has NEVER been backed up!
Must backup before migration.
*/
```

---

**Phase 2: Backup Certificate and Private Key (SOURCE)**

```sql
-- SOURCE server: SQL-PROD01
USE master
GO

-- Verify master key exists (required for certificate backup)
SELECT * FROM sys.symmetric_keys WHERE name = '##MS_DatabaseMasterKey##'
GO

-- If no master key exists, create one:
CREATE MASTER KEY ENCRYPTION BY PASSWORD = '$(DatabaseMasterKeyPassword)'
GO

-- Backup the certificate WITH PRIVATE KEY
BACKUP CERTIFICATE TDE_Cert_FinanceDB
TO FILE = 'C:\Backup\TDE_Cert_FinanceDB.cer'  -- Public key
WITH PRIVATE KEY (
    FILE = 'C:\Backup\TDE_Cert_FinanceDB.pvk',  -- Private key
    ENCRYPTION BY PASSWORD = '$(CertificateBackupPassword)'  -- Protect private key
)
GO

-- Success message:
-- Certificate 'TDE_Cert_FinanceDB' and its private key were backed up successfully.
```

**Verify Certificate Backup Files:**
```powershell
# Verify files were created
Get-ChildItem C:\Backup\TDE_Cert_*

<# Expected output:
Mode          LastWriteTime    Length Name
----          -------------    ------ ----
-a----  3/9/2026  3:45 PM      1234   TDE_Cert_FinanceDB.cer
-a----  3/9/2026  3:45 PM      3456   TDE_Cert_FinanceDB.pvk
#>
```

---

**Phase 3: Backup Encrypted Database (SOURCE)**

```sql
-- SOURCE server: SQL-PROD01
-- Take full backup of encrypted database
BACKUP DATABASE FinanceDB
TO DISK = 'C:\Backup\FinanceDB_Full_Encrypted.bak'
WITH COMPRESSION, CHECKSUM, INIT, STATS = 10
GO

-- Backup size will be larger than unencrypted due to TDE overhead
-- Backup will complete successfully (TDE transparent to backup process)

-- Take transaction log backup (for point-in-time recovery)
BACKUP LOG FinanceDB
TO DISK = 'C:\Backup\FinanceDB_Log.trn'
WITH COMPRESSION, CHECKSUM, INIT
GO
```

**Verify Backup Header:**
```sql
-- Check backup contains TDE information
RESTORE HEADERONLY
FROM DISK = 'C:\Backup\FinanceDB_Full_Encrypted.bak'
GO

/* Check these columns:
Encryptor       Encryptor Type
Thumbprint
0x6A7F8E9D2B..  CERTIFICATE  ← Shows backup is encrypted!
*/
```

---

**Phase 4: Copy Files to Target Server**

```powershell
# Copy certificate files and backup to TARGET server
$source = "\\SQL-PROD01\C$\Backup"
$destination = "\\SQL-PROD02\C$\Backup"

Copy-Item "$source\TDE_Cert_FinanceDB.cer" $destination
Copy-Item "$source\TDE_Cert_FinanceDB.pvk" $destination
Copy-Item "$source\FinanceDB_Full_Encrypted.bak" $destination
Copy-Item "$source\FinanceDB_Log.trn" $destination

# Verify copy completed
Get-ChildItem $destination
```

---

**Phase 5: Restore Certificate on Target Server**

```sql
-- Connect to TARGET server: SQL-PROD02
USE master
GO

-- Step 1: Create/verify master key exists
SELECT * FROM sys.symmetric_keys WHERE name = '##MS_DatabaseMasterKey##'
GO

-- If no master key, create one:
CREATE MASTER KEY ENCRYPTION BY PASSWORD = '$(TargetMasterKeyPassword)'
GO

-- Step 2: Restore the certificate from backup
CREATE CERTIFICATE TDE_Cert_FinanceDB
FROM FILE = 'C:\Backup\TDE_Cert_FinanceDB.cer'  -- Public key
WITH PRIVATE KEY (
    FILE = 'C:\Backup\TDE_Cert_FinanceDB.pvk',  -- Private key
    DECRYPTION BY PASSWORD = '$(CertificateBackupPassword)'  -- Password used during backup
)
GO

-- Success message:
-- Certificate 'TDE_Cert_FinanceDB' successfully created.
```

**Verify Certificate on Target:**
```sql
-- Verify certificate was restored correctly
SELECT
    name,
    certificate_id,
    subject,
    thumbprint,
    pvt_key_encryption_type_desc
FROM sys.certificates
WHERE name = 'TDE_Cert_FinanceDB'
GO

/* Output should match SOURCE:
name                    thumbprint
TDE_Cert_FinanceDB     0x6A7F8E9D2B...  ← Must match source!
*/
```

---

**Phase 6: Restore Encrypted Database on Target**

```sql
-- TARGET server: SQL-PROD02
-- Now restore the encrypted database
RESTORE DATABASE FinanceDB
FROM DISK = 'C:\Backup\FinanceDB_Full_Encrypted.bak'
WITH NORECOVERY,
     MOVE 'FinanceDB' TO 'E:\SQLData\FinanceDB.mdf',
     MOVE 'FinanceDB_log' TO 'F:\SQLLogs\FinanceDB_log.ldf',
     STATS = 10
GO

-- Apply transaction log backup
RESTORE LOG FinanceDB
FROM DISK = 'C:\Backup\FinanceDB_Log.trn'
WITH RECOVERY
GO

-- Database is now ONLINE and accessible!
SELECT state_desc FROM sys.databases WHERE name = 'FinanceDB'
-- state_desc = ONLINE
```

---

**Phase 7: Verify TDE on Target Server**

```sql
-- TARGET server: SQL-PROD02
-- Verify encryption state
SELECT
    db.name,
    db.is_encrypted,
    dm.encryption_state,
    dm.encryption_state_desc,
    c.name AS certificate_name,
    c.thumbprint
FROM sys.databases db
INNER JOIN sys.dm_database_encryption_keys dm ON db.database_id = dm.database_id
INNER JOIN sys.certificates c ON dm.encryptor_thumbprint = c.thumbprint
WHERE db.name = 'FinanceDB'
GO

/* Expected output:
database_name  is_encrypted  encryption_state  certificate_name        thumbprint
FinanceDB      1             3 (Encrypted)     TDE_Cert_FinanceDB     0x6A7F8E9D2B...
*/

-- Test data access
USE FinanceDB
GO
SELECT TOP 10 * FROM Transactions
GO
-- Data accessible and automatically decrypted!

-- Verify database size
EXEC sp_spaceused
GO
```

---

**Phase 8: Verify Data Integrity**

```sql
-- Run CHECKDB to verify no corruption during migration
DBCC CHECKDB('FinanceDB') WITH NO_INFOMSGS
GO
-- Result: CHECKDB found 0 allocation errors and 0 consistency errors

-- Compare row counts (if you have them from source)
SELECT
    OBJECT_NAME(object_id) AS table_name,
    SUM(row_count) AS row_count
FROM sys.dm_db_partition_stats
WHERE object_id > 100  -- User tables only
  AND index_id IN (0, 1)  -- Heap or clustered index
GROUP BY object_id
ORDER BY table_name
GO

-- Verify critical business data
SELECT COUNT(*) AS transaction_count FROM Transactions
SELECT COUNT(*) AS account_count FROM Accounts
GO
```

---

**Common Errors and Solutions:**

**Error 1: "Cannot find server certificate with thumbprint"**
```
Msg 33111, Level 16, State 3
Cannot find server certificate with thumbprint '0x6A7F8E9D2B4C5A7F8E9D'.

Msg 3013, Level 16, State 1
RESTORE DATABASE is terminating abnormally.
```

**Cause:** Certificate not installed on target server or thumbprint mismatch

**Solution:**
```sql
-- Verify certificate thumbprint matches
-- On SOURCE:
SELECT thumbprint FROM sys.certificates WHERE name = 'TDE_Cert_FinanceDB'

-- On TARGET:
SELECT thumbprint FROM sys.certificates WHERE name = 'TDE_Cert_FinanceDB'

-- If missing, restore certificate again (Phase 5)
```

---

**Error 2: "CREATE CERTIFICATE failed because of invalid arguments"**
```
Msg 15240, Level 16, State 1
Cannot write into file 'C:\Backup\TDE_Cert_FinanceDB.pvk'.
Verify that you have write permissions and the file path is valid.
```

**Cause:** SQL Server service account lacks permissions or file already exists

**Solution:**
```powershell
# Grant permissions to SQL Server service account
$acl = Get-Acl "C:\Backup"
$permission = "NT SERVICE\MSSQLSERVER","FullControl","Allow"
$accessRule = New-Object System.Security.AccessControl.FileSystemAccessRule $permission
$acl.AddAccessRule($accessRule)
Set-Acl "C:\Backup" $acl

# Or delete existing file
Remove-Item "C:\Backup\TDE_Cert_FinanceDB.pvk" -Force
```

---

**Error 3: "The private key is already present in the key container"**
```
Msg 15531, Level 16, State 1
The certificate 'TDE_Cert_FinanceDB' private key is already present in the key container.
```

**Cause:** Certificate already exists on target server

**Solution:**
```sql
-- Drop existing certificate (if safe to do so)
DROP CERTIFICATE TDE_Cert_FinanceDB
GO

-- Then recreate from backup files
```

---

**Security Best Practices:**

**1. Secure Certificate Files**
```powershell
# Encrypt certificate files during transfer
# Use secure copy methods (not plain file shares)

# Example: Use encrypted USB drive or secure FTP
$securePassword = Read-Host "Enter certificate password" -AsSecureString

# Delete certificate files after successful migration
Remove-Item "C:\Backup\TDE_Cert_FinanceDB.cer" -Force
Remove-Item "C:\Backup\TDE_Cert_FinanceDB.pvk" -Force
```

**2. Backup Certificates Regularly**
```sql
-- Schedule monthly certificate backups
CREATE PROCEDURE dbo.BackupTDECertificates
AS
BEGIN
    DECLARE @Date VARCHAR(8) = CONVERT(VARCHAR(8), GETDATE(), 112)  -- YYYYMMDD
    DECLARE @CertName VARCHAR(100)
    DECLARE @SQL NVARCHAR(MAX)

    DECLARE cert_cursor CURSOR FOR
    SELECT name FROM sys.certificates WHERE pvt_key_encryption_type_desc <> 'NO_PRIVATE_KEY'

    OPEN cert_cursor
    FETCH NEXT FROM cert_cursor INTO @CertName

    WHILE @@FETCH_STATUS = 0
    BEGIN
        SET @SQL = N'
        BACKUP CERTIFICATE [' + @CertName + ']
        TO FILE = ''C:\Backup\Certificates\' + @CertName + '_' + @Date + '.cer''
        WITH PRIVATE KEY (
            FILE = ''C:\Backup\Certificates\' + @CertName + '_' + @Date + '.pvk'',
            ENCRYPTION BY PASSWORD = ''$(CertificateBackupPassword)''
        )'

        EXEC sp_executesql @SQL
        PRINT 'Backed up: ' + @CertName

        FETCH NEXT FROM cert_cursor INTO @CertName
    END

    CLOSE cert_cursor
    DEALLOCATE cert_cursor
END
GO
```

**3. Document Certificate Information**
```sql
-- Create inventory of TDE certificates
SELECT
    db.name AS database_name,
    c.name AS certificate_name,
    c.subject,
    c.thumbprint,
    c.start_date,
    c.expiry_date,
    c.pvt_key_last_backup_date
FROM sys.databases db
INNER JOIN sys.dm_database_encryption_keys dek ON db.database_id = dek.database_id
INNER JOIN sys.certificates c ON dek.encryptor_thumbprint = c.thumbprint
ORDER BY db.name
GO

-- Export to file for documentation
-- Store securely (contains sensitive information)
```

---

**Alternative: Migrate Without Downtime (Log Shipping)**

For very large databases, use TDE-enabled log shipping:

```sql
-- SOURCE server: Configure log shipping to TARGET
-- 1. Full backup with TDE certificate migrated first
-- 2. Log shipping configured (continuous restore)
-- 3. Cutover: Manual failover to target

-- Benefits:
-- - Minimal downtime (minutes instead of hours for 2TB)
-- - Automated synchronization
-- - Tested failover process
```

---

**Performance Considerations:**

| Aspect | TDE Impact | Mitigation |
|--------|------------|------------|
| Backup speed | 10-15% slower | Use backup compression |
| Restore speed | 10-15% slower | Fast storage (NVMe SSDs) |
| Backup size | No impact (compression still works) | COMPRESSION option |
| CPU usage | Moderate increase | Scale up CPU if needed |

---

### Q96: Your database has 85,000 VLFs (Virtual Log Files) and log backups are taking 45 minutes instead of 2 minutes. Explain the problem and provide complete remediation steps.

**Answer:**

**Symptoms:**
- Transaction log backups extremely slow (45 minutes for 50 GB log)
- Database startup/recovery slow (15+ minutes)
- Transaction log growth out of control
- Poor transaction performance during peak hours

**Root Cause:** Excessive VLF fragmentation caused by improper transaction log sizing and autogrowth settings.

---

**Diagnostic Process:**

**Step 1: Check VLF Count**
```sql
-- Check VLF count (SQL Server 2012+)
USE ProductionDB
GO

DBCC LOGINFO('ProductionDB')
GO

-- Count rows in result set = VLF count
-- Optimal: < 100 VLFs
-- Acceptable: 100-500 VLFs
-- Poor: 500-1000 VLFs
-- Critical: > 1000 VLFs (85,000 is catastrophic!)

-- Or use this query for count
SELECT
    DB_NAME(database_id) AS database_name,
    COUNT(*) AS vlf_count,
    SUM(vlf_size_mb) AS total_log_size_mb
FROM sys.dm_db_log_info(DB_ID('ProductionDB'))
GROUP BY database_id
GO

/* Example output:
database_name   vlf_count   total_log_size_mb
ProductionDB    85234       51200            ← Problem!
*/
```

**Step 2: Check Transaction Log Configuration**
```sql
-- Check transaction log settings
SELECT
    name,
    physical_name,
    size * 8 / 1024 AS size_mb,
    growth,
    is_percent_growth,
    CASE
        WHEN is_percent_growth = 1 THEN CAST(growth AS VARCHAR(10)) + '%'
        ELSE CAST(growth * 8 / 1024 AS VARCHAR(10)) + ' MB'
    END AS growth_setting
FROM sys.master_files
WHERE database_id = DB_ID('ProductionDB')
  AND type_desc = 'LOG'
GO

/* Example output (BAD configuration):
name              size_mb   growth  is_percent_growth  growth_setting
ProductionDB_log  51200     10      1                  10%            ← Problem!

Why bad:
- 10% growth on 50 GB = 5 GB autogrowth events
- Each large autogrowth creates many VLFs
- Leads to VLF fragmentation
*/
```

**Step 3: Measure Log Backup Performance**
```sql
-- Check log backup history
SELECT TOP 20
    database_name,
    backup_start_date,
    backup_finish_date,
    DATEDIFF(SECOND, backup_start_date, backup_finish_date) AS duration_seconds,
    backup_size / 1024 / 1024 AS backup_size_mb,
    compressed_backup_size / 1024 / 1024 AS compressed_size_mb
FROM msdb.dbo.backupset
WHERE database_name = 'ProductionDB'
  AND type = 'L'  -- Log backups
ORDER BY backup_start_date DESC
GO

/* Example output:
database_name  backup_start_date     duration_seconds  backup_size_mb
ProductionDB   2026-03-09 14:00:00   2700 (45 min!)    4500
ProductionDB   2026-03-09 13:45:00   2640              4200

Normal should be: ~120 seconds (2 minutes)
*/
```

---

**Remediation Process:**

**Critical:** Cannot fix VLF fragmentation while database is in use. Must shrink and rebuild log.

**Step 1: Backup Database First!**
```sql
-- Full backup before making changes
BACKUP DATABASE ProductionDB
TO DISK = 'C:\Backup\ProductionDB_BeforeVLFFix.bak'
WITH COMPRESSION, CHECKSUM, INIT
GO

-- Log backup
BACKUP LOG ProductionDB
TO DISK = 'C:\Backup\ProductionDB_Log_BeforeVLFFix.trn'
WITH COMPRESSION, CHECKSUM, INIT
GO
```

---

**Step 2: Truncate Transaction Log**
```sql
-- Option A: Backup transaction log (preserves log chain)
BACKUP LOG ProductionDB
TO DISK = 'C:\Backup\ProductionDB_Log_PreShrink.trn'
WITH COMPRESSION, INIT
GO

-- Option B: If you can break log chain, switch to SIMPLE temporarily
ALTER DATABASE ProductionDB SET RECOVERY SIMPLE
GO
CHECKPOINT
GO
```

---

**Step 3: Shrink Transaction Log**
```sql
-- Shrink log file to minimum size
USE ProductionDB
GO

-- Check current log usage
DBCC SQLPERF(LOGSPACE)
GO

/* Output:
Database Name    Log Size (MB)  Log Space Used (%)  Status
ProductionDB     51200          5.2                 0

Only 5% used = 2.6 GB of 51 GB
Can shrink significantly!
*/

-- Shrink log file to smallest possible size
DBCC SHRINKFILE(ProductionDB_log, 1)  -- Shrink to 1 MB
GO

-- Verify new size
SELECT
    name,
    size * 8 / 1024 AS size_mb
FROM sys.database_files
WHERE type_desc = 'LOG'
GO

/* After shrink:
name              size_mb
ProductionDB_log  128      ← Minimum size (varies by SQL version)
*/
```

---

**Step 4: Rebuild Transaction Log with Optimal VLF Count**

**Goal:** Create ~64-100 VLFs for optimal performance

**Method:** Grow log in specific increments (8 GB recommended)

```sql
-- Calculate target log size based on workload
-- Guideline: Size log to hold 4-6 hours of transactions

-- For this example: Target = 40 GB log file

-- Step 4a: Set log to size just under first growth target
ALTER DATABASE ProductionDB
MODIFY FILE (NAME = ProductionDB_log, SIZE = 8000MB)  -- Slightly under 8 GB
GO

-- This creates ~16 VLFs (SQL Server 2014+: 8 GB = 16 VLFs)

-- Step 4b: Grow in 8 GB increments
ALTER DATABASE ProductionDB
MODIFY FILE (NAME = ProductionDB_log, SIZE = 16000MB)
GO
-- Now have ~32 VLFs

ALTER DATABASE ProductionDB
MODIFY FILE (NAME = ProductionDB_log, SIZE = 24000MB)
GO
-- Now have ~48 VLFs

ALTER DATABASE ProductionDB
MODIFY FILE (NAME = ProductionDB_log, SIZE = 32000MB)
GO
-- Now have ~64 VLFs

ALTER DATABASE ProductionDB
MODIFY FILE (NAME = ProductionDB_log, SIZE = 40000MB)
GO
-- Now have ~80 VLFs ← Perfect!

-- Verify VLF count
SELECT COUNT(*) AS vlf_count
FROM sys.dm_db_log_info(DB_ID('ProductionDB'))
GO
-- Expected: ~80 VLFs (down from 85,000!)
```

**VLF Creation Algorithm (SQL Server 2014+):**
| Growth Size | VLFs Created |
|-------------|--------------|
| < 64 MB | 4 VLFs |
| 64 MB - 1 GB | 8 VLFs |
| > 1 GB - 8 GB | 16 VLFs |
| > 8 GB | 16 VLFs |

---

**Step 5: Configure Autogrowth**
```sql
-- Set fixed autogrowth (NOT percentage!)
ALTER DATABASE ProductionDB
MODIFY FILE (
    NAME = ProductionDB_log,
    FILEGROWTH = 1024MB  -- 1 GB fixed growth
)
GO

-- Verify setting
SELECT
    name,
    growth * 8 / 1024 AS growth_mb,
    is_percent_growth
FROM sys.master_files
WHERE database_id = DB_ID('ProductionDB')
  AND type_desc = 'LOG'
GO

/* Output:
name              growth_mb  is_percent_growth
ProductionDB_log  1024       0                ← Fixed size growth ✓
*/
```

---

**Step 6: Restore Full Recovery Model (if changed)**
```sql
-- Switch back to FULL recovery
ALTER DATABASE ProductionDB SET RECOVERY FULL
GO

-- Take full backup to establish new log chain
BACKUP DATABASE ProductionDB
TO DISK = 'C:\Backup\ProductionDB_AfterVLFFix.bak'
WITH COMPRESSION, CHECKSUM, INIT
GO
```

---

**Step 7: Verify Performance Improvement**
```sql
-- Test log backup speed
DECLARE @StartTime DATETIME2 = SYSDATETIME()

BACKUP LOG ProductionDB
TO DISK = 'C:\Backup\ProductionDB_Log_Test.trn'
WITH COMPRESSION, INIT
GO

SELECT DATEDIFF(SECOND, @StartTime, SYSDATETIME()) AS duration_seconds
GO

/* Expected result:
duration_seconds
120              ← 2 minutes (instead of 45 minutes!)

Speed improvement: 22.5x faster!
*/

-- Verify VLF count
SELECT COUNT(*) AS vlf_count
FROM sys.dm_db_log_info(DB_ID('ProductionDB'))
GO
-- Should show ~80 VLFs
```

---

**Monitoring and Prevention:**

**1. Create Alert for High VLF Count**
```sql
-- Create monitoring stored procedure
CREATE PROCEDURE dbo.CheckVLFCounts
AS
BEGIN
    SELECT
        DB_NAME(database_id) AS database_name,
        COUNT(*) AS vlf_count,
        CASE
            WHEN COUNT(*) > 1000 THEN 'CRITICAL'
            WHEN COUNT(*) > 500 THEN 'WARNING'
            ELSE 'OK'
        END AS status
    FROM sys.dm_db_log_info(NULL)
    WHERE database_id > 4  -- Skip system databases
    GROUP BY database_id
    HAVING COUNT(*) > 500
    ORDER BY vlf_count DESC
END
GO

-- Schedule SQL Agent job to run daily
-- Send email if any database > 1000 VLFs
```

**2. Proactive Log Sizing**
```sql
-- Size transaction logs appropriately at database creation
CREATE DATABASE NewDatabase
ON PRIMARY (
    NAME = NewDatabase_Data,
    FILENAME = 'E:\SQLData\NewDatabase.mdf',
    SIZE = 10 GB,
    FILEGROWTH = 1 GB
)
LOG ON (
    NAME = NewDatabase_Log,
    FILENAME = 'F:\SQLLogs\NewDatabase_log.ldf',
    SIZE = 10 GB,  -- Size to hold 4-6 hours of transactions
    FILEGROWTH = 1 GB  -- Fixed growth, not percentage!
)
GO
```

**3. Regular Maintenance**
```sql
-- Monthly check for databases needing log optimization
SELECT
    db.name AS database_name,
    mf.size * 8 / 1024 AS log_size_mb,
    mf.growth,
    mf.is_percent_growth,
    vlf.vlf_count,
    CASE
        WHEN vlf.vlf_count > 1000 THEN 'Rebuild Log Needed'
        WHEN vlf.vlf_count > 500 THEN 'Monitor Closely'
        ELSE 'OK'
    END AS recommendation
FROM sys.databases db
INNER JOIN sys.master_files mf ON db.database_id = mf.database_id
CROSS APPLY (
    SELECT COUNT(*) AS vlf_count
    FROM sys.dm_db_log_info(db.database_id)
) vlf
WHERE mf.type_desc = 'LOG'
  AND db.database_id > 4
ORDER BY vlf.vlf_count DESC
GO
```

---

**Alternative Method: Copy Database**

For very large databases where downtime is acceptable:

```sql
-- Alternative: Restore database to new files (auto-creates optimal VLFs)
-- 1. Backup database
BACKUP DATABASE ProductionDB TO DISK = 'C:\Backup\ProductionDB.bak'

-- 2. Restore to new location with pre-sized log
RESTORE DATABASE ProductionDB_New
FROM DISK = 'C:\Backup\ProductionDB.bak'
WITH MOVE 'ProductionDB' TO 'E:\SQLData\ProductionDB_New.mdf',
     MOVE 'ProductionDB_log' TO 'F:\SQLLogs\ProductionDB_New_log.ldf',
     REPLACE
GO

-- 3. Drop old database, rename new one
-- 4. Verify VLF count on restored database
-- Restore process creates optimal VLFs automatically!
```

---

**Performance Impact Comparison:**

| Metric | Before (85K VLFs) | After (~80 VLFs) | Improvement |
|--------|-------------------|------------------|-------------|
| Log backup duration | 45 minutes | 2 minutes | 22.5x faster |
| Database startup | 15 minutes | 30 seconds | 30x faster |
| Transaction throughput | 2,000 TPS | 8,000 TPS | 4x faster |
| Log growth operations | 60 seconds | 1 second | 60x faster |

---

## Sources & References

### Official Microsoft Documentation
- [Failover Cluster Troubleshooting - Microsoft Learn](https://learn.microsoft.com/en-us/sql/sql-server/failover-clusters/windows/failover-cluster-troubleshooting)
- [AlwaysOn Availability Groups Troubleshooting](https://learn.microsoft.com/en-us/sql/database-engine/availability-groups/windows/troubleshoot-always-on-availability-groups-configuration)
- [Query Store Best Practices](https://learn.microsoft.com/en-us/sql/relational-databases/performance/best-practice-with-the-query-store)

### Interview Questions Resources
- [SQL Server AlwaysOn AG Interview Questions - SQLShack](https://www.sqlshack.com/sql-server-always-on-availability-groups-interview-questions-answers/)
- [AlwaysOn Interview Questions Part 1 - MSSQLTips](https://www.mssqltips.com/sqlservertip/5474/sql-server-alwayson-interview-questions-and-answers-part-1/)
- [AlwaysOn Interview Questions Part 2 - MSSQLTips](https://www.mssqltips.com/sqlservertip/5719/sql-server-alwayson-interview-questions-and-answers-part-2/)
- [DBA Mantra - Always On Interview Questions](https://dbamantra.com/sql-server-dba-interview-questions-answers-always-on-availability-group/)
- [SQL Performance Tuning Interview Questions - TechBeamers](https://techbeamers.com/sql-performance-interview-questions-answers/)
- [Performance Tuning Questions - MSSQLTips](https://www.mssqltips.com/sqlservertip/1429/sql-server-dba-performance-tuning-interview-questions/)
- [SQL Performance Tuning Scenarios - Medium](https://medium.com/itversity/sql-performance-tuning-10-real-world-scenarios-and-interview-prep-tips-da095c5f103f)
- [Query Optimization Interview Questions - DBVis](https://www.dbvis.com/thetable/top-sql-performance-tuning-interview-questions-and-answers/)
- [Deadlocks Interview Q&A - SQL Authority](https://blog.sqlauthority.com/2023/06/23/sql-server-deadlocks-interview-q-and-a/)
- [SQL Server Locking Interview Questions - MSSQLTips](https://www.mssqltips.com/sqlservertip/1253/sql-server-dba-concurrency-and-locking-interview-questions/)
- [Indexes Interview Questions - SQLShack](https://www.sqlshack.com/top-25-sql-interview-questions-and-answers-about-indexes/)

### Technical Deep-Dive Resources (mssqlwiki.com)
- [Tempdb Latch Contention Optimization - mssqlwiki](https://mssqlwiki.com/2013/09/17/tempdb-latch-contention/)
  - PFS/SGAM page contention, multiple data files, proportional fill algorithm
  - SQL Server 2019+ memory-optimized tempdb metadata
  - Trace flag 1118 for uniform extent allocations
- [Parameter Sniffing Deep Dive - mssqlwiki](https://mssqlwiki.com/2012/10/08/parameter-sniffing/)
  - RECOMPILE, OPTIMIZE FOR, local variable techniques
  - Query Store plan forcing
  - Plan guides and dynamic SQL approaches
- [Non-Yielding Scheduler Troubleshooting - mssqlwiki](https://mssqlwiki.com/)
  - SQLOS cooperative scheduling, quantum violations
  - Dump analysis with WinDbg
  - Common causes: antivirus, drivers, CLR code, spinlock contention
- [SQL Server Memory Architecture - mssqlwiki] — context link already listed above; specific page requires validation
  - Buffer pool management, memory clerks
  - Page life expectancy guidelines
  - Resource Governor memory limits
- [SQLOS Internals - mssqlwiki] — context link already listed above; specific page requires validation
  - Scheduler architecture, worker threads, quantum management
  - Wait statistics and spinlock analysis

### Advanced Backup, Restore & Disaster Recovery Resources
- [Restore Database to Point in Time - Microsoft Learn](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/restore-a-sql-server-database-to-a-point-in-time-full-recovery-model?view=sql-server-ver17)
- [Disaster Recovery 101: Backing Up the Tail of the Log - SQLSkills (Paul Randal)](https://www.sqlskills.com/blogs/paul/disaster-recovery-101-backing-up-the-tail-of-the-log/)
- [SQL Server Point in Time Recovery - MSSQLTips](https://www.mssqltips.com/sqlservertip/1229/sql-server-point-in-time-recovery/)
- [SQL Server Point in Time Restore - STOPAT - MSSQLTips](https://www.mssqltips.com/sqlservertutorial/119/sql-server-point-in-time-restore/)
- [Point-in-Time Recovery with SQL Server - SQL Shack](https://www.sqlshack.com/point-in-time-recovery-with-sql-server/)
- [Piecemeal Restores - Microsoft Learn](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/piecemeal-restores-sql-server?view=sql-server-ver17)
- [Database Filegroups and Piecemeal Restores - SQL Shack](https://www.sqlshack.com/database-filegroups-and-piecemeal-restores-in-sql-server/)
- [Piecemeal Restore of Filegroups - Microsoft Learn](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/example-piecemeal-restore-of-only-some-filegroups-full-recovery-model?view=sql-server-ver16)
- [Recognizing Corrupted SQL Backup Files - SQL Shack](https://www.sqlshack.com/how-to-recognize-corrupted-sql-backup-files/)
- [CHECKSUM and VERIFYONLY - SQL Backup Academy](https://sqlbak.com/academy/checksum-and-verifyonly/)
- [RESTORE VERIFYONLY and CHECKSUM Options - SQLBackupAndFTP](https://sqlbackupandftp.com/blog/restore-verifyonly-and-checksum/)
- [Validate SQL Server Backups - MSSQLTips](https://www.mssqltips.com/sqlservertip/4454/validate-a-sql-server-backup-can-be-restored/)
- [Media Errors During Backup and Restore - Microsoft Learn](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/possible-media-errors-during-backup-and-restore-sql-server?view=sql-server-ver16)
- [Backup Chain and LSN Sequence - SQL Backup Academy](https://sqlbak.com/academy/backup-chain/)
- [Understanding Log Sequence Numbers - SQL Shack](https://www.sqlshack.com/understanding-log-sequence-numbers-for-sql-server-transaction-log-backups-and-full-backups/)
- [Unable to Create Restore Plan Due to Break in LSN Chain - SQLBackupAndFTP](https://sqlbackupandftp.com/blog/unable-create-restore-plan-due-break-lsn-chain/)
- [Restoring TDE-Enabled Databases on Different Server - SQL Shack](https://www.sqlshack.com/restoring-transparent-data-encryption-tde-enabled-databases-on-a-different-server/)
- [Move TDE-Protected Database - Microsoft Learn](https://learn.microsoft.com/en-us/sql/relational-databases/security/encryption/move-a-tde-protected-database-to-another-sql-server?view=sql-server-ver17)
- [TDE and SQL Server Database Backups - SQL Backup Master](https://www.sqlbackupmaster.com/wordpress/2025/08/20/tde-and-sql-server-database-backups-the-critical-piece-everyone-forgets/)
- [SQL Server Log Shipping Disaster Recovery - DZone](https://dzone.com/articles/sql-server-disaster-recovery-with-log-shipping)
- [Log Shipping Manual Failover Steps - SqlSchoolHouse](https://sqlschoolhouse.wordpress.com/2010/09/06/log-shipping-manual-failover-steps/)
- [Automate Log Shipping Failover - MSSQLTips](https://www.mssqltips.com/sqlservertip/1516/automate-restoration-of-log-shipping-databases-for-failover-in-sql-server/)
- [Backup Compression - Microsoft Learn](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/backup-compression-sql-server?view=sql-server-ver17)
- [Backup Compression with TDE - MSSQLTips](https://www.mssqltips.com/sqlservertip/4522/backup-compression-performance-enhancements-for-sql-server-2016-tde-enabled-databases/)
- [SQL Server Backup Encryption and Compression - Matthew McGiffen Data](https://matthewmcgiffen.com/2023/05/24/sql-server-backup-encryption-and-compression/)
- [Copy-Only Backups - Microsoft Learn](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/copy-only-backups-sql-server?view=sql-server-ver17)
- [SQL Server COPY_ONLY Backup Why and How - SqlBak](https://sqlbak.com/blog/sql-server-copy-only-backup-why-and-how/)
- [Offload Backups to Secondary Replicas - Microsoft Learn](https://learn.microsoft.com/en-us/sql/database-engine/availability-groups/windows/active-secondaries-backup-on-secondary-replicas-always-on-availability-groups?view=sql-server-ver17)
- [Performance Issue with Large Number of VLFs - MSSQLTips](https://www.mssqltips.com/sqlservertip/2107/performance-issue-with-large-number-of-virtual-log-files-in-sql-server-transaction-log/)
- [SQL Server Transaction Log Fragmentation - Simple Talk](https://www.red-gate.com/simple-talk/databases/sql-server/database-administration-sql-server/sql-server-transaction-log-fragmentation-a-primer/)
- [Virtual Log Files in Transaction Log - SQL Shack](https://www.sqlshack.com/virtual-log-files-sql-server-transaction-log/)
- [8 Steps to Better Transaction Log Throughput - SQLSkills (Kimberly Tripp)](https://www.sqlskills.com/blogs/kimberly/8-steps-to-better-transaction-log-throughput/)
- [Managing Virtual Log Files SQL Server 2022 - SQL Authority](https://blog.sqlauthority.com/2023/02/28/sql-server-2022-managing-virtual-log-files/)

### System Database Corruption & Recovery Resources
- [Rebuild System Databases - Microsoft Learn](https://learn.microsoft.com/en-us/sql/relational-databases/databases/rebuild-system-databases?view=sql-server-ver17)
- [Restore Master Database - Microsoft Learn](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/restore-the-master-database-transact-sql?view=sql-server-ver17)
- [DBCC CHECKDB Documentation - Microsoft Learn](https://learn.microsoft.com/en-us/sql/t-sql/database-console-commands/dbcc-checkdb-transact-sql?view=sql-server-ver17)
- [Trace Flags Documentation - Microsoft Learn](https://learn.microsoft.com/en-us/sql/t-sql/database-console-commands/dbcc-traceon-trace-flags-transact-sql?view=sql-server-ver17)
- [Restore SQL Server Master Database Options - MSSQLTips](https://www.mssqltips.com/sqlservertip/6226/restore-sql-server-master-database-options/)
- [How to Restore Model Database - MSSQLTips](https://www.mssqltips.com/sqlservertip/6237/how-to-restore-model-database-in-sql-server/)
- [Restoring msdb and model Databases - MSSQLTips](https://www.mssqltips.com/sqlservertip/2571/restoring-sql-server-system-databases-msdb-and-model/)
- [Rebuild System Databases in SQL Server - MSSQLTips](https://www.mssqltips.com/sqlservertip/6911/rebuild-system-databases-in-sql-server/)
- [SQL Database Corruption and CHECKDB REPAIR_ALLOW_DATA_LOSS - MSSQLTips](https://www.mssqltips.com/sqlservertip/5645/sql-server-database-corruption-and-impact-of-running-checkdb-repair-with-allow-data-loss/)
- [Recover SQL Server Resource Database - MSSQLTips](https://www.mssqltips.com/sqlservertip/6194/recover-sql-server-resource-database/)
- [SQL Server EMERGENCY Mode Repair - SQLSkills](https://www.sqlskills.com/blogs/paul/checkdb-from-every-angle-emergency-mode-repair-the-very-very-last-resort/)
- [What to Do When DBCC CHECKDB Reports Corruption - Brent Ozar](https://www.brentozar.com/archive/2016/05/dbcc-checkdb-reports-corruption/)
- [SQL Server Resource Database Corruption - Microsoft Learn Archive](https://learn.microsoft.com/en-us/archive/blogs/sqljourney/sql-server-resource-database-corruptionyes-its-possible)
- [Trace Flag 3608 - SQLMaestros](https://sqlmaestros.com/sql-server-trace-flag-3608-might-encounter/)
- [SQL Server Trace Flag 3608 - SQL Server Geeks](https://www.sqlservergeeks.com/sql-server-trace-flag-3608/)
- [Rebuild System Databases: Recovery Strategies - Rackspace](https://www.rackspace.com/blog/rebuild-system-databases)
- [How to Rebuild and Restore SQL Server Master Database - Information Security Buzz](https://informationsecuritybuzz.com/how-to-rebuild-and-restore-sql-server-master-database/)
- [SQL Server Model Database Repair - Dell](https://www.dell.com/support/kbdoc/en-us/000134526/sql-server-model-database-repair)
- [Microsoft SQL Server MSDB Database Recovery - Dell](https://www.dell.com/support/kbdoc/en-us/000200606/microsoft-sql-server-msdb-database-recovery)

### Additional Technical Resources
- [Brent Ozar Unlimited - First Responder Kit](https://www.brentozar.com/first-aid/)
- [Glenn Berry's Diagnostic Queries](https://glennsqlperformance.com/)
- [Ola Hallengren's Maintenance Solution](https://ola.hallengren.com/)
- [Adam Machanic's sp_WhoIsActive](http://whoisactive.com/)

---

**Document prepared:** March 2026
**Target Audience:** SQL Server DBA L3/L4 positions
**Current Status:** 33 comprehensive scenario-based questions with detailed troubleshooting guides, diagnostic queries, and resolution strategies

**Coverage:**
- Section 1: AlwaysOn Availability Groups (10 questions: Q1-Q10)
- Section 2: Performance Tuning & Query Optimization (9 questions: Q36-Q44)
- Section 3: Wait Statistics, Blocking & Deadlocks (3 questions: Q66-Q68)
- Section 4: Indexing & Execution Plans (2 questions: Q86-Q87)
- Section 5: System Database Corruption & Recovery (4 questions: Q88-Q91)
- Section 6: Advanced Backup, Restore & Disaster Recovery (5 questions: Q92-Q96)

**Key Features:**
- Real-world production scenarios
- Complete diagnostic T-SQL queries
- Step-by-step troubleshooting workflows
- Resolution strategies with code examples
- Prevention and monitoring guidance
- Insights from mssqlwiki.com technical articles
- Enterprise-grade best practices

**Note:** This document provides in-depth, production-ready content for senior DBA positions. Each question includes educational diagnostic queries and hypothetical context. Validate permissions, columns, and behavior for the exact SQL Server build before execution.
