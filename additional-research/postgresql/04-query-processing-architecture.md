# POSTGRESQL ARCHITECTURE & END-TO-END QUERY EXECUTION INTERNALS

> **Publication and applicability note (reviewed 2026-08-03):** This is independently reviewed, supplemental research, not canonical ATS/RAG implementation documentation. All operational scenarios and examples are hypothetical. PostgreSQL internals, defaults, statistics behavior, extensions, and monitoring views vary by major/minor version and build; verify against the documentation and source for the exact target version. Numeric settings are lab illustrations, not universal production recommendations.

## Complete Technical Deep Dive: From Client Request to Data Return

---

## Table of Contents

1. [Introduction](#introduction)
2. [PostgreSQL Architecture Overview](#postgresql-architecture-overview)
3. [Network Layer: Connection Protocol and Session Management](#network-layer-connection-protocol-and-session-management)
4. [Process Architecture: Postmaster and Backend Processes](#process-architecture-postmaster-and-backend-processes)
5. [Query Processing Pipeline](#query-processing-pipeline)
6. [Parser Stage: Lexical and Syntax Analysis](#parser-stage-lexical-and-syntax-analysis)
7. [Rewriter Stage: Rule System and View Expansion](#rewriter-stage-rule-system-and-view-expansion)
8. [Planner Stage: Cost-Based Optimization](#planner-stage-cost-based-optimization)
9. [Executor Stage: Plan Execution and Iterator Model](#executor-stage-plan-execution-and-iterator-model)
10. [Storage Layer: Pages, TOAST, and MVCC](#storage-layer-pages-toast-and-mvcc)
11. [Buffer Management: shared_buffers and Page Cache](#buffer-management-shared_buffers-and-page-cache)
12. [MVCC: Multi-Version Concurrency Control](#mvcc-multi-version-concurrency-control)
13. [Transaction Management: WAL and Checkpoints](#transaction-management-wal-and-checkpoints)
14. [Vacuum System: Dead Tuple Cleanup](#vacuum-system-dead-tuple-cleanup)
15. [Lock Management: Lightweight Locks and Heavyweight Locks](#lock-management-lightweight-locks-and-heavyweight-locks)
16. [Index Access Methods: B-tree, Hash, GiST, GIN, BRIN](#index-access-methods)
17. [Parallel Query Execution](#parallel-query-execution)
18. [Performance Monitoring: Cumulative Statistics and pg_stat Views (version-sensitive)](#performance-monitoring)

---

## Introduction

This document provides a comprehensive, end-to-end exploration of PostgreSQL query execution from the moment a client application submits a SELECT request until results are returned. It is designed for database professionals with deep SQL Server experience transitioning to PostgreSQL Principal/Staff roles.

**Execution Flow Summary:**
1. Client application sends query via PostgreSQL protocol over TCP/IP
2. Postmaster accepts connection or assigns to existing backend process
3. Backend process receives query text
4. Parser converts SQL text to parse tree
5. Rewriter applies rules and expands views
6. Planner generates optimal execution plan using cost-based analysis
7. Executor runs plan using iterator model
8. Storage layer reads pages using MVCC visibility rules
9. Results flow back through network to client

---

## PostgreSQL Architecture Overview

### High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENT APPLICATION                           │
│                    (psql, JDBC, .NET, Python, etc.)                  │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    │ PostgreSQL Protocol (TCP/IP)
                                    │ Port 5432
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         POSTMASTER PROCESS                           │
│                  (postgres.exe -D data_directory)                    │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Connection Handling & Process Management                     │  │
│  │  - Accepts new connections                                    │  │
│  │  - Authenticates users (pg_hba.conf)                          │  │
│  │  - Creates a dedicated backend process per connection using platform-specific process creation                       │  │
│  │  - Manages background worker processes                        │  │
│  └──────────────────────────────────────────────────────────────┘  │
└───────────────────────┬───────────────────────────────────────────┬─┘
                        │                                           │
         ┌──────────────┴──────────────┐               ┌───────────┴──────────┐
         │                             │               │                      │
         ▼                             ▼               ▼                      ▼
┌──────────────────┐       ┌────────────────────┐    ┌──────────────┐  ┌─────────────┐
│  BACKEND PROCESS │       │  BACKEND PROCESS   │    │ BACKGROUND   │  │ BACKGROUND  │
│  (Connection 1)  │  ...  │  (Connection N)    │    │ PROCESSES:   │  │ PROCESSES:  │
│                  │       │                    │    │              │  │             │
│ ┌──────────────┐│       │ ┌──────────────┐  │    │ •Checkpointer│  │•Autovacuum  │
│ │ Parser       ││       │ │ Parser       │  │    │ •BG Writer   │  │ Launcher    │
│ │ Rewriter     ││       │ │ Rewriter     │  │    │ •WAL Writer  │  │•Stats       │
│ │ Planner      ││       │ │ Planner      │  │    │ •Archiver    │  │ Collector   │
│ │ Executor     ││       │ │ Executor     │  │    │              │  │•Logical Rep │
│ └──────────────┘│       │ └──────────────┘  │    │              │  │ Launcher    │
│                  │       │                    │    └──────────────┘  └─────────────┘
│  work_mem        │       │  work_mem          │
│  temp_buffers    │       │  temp_buffers      │
└──────┬───────────┘       └────────┬───────────┘
       │                            │
       │                            │
       └────────────┬───────────────┘
                    │
                    │ IPC via Shared Memory
                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      SHARED MEMORY AREA                              │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  shared_buffers (Buffer Cache - default 128MB)              │   │
│  │  - Caches data pages (8KB each)                             │   │
│  │  - Clock-sweep replacement using per-buffer usage counts                                       │   │
│  │  - Shared across all backend processes                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  WAL Buffers (wal_buffers - default 16MB)                   │   │
│  │  - Transaction log buffer                                    │   │
│  │  - Flushed to WAL files by WAL writer                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Lock Tables (max_locks_per_transaction)                    │   │
│  │  - Heavyweight locks (table, row, transaction)               │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  CLOG (Commit Log) & Visibility Maps                        │   │
│  │  - Transaction commit status                                 │   │
│  │  - MVCC visibility information                               │   │
│  └─────────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬───────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         STORAGE LAYER                                │
│                                                                       │
│  ┌─────────────────────┐  ┌─────────────────────┐                  │
│  │  Data Files         │  │  WAL Files          │                  │
│  │  (base/dboid/)      │  │  (pg_wal/)          │                  │
│  │                     │  │                     │                  │
│  │  • Tables (heap)    │  │  • 16MB segments    │                  │
│  │  • Indexes (btree)  │  │  • Write-Ahead Log  │                  │
│  │  • TOAST tables     │  │  • Continuous write │                  │
│  └─────────────────────┘  └─────────────────────┘                  │
│                                                                       │
│  ┌─────────────────────┐  ┌─────────────────────┐                  │
│  │  Transaction State  │  │  Statistics Files   │                  │
│  │  (pg_xact/)         │  │  (implementation varies by version)     │                  │
│  └─────────────────────┘  └─────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Principles

**1. Multi-Process Architecture (Not Multi-Threaded)**
- Each client connection = dedicated backend process (postgres.exe)
- Processes communicate via shared memory (not message passing)
- Per-connection process overhead can make connection pooling valuable; validate the need and pool mode for the workload

**2. MVCC (Multi-Version Concurrency Control)**
- Readers never block writers, writers never block readers
- Dead tuples (old row versions) accumulate → VACUUM required
- No equivalent to SQL Server's snapshot isolation overhead (versioning is native)

**3. Write-Ahead Logging (WAL)**
- All changes logged to WAL before data pages modified
- 16MB segments recycled continuously
- Basis for PITR, replication, and crash recovery

**4. Shared Memory Model**
- shared_buffers: Data page cache (default 128MB, size from measured workload and concurrency; avoid fixed percentages)
- WAL buffers: Transaction log buffer
- Lock tables: Transaction and row-level locks
- CLOG: Transaction commit status for MVCC

---

## Network Layer: Connection Protocol and Session Management

### PostgreSQL Wire Protocol

PostgreSQL uses a custom **binary protocol** for client-server communication over TCP/IP (default port 5432). Unlike SQL Server's TDS protocol, PostgreSQL's protocol is:
- **Message-based**: Each message has a type and length
- **Stateful**: Connection maintains session state (SET variables, temp tables, prepared statements)
- **Supports both text and binary formats** for parameters and results

**Protocol Message Types:**

```
Client → Server Messages:
├── StartupMessage: Initial connection request with database, user
├── Query (Q): Simple query (unparsed SQL text)
├── Parse (P): Parse SQL into prepared statement
├── Bind (B): Bind parameters to prepared statement
├── Execute (E): Execute bound statement
├── Describe (D): Get result column metadata
├── Sync (S): Sync point for transaction boundary
├── Terminate (X): Close connection
└── CopyData: Bulk data transfer (COPY command)

Server → Client Messages:
├── AuthenticationOk/AuthenticationMD5: Authentication challenge/success
├── ParameterStatus: Server parameter values
├── ReadyForQuery (Z): Ready to accept new command
├── RowDescription: Result set column metadata
├── DataRow: Result row data
├── CommandComplete: Query execution finished
├── ErrorResponse: Error message
└── NoticeResponse: Warning message
```

**Message Structure:**

```
Message Format (all multi-byte integers are big-endian):
┌────────────────────────────────────┐
│ Type (1 byte)                      │ 'Q' = Query, 'P' = Parse, etc.
├────────────────────────────────────┤
│ Length (4 bytes)                   │ Message length (including self, excluding type)
├────────────────────────────────────┤
│ Payload (variable length)          │ Message-specific data
└────────────────────────────────────┘

Example: Simple Query Message
Type: 'Q' (0x51)
Length: 27 (4 + 23)
Payload: "SELECT * FROM users\0" (null-terminated string)
```

### Connection Lifecycle

**Connection Establishment Flow:**

```
Client                                  Postmaster                    Backend Process
  |                                         |                               |
  |--- TCP SYN ---------------------->     |                               |
  |<-- TCP SYN-ACK -------------------      |                               |
  |--- TCP ACK ---------------------->     |                               |
  |                                         |                               |
  |--- StartupMessage ---------------->     |                               |
  |    (user, database, protocol)           |                               |
  |                                         | [Check pg_hba.conf]           |
  |                                         | [Authenticate user]           |
  |<-- AuthenticationMD5Password ------     |                               |
  |    (salt value)                         |                               |
  |--- PasswordMessage ---------------->     |                               |
  |    (MD5 hashed password)                |                               |
  |                                         | [Verify password]             |
  |                                         |                               |
  |                                         |--- fork() --------------->    |
  |                                         |    Create backend process     |
  |                                         |                               |
  |<-- AuthenticationOk -------------------------<-- [Auth success] ----    |
  |<-- ParameterStatus (multiple) ---------------<-- [Session params] --    |
  |<-- ReadyForQuery (Z) ------------------------<-- [Ready] -----------    |
  |    Transaction status: Idle                                             |
  |                                                                          |
  |--- Query Message (Q) ------------------------------------->             |
  |    "SELECT * FROM customers WHERE id = 123"                             |
  |                                                             [Parse SQL]  |
  |                                                             [Plan query] |
  |                                                             [Execute]    |
  |<-- RowDescription ----------------------------------<--    [Columns]    |
  |<-- DataRow (multiple) ---------------------------<--    [Rows]          |
  |<-- CommandComplete ------------------------------<--    [Done]          |
  |<-- ReadyForQuery (Z) ----------------------------<--    [Ready]         |
```

**Connection Management Pseudocode:**

```c
/* postmaster.c - Simplified connection handling */

int ServerLoop(void) {
    Port *port;

    for (;;) {
        /* Accept new connection on listening socket */
        port = AcceptConnection();

        if (port == NULL) {
            continue;  /* Error or signal, retry */
        }

        /* Fork backend process to handle connection */
        pid_t pid = fork();

        if (pid == 0) {
            /* Child process: backend */
            CloseListenerSocket();
            BackendMain(port);
            exit(0);
        } else if (pid > 0) {
            /* Parent process: postmaster */
            CloseClientSocket(port);
            RegisterBackendProcess(pid, port);
        } else {
            /* Fork failed */
            ReportError("fork() failed");
            CloseClientSocket(port);
        }
    }
}

void BackendMain(Port *port) {
    /* Authenticate client */
    if (!PerformAuthentication(port)) {
        SendAuthenticationError(port);
        return;
    }

    /* Send authentication success */
    SendAuthenticationOk(port);

    /* Send session parameter status */
    SendParameterStatus(port, "server_version", PG_VERSION);
    SendParameterStatus(port, "server_encoding", GetDatabaseEncoding());
    SendParameterStatus(port, "client_encoding", "UTF8");

    /* Send ready for query */
    SendReadyForQuery(port, TRANS_IDLE);

    /* Main query loop */
    for (;;) {
        int message_type;

        /* Read next message from client */
        message_type = ReadMessageType(port);

        switch (message_type) {
            case 'Q':  /* Simple query */
                HandleSimpleQuery(port);
                break;

            case 'P':  /* Parse (prepared statement) */
                HandleParse(port);
                break;

            case 'B':  /* Bind */
                HandleBind(port);
                break;

            case 'E':  /* Execute */
                HandleExecute(port);
                break;

            case 'X':  /* Terminate */
                return;  /* Clean exit */

            default:
                ReportProtocolError(port);
        }
    }
}
```

### Authentication: pg_hba.conf

PostgreSQL's **Host-Based Authentication** (HBA) file controls connection access:

```
# pg_hba.conf format:
# TYPE  DATABASE  USER  ADDRESS       METHOD

# Local connections (Windows named pipe or Unix socket)
local   all       all                 md5

# IPv4 connections
host    all       all   127.0.0.1/32  md5
host    all       all   10.0.0.0/8    md5

# IPv6 connections
host    all       all   ::1/128       md5

# SSL connections only
hostssl production app_user 192.168.1.0/24 md5

# Trust (no password) for local admin
local   all       postgres            trust
```

**Authentication Methods:**
- **trust**: No authentication (dangerous!)
- **md5**: MD5-hashed password (default, legacy)
- **scram-sha-256**: Modern SCRAM authentication (recommended)
- **password**: Plaintext password (never use in production)
- **gss/sspi**: Kerberos/Windows integrated auth
- **peer/ident**: OS user identity verification

---

## Process Architecture: Postmaster and Backend Processes

### Postmaster Process (Master Daemon)

The **postmaster** is the parent process for the entire PostgreSQL instance:

**Responsibilities:**
1. **Listen for connections** on TCP port 5432
2. **Fork backend processes** for each new connection
3. **Spawn background workers** (checkpointer, WAL writer, etc.)
4. **Monitor child processes** and restart on crash
5. **Handle shutdown** (smart, fast, immediate modes)

**Postmaster State Machine:**

```
Postmaster States:
PM_INIT        → Starting up, reading config
PM_STARTUP     → Running crash recovery
PM_RECOVERY    → Running archive recovery (PITR)
PM_HOT_STANDBY → Standby mode, accepting read-only connections
PM_RUN         → Normal operation
PM_WAIT_BACKUP → Waiting for backup to finish
PM_SHUTDOWN    → Shutting down
PM_STOP_BACKENDS → Terminating backends
PM_WAIT_DEAD_END → Waiting for dead-end children
```

### Backend Process Anatomy

Each client connection gets a **dedicated backend process**:

```
Backend Process Memory Layout:
┌─────────────────────────────────────────┐
│  Process Code & Stack                   │
├─────────────────────────────────────────┤
│  Backend-Private Memory:                │
│  • work_mem (sort/hash operations)      │
│  • maintenance_work_mem (VACUUM, INDEX) │
│  • temp_buffers (temp tables)           │
│  • Per-query executor state             │
│  • Cached catalogs (pg_class, etc.)     │
└─────────────────────────────────────────┘
         │
         │ IPC via Shared Memory
         ▼
┌─────────────────────────────────────────┐
│  Shared Memory (all backends):          │
│  • shared_buffers (buffer pool)         │
│  • WAL buffers                           │
│  • Lock tables                           │
│  • CLOG (transaction commit log)        │
└─────────────────────────────────────────┘
```

**Critical Backend Parameters:**

| Parameter | SQL Server Equivalent | Default | Recommendation |
|-----------|----------------------|---------|----------------|
| **work_mem** | Memory grant per sort/hash | Version default | Derive from concurrent sort/hash demand and spill observations; no universal formula |
| **maintenance_work_mem** | No equivalent | Version default | Size from maintenance concurrency, object size, and memory headroom |
| **temp_buffers** | tempdb per session | 8MB | 8-16MB |
| **shared_buffers** | Buffer Pool | 128MB | workload- and concurrency-dependent; benchmark |

**Backend Process Lifecycle Pseudocode:**

```c
/* postgres.c - Backend main entry point */

void PostgresMain(Port *port) {
    /* Initialize backend process */
    InitializeBackend(port);

    /* Attach to shared memory */
    AttachSharedMemory();

    /* Set session parameters */
    SetSessionUser(port->user);
    SetSessionDatabase(port->database);

    /* Initialize memory contexts */
    MemoryContext query_context = AllocSetContextCreate(
        TopMemoryContext, "QueryContext", ALLOCSET_DEFAULT_SIZES
    );

    /* Main command loop */
    for (;;) {
        /* Read command from client */
        StringInfo query_string = ReadCommand(port);

        if (query_string == NULL) {
            break;  /* Connection closed */
        }

        /* Switch to query memory context (auto-freed after query) */
        MemoryContextSwitchTo(query_context);

        /* Start transaction block if needed */
        if (!IsTransactionState()) {
            StartTransactionCommand();
        }

        /* Process query */
        ProcessQuery(query_string, port);

        /* Commit transaction */
        CommitTransactionCommand();

        /* Reset query context (free memory) */
        MemoryContextReset(query_context);

        /* Send ready for next query */
        SendReadyForQuery(port);
    }

    /* Cleanup and exit */
    DetachSharedMemory();
    CloseConnection(port);
}
```

### Background Worker Processes

PostgreSQL spawns several background processes for housekeeping:

**1. Checkpointer Process**

Writes dirty pages from shared_buffers to data files:

```c
/* checkpointer.c - Simplified */

void CheckpointerMain(void) {
    for (;;) {
        /* Wait for checkpoint timeout or max_wal_size trigger */
        TimestampTz next_checkpoint = GetNextCheckpointTime();
        WaitForCheckpointTrigger(next_checkpoint);

        /* Start checkpoint */
        StartCheckpoint(CHECKPOINT_IMMEDIATE);

        /* Write all dirty buffers to disk */
        int num_written = WriteAllDirtyBuffers();

        /* Fsync data files */
        SyncDataFiles();

        /* Update checkpoint record in WAL */
        WriteCheckpointRecord();

        /* Update control file */
        UpdateControlFile();

        LogCheckpointStats(num_written);
    }
}

int WriteAllDirtyBuffers(void) {
    int num_written = 0;

    /* Scan shared_buffers for dirty pages */
    for (int i = 0; i < NBuffers; i++) {
        BufferDesc *buf = GetBufferDescriptor(i);

        if (buf->flags & BM_DIRTY) {
            /* Write buffer to disk */
            FlushBuffer(buf);
            num_written++;
        }
    }

    return num_written;
}
```

**Checkpoint Triggers:**
- **checkpoint_timeout**: Default 5 minutes (vs. SQL Server's variable checkpoint based on log activity)
- **max_wal_size**: Default 1GB of WAL generated
- **Manual CHECKPOINT command**

**2. Background Writer (bgwriter)**

Continuously writes dirty buffers to reduce checkpoint I/O spikes:

```c
/* bgwriter.c */

void BackgroundWriterMain(void) {
    for (;;) {
        /* Sleep for bgwriter_delay (default 200ms) */
        pg_usleep(bgwriter_delay * 1000L);

        /* Write some dirty buffers */
        int buffers_to_write = bgwriter_lru_maxpages;
        int buffers_written = 0;

        /* Scan candidate buffers using the clock-sweep strategy */
        for (int i = 0; i < buffers_to_write; i++) {
            BufferDesc *buf = GetClockSweepCandidate();

            if (buf != NULL && (buf->flags & BM_DIRTY)) {
                FlushBuffer(buf);
                buffers_written++;
            }
        }

        BgWriterStats.buffers_written += buffers_written;
    }
}
```

**3. WAL Writer**

Flushes WAL buffers to disk:

```c
/* walwriter.c */

void WalWriterMain(void) {
    for (;;) {
        /* Sleep for wal_writer_delay (default 200ms) */
        pg_usleep(wal_writer_delay * 1000L);

        /* Flush WAL buffers */
        XLogFlush(GetInsertRecPtr());

        /* Update statistics */
        WalWriterStats.wal_write_time++;
    }
}
```

**4. Autovacuum Launcher & Workers**

Spawns autovacuum workers to clean dead tuples:

```c
/* autovacuum.c */

void AutoVacLauncherMain(void) {
    for (;;) {
        /* Sleep for autovacuum_naptime (default 1 minute) */
        WaitForAutovacuumWakeup();

        /* Get list of databases needing vacuum */
        List *databases = GetDatabasesNeedingVacuum();

        foreach (db, databases) {
            /* Limit concurrent workers */
            if (num_workers < autovacuum_max_workers) {
                /* Fork autovacuum worker */
                StartAutovacuumWorker(db->oid);
                num_workers++;
            }
        }
    }
}

void AutovacuumWorkerMain(Oid dboid) {
    /* Connect to database */
    InitPostgres(dboid);

    /* Get tables needing vacuum/analyze */
    List *tables = GetTablesNeedingMaintenance(dboid);

    foreach (table, tables) {
        if (TableNeedsVacuum(table)) {
            /* Run VACUUM */
            vacuum_rel(table->relid, NULL, VACOPT_VERBOSE);
        }

        if (TableNeedsAnalyze(table)) {
            /* Update statistics */
            analyze_rel(table->relid, NULL, VACOPT_VERBOSE);
        }
    }

    /* Exit worker */
    proc_exit(0);
}
```

**Autovacuum Triggers (per table):**
```
Vacuum threshold = autovacuum_vacuum_threshold +
                   (autovacuum_vacuum_scale_factor * table_rows)

Default: 50 + (0.2 * table_rows)
Example: 1M row table → vacuum at 200,050 dead tuples
```

---

## Query Processing Pipeline

PostgreSQL's query processing consists of four major phases:

```
SQL Text Input
     |
     v
[1. PARSER]
     | (Parse Tree)
     v
[2. REWRITER]
     | (Rewritten Query Tree)
     v
[3. PLANNER]
     | (Execution Plan)
     v
[4. EXECUTOR]
     | (Result Tuples)
     v
Output to Client
```

### Phase Responsibilities

**1. Parser Phase:**
- Lexical analysis (tokenization)
- Syntax analysis (grammar validation)
- Build abstract syntax tree (Parse Tree)
- *No* name resolution or type checking (unlike SQL Server)

**2. Rewriter Phase:**
- Apply query rewrite rules (CREATE RULE)
- Expand views into base table references
- Apply RLS (Row-Level Security) policies
- Permission checking
- *Unique to PostgreSQL* (SQL Server has no equivalent)

**3. Planner Phase:**
- Cost-based query optimization
- Join order selection
- Index selection
- Statistics-based cardinality estimation
- Produces physical execution plan (Plan Tree)

**4. Executor Phase:**
- Execute plan using iterator model (similar to SQL Server)
- Read data pages via buffer manager
- Apply MVCC visibility rules
- Return result tuples

---

## Parser Stage: Lexical and Syntax Analysis

The parser converts SQL text into a **Parse Tree** using flex (lexer) and bison (parser generator).

### Lexical Analysis (Tokenization)

**Tokenizer (scan.l - flex specification):**

```c
/* gram.y input tokens */

Input: SELECT customer_name, order_total FROM orders WHERE order_total > 1000

Tokens:
1. KEYWORD: SELECT
2. IDENTIFIER: customer_name
3. COMMA: ,
4. IDENTIFIER: order_total
5. KEYWORD: FROM
6. IDENTIFIER: orders
7. KEYWORD: WHERE
8. IDENTIFIER: order_total
9. OPERATOR: >
10. INTEGER: 1000
```

**Simplified Lexer Pseudocode:**

```c
/* scanner.l (flex) */

%%
SELECT          { return SELECT; }
FROM            { return FROM_P; }
WHERE           { return WHERE; }
AND             { return AND; }
OR              { return OR; }

[0-9]+          { yylval.ival = atoi(yytext); return ICONST; }
[a-zA-Z_][a-zA-Z0-9_]*  { yylval.str = pstrdup(yytext); return IDENT; }

"="             { return '='; }
">"             { return '>'; }
"<"             { return '<'; }
","             { return ','; }
"("             { return '('; }
")"             { return ')'; }
";"             { return ';'; }

[ \t\n]+        { /* skip whitespace */ }
%%
```

### Syntax Analysis (Parsing)

PostgreSQL uses **bison** (yacc) to generate an LALR parser from grammar rules:

**Grammar Rules (gram.y):**

```yacc
/* gram.y (simplified) */

SelectStmt:
    SELECT opt_all_clause select_list
    FROM from_list
    opt_where_clause
    opt_group_clause
    opt_having_clause
    opt_order_clause
    {
        SelectStmt *n = makeNode(SelectStmt);
        n->targetList = $3;      /* select_list */
        n->fromClause = $5;      /* from_list */
        n->whereClause = $6;     /* opt_where_clause */
        n->groupClause = $7;     /* opt_group_clause */
        n->havingClause = $8;    /* opt_having_clause */
        n->sortClause = $9;      /* opt_order_clause */
        $$ = (Node *) n;
    }
;

select_list:
    select_item                     { $$ = list_make1($1); }
    | select_list ',' select_item   { $$ = lappend($1, $3); }
;

select_item:
    a_expr AS ColLabel              { /* column with alias */ }
    | a_expr                        { /* column without alias */ }
;

from_list:
    table_ref                       { $$ = list_make1($1); }
    | from_list ',' table_ref       { $$ = lappend($1, $3); }
;

opt_where_clause:
    WHERE a_expr                    { $$ = $2; }
    | /* EMPTY */                   { $$ = NULL; }
;
```

### Parse Tree Structure

**Parse Tree for: `SELECT name, total FROM orders WHERE total > 1000`**

```
SelectStmt
├── targetList (TargetEntry list)
│   ├── TargetEntry: name
│   │   └── ColumnRef: "name"
│   └── TargetEntry: total
│       └── ColumnRef: "total"
├── fromClause (RangeVar list)
│   └── RangeVar: "orders"
└── whereClause (A_Expr)
    ├── kind: AEXPR_OP (>)
    ├── lexpr: ColumnRef "total"
    └── rexpr: A_Const 1000
```

**Parser Entry Point:**

```c
/* parser.c */

List *raw_parser(const char *query_string) {
    /* Initialize scanner */
    yyscan_t scanner;
    core_yyscan_t *yyextra;

    scanner = scanner_init(query_string, &yyextra);

    /* Parse query - calls bison-generated yyparse() */
    int yyresult = base_yyparse(scanner);

    if (yyresult != 0) {
        /* Syntax error */
        ereport(ERROR,
                (errcode(ERRCODE_SYNTAX_ERROR),
                 errmsg("syntax error at or near \"%s\"",
                        scanner_errposition_arg)));
    }

    /* Return list of parse trees (can be multiple statements) */
    return yyextra->parsetree;
}
```

---

## Rewriter Stage: Rule System and View Expansion

The rewriter transforms the parse tree by:
1. **Expanding views** into base table references
2. **Applying query rewrite rules** (CREATE RULE)
3. **Adding RLS policies** (Row-Level Security)
4. **Resolving names** to actual table/column OIDs

**SQL Server Comparison:** SQL Server has no equivalent rewriter phase. View expansion happens during binding.

### View Expansion

**Example: View Definition**

```sql
CREATE VIEW customer_orders AS
SELECT c.name, c.email, o.order_id, o.total
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id;
```

**Query Using View:**

```sql
SELECT name, total
FROM customer_orders
WHERE total > 1000;
```

**Rewritten Query (after view expansion):**

```sql
SELECT c.name, o.total
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
WHERE o.total > 1000;
```

**Rewriter Pseudocode:**

```c
/* rewriteHandler.c */

Query *QueryRewrite(Query *parsetree) {
    ListCell *l;

    /* Resolve table names to OIDs */
    foreach (l, parsetree->rtable) {
        RangeTblEntry *rte = (RangeTblEntry *) lfirst(l);

        if (rte->rtekind == RTE_RELATION) {
            /* Look up relation in catalog */
            Oid relid = RangeVarGetRelid(rte->relname, NoLock, false);
            rte->relid = relid;

            /* Check if this is a view */
            Relation rel = heap_open(relid, NoLock);

            if (rel->rd_rel->relkind == RELKIND_VIEW) {
                /* Expand view into subquery */
                Query *viewquery = get_view_query(rel);
                rte = ExpandView(rte, viewquery);
            }

            heap_close(rel, NoLock);
        }
    }

    /* Apply rewrite rules */
    parsetree = ApplyRewriteRules(parsetree);

    /* Apply RLS policies */
    parsetree = ApplyRowLevelSecurity(parsetree);

    return parsetree;
}
```

### Query Rewrite Rules

PostgreSQL's rule system allows defining query transformations:

```sql
-- Example: Audit trigger via rule
CREATE RULE customer_audit AS
ON INSERT TO customers
DO ALSO
INSERT INTO customers_audit (customer_id, action, timestamp)
VALUES (NEW.customer_id, 'INSERT', NOW());
```

When an INSERT happens, the rewriter automatically adds the audit INSERT.

---

## Planner Stage: Cost-Based Optimization

The planner generates an optimal execution plan using:
1. **Statistics** from pg_statistic (via ANALYZE)
2. **Cost model** (cpu_tuple_cost, random_page_cost, etc.)
3. **Join enumeration** (dynamic programming for ≤ 12 tables, genetic for > 12)
4. **Index selection**
5. **Physical operator choice**

### Cost Model Parameters

| Parameter | Default | SQL Server Equivalent | Purpose |
|-----------|---------|----------------------|---------|
| **seq_page_cost** | 1.0 | N/A (base cost unit) | Cost to read sequential page |
| **random_page_cost** | 4.0 | N/A | Cost to read random page (4x sequential) |
| **cpu_tuple_cost** | 0.01 | N/A | Cost to process one tuple |
| **cpu_index_tuple_cost** | 0.005 | N/A | Cost to scan one index entry |
| **cpu_operator_cost** | 0.0025 | N/A | Cost to execute operator |
| **parallel_tuple_cost** | 0.1 | N/A | Overhead per tuple in parallel query |

**SSD Tuning:** calibrate `random_page_cost` from measured storage and cache behavior; do not assume one SSD value

### Cardinality Estimation

PostgreSQL uses histograms (MCV + histogram buckets) similar to SQL Server:

**Statistics Structure (pg_statistic):**

```
pg_statistic columns:
├── stakind1-5: Statistic kind (1=MCV, 2=Histogram, 3=Correlation, etc.)
├── stanumbers1-5: Frequency arrays
├── stavalues1-5: Value arrays
└── stadistinct: Number of distinct values

Histogram Example:
Table: orders, Column: order_total
Distinct values: 15,000
Histogram buckets: 100 (default_statistics_target)

Bucket boundaries: [10.50, 25.75, 45.00, ..., 9999.99]
```

**Selectivity Estimation:**

```c
/* clausesel.c */

Selectivity clause_selectivity(PlannerInfo *root, Node *clause) {
    if (IsA(clause, OpExpr)) {
        OpExpr *opexpr = (OpExpr *) clause;

        /* Extract operator and operands */
        Oid opno = opexpr->opno;
        Node *left = linitial(opexpr->args);
        Node *right = lsecond(opexpr->args);

        /* Get operator selectivity function */
        RegProcedure oprrest = get_oprrest(opno);

        if (oprrest) {
            /* Call operator-specific selectivity function */
            /* For "=": eqsel(), for ">": scalargtsel(), etc. */
            return DatumGetFloat8(
                OidFunctionCall4(oprrest,
                                PointerGetDatum(root),
                                ObjectIdGetDatum(opno),
                                PointerGetDatum(left),
                                PointerGetDatum(right))
            );
        }
    }

    /* Default selectivity */
    return DEFAULT_SELECTIVITY;  /* 0.005 (0.5%) */
}

/* Equality selectivity: col = constant */
Selectivity eqsel(PlannerInfo *root, Oid operator, List *args) {
    Var *var = extract_var(args);
    Const *constval = extract_const(args);

    /* Get statistics for column */
    VariableStatData stats;
    examine_variable(root, var, 0, &stats);

    /* Check if value is in MCV (Most Common Values) list */
    float4 *mcv_freqs = stats.stanumbers[MCV_SLOT];
    Datum *mcv_values = stats.stavalues[MCV_SLOT];

    for (int i = 0; i < stats.numnumbers[MCV_SLOT]; i++) {
        if (datumIsEqual(constval->constvalue, mcv_values[i])) {
            return mcv_freqs[i];  /* Return MCV frequency */
        }
    }

    /* Not in MCV - assume uniform distribution */
    if (stats.stadistinct > 0) {
        return 1.0 / stats.stadistinct;
    }

    return DEFAULT_EQ_SEL;  /* 0.005 */
}

/* Range selectivity: col > constant */
Selectivity scalargtsel(PlannerInfo *root, Oid operator, List *args) {
    Var *var = extract_var(args);
    Const *constval = extract_const(args);

    /* Get histogram */
    VariableStatData stats;
    examine_variable(root, var, 0, &stats);

    Datum *histogram = stats.stavalues[HISTOGRAM_SLOT];
    int nhist = stats.numvalues[HISTOGRAM_SLOT];

    /* Binary search to find bucket */
    int bucket = binary_search_histogram(histogram, nhist, constval->constvalue);

    /* Calculate selectivity based on bucket position */
    float8 selectivity = (float8)(nhist - bucket) / (float8)nhist;

    return selectivity;
}
```

### Join Order Optimization

PostgreSQL uses **dynamic programming** for small join counts, **genetic algorithm** for large joins:

**Dynamic Programming (≤ from_collapse_limit tables, default 8):**

```c
/* allpaths.c */

RelOptInfo *make_one_rel(PlannerInfo *root, List *joinlist) {
    int num_rels = list_length(root->simple_rel_array);

    if (num_rels <= from_collapse_limit) {
        /* Use dynamic programming */
        return standard_join_search(root, num_rels, joinlist);
    } else {
        /* Use genetic algorithm */
        return geqo(root, num_rels, joinlist);
    }
}

RelOptInfo *standard_join_search(PlannerInfo *root, int levels_needed, List *initial_rels) {
    /* DP table: best path for each subset of relations */
    Relids all_baserels = root->all_baserels;

    /* Level 1: Single-table access paths */
    for (int level = 1; level <= levels_needed; level++) {
        List *joinrels = NIL;

        if (level == 1) {
            /* Base relations - choose best scan method */
            foreach (rel, initial_rels) {
                set_base_rel_pathlist(root, rel);
            }
        } else {
            /* Join level N: combine all (N-1, 1) and (N-2, 2) pairs */
            joinrels = make_rels_by_clause_joins(root, level, joinrels);
            joinrels = make_rels_by_clauseless_joins(root, level, joinrels);
        }
    }

    /* Return best path for all relations */
    return find_final_rel(root, all_baserels);
}
```

**Genetic Algorithm (GEQO, > from_collapse_limit tables):**

```c
/* geqo_main.c */

RelOptInfo *geqo(PlannerInfo *root, int number_of_rels, List *initial_rels) {
    GeqoPrivateData private;
    int pool_size = geqo_pool_size;
    int generations = geqo_generations;

    /* Initialize population with random join orders */
    Gene **population = gimme_pool(pool_size, number_of_rels);

    for (int gen = 0; gen < generations; gen++) {
        /* Evaluate fitness (cost) of each chromosome */
        for (int i = 0; i < pool_size; i++) {
            population[i]->fitness = geqo_eval(root, population[i]);
        }

        /* Selection: keep best chromosomes */
        sort_population(population, pool_size);

        /* Crossover: combine chromosomes */
        for (int i = 0; i < pool_size / 2; i++) {
            Gene *offspring = geqo_crossover(population[i], population[i+1]);
            population[pool_size - i - 1] = offspring;
        }

        /* Mutation: randomly alter some chromosomes */
        for (int i = 0; i < pool_size; i++) {
            if (random() < geqo_mutation_rate) {
                geqo_mutation(population[i]);
            }
        }
    }

    /* Return best join order found */
    Gene *best = population[0];
    return gimme_tree(root, best);
}
```

### Plan Tree Structure

**Plan Tree for: `SELECT name, total FROM orders WHERE total > 1000`**

```
SeqScan (orders)
├── Filter: (total > 1000)
├── Output: name, total
├── Rows: 5000 (estimated)
└── Cost: 0.00..180.00

Alternative with Index:

IndexScan (orders_total_idx)
├── Index Cond: (total > 1000)
├── Output: name, total
├── Rows: 5000 (estimated)
└── Cost: 0.42..250.00

Chosen: SeqScan (lower cost)
```

**Planner Entry Point:**

```c
/* planner.c */

PlannedStmt *planner(Query *parse, int cursorOptions, ParamListInfo boundParams) {
    PlannerInfo *root;
    Plan *top_plan;

    /* Initialize planner context */
    root = subquery_planner(glob, parse, NULL, false, tuple_fraction);

    /* Get cheapest path for query */
    RelOptInfo *final_rel = query_planner(root, standard_qp_callback, &qp_extra);

    /* Convert path to plan */
    top_plan = create_plan(root, final_rel->cheapest_total_path);

    /* Create PlannedStmt */
    PlannedStmt *result = makeNode(PlannedStmt);
    result->commandType = parse->commandType;
    result->planTree = top_plan;
    result->rtable = glob->finalrtable;

    return result;
}
```

---

*[Due to length constraints, the remaining sections (Executor, Storage, MVCC, etc.) would continue in the same detailed style with pseudocode, diagrams, and SQL Server comparisons. Would you like me to continue with specific sections?]*

---

## Quick Reference: PostgreSQL vs SQL Server Architecture

| Component | SQL Server | PostgreSQL |
|-----------|-----------|------------|
| **Process Model** | Single process, multi-threaded | Multi-process (dedicated backend per connection; creation is platform-specific) |
| **Connection Pooling** | SQLOS thread pooling (built-in) | External (PgBouncer required) |
| **Buffer Pool** | Buffer Pool (aggressive, 80%+ RAM) | shared_buffers sized by measurement + OS cache |
| **Transaction Log** | .ldf file with auto-growth | WAL 16MB segments (recycled) |
| **Concurrency** | Pessimistic locking + optional snapshot | Optimistic MVCC (always multi-version) |
| **Dead Row Cleanup** | Automatic (ghost cleanup) | Manual VACUUM (autovacuum) |
| **Statistics** | Auto-update (async) | ANALYZE (manual or autovacuum) |
| **Query Optimizer** | Cost-based, proprietary | Cost-based, open source (GEQO) |
| **Execution Model** | Iterator (Volcano) model | Iterator model (similar) |
| **Parallel Query** | Parallelism with exchange operators | Parallel workers (similar concept) |
| **Plan Caching** | Procedure cache (automatic) | Prepared statements (manual) |
| **Authentication** | Windows/SQL Auth | pg_hba.conf (host-based) |

---

**Document Version**: 1.0
**PostgreSQL Version**: 15/16
**Last Updated**: 2026

*This document uses representative pseudocode and simplified algorithms for educational purposes.*
