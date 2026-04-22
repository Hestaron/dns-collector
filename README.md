# DnsCollector

Lightweight DNS records ingestion pipeline that resolves A, AAAA, MX, TXT, NS, and CNAME records for a set of domains and stores them in a local DuckDB database for downstream analytics.

## Technical Architecture

```
config.toml
    │
    ▼
config.py ──► pipeline.py ──► resolver.py (dnspython)
                  │                │
                  │         ResolveResult (status, records)
                  │                │
                  └───────────────►▼
                            DuckDB (data/dns_collector.db)
                                   │
                                   ▼
                             queries.py (validation)
```
**Components:**

| Module | Responsibility |
|---|---|
| `config.py` | Loads `config.toml` — domain list and record types |
| `resolver.py` | Resolves a single (domain, record\_type) pair via dnspython; returns a `ResolveResult` with a status (`ok`, `noanswer`, `nxdomain`, `timeout`, `error`) and `(value, TTL)` tuples |
| `pipeline.py` | Iterates domains × record types, calls the resolver, upserts domains, bulk-inserts records, and logs every resolution attempt into DuckDB. Each execution is tracked as a **run** |
| `db.py` | Opens the DuckDB connection and applies the schema (tables + sequences) |
| `queries.py` | Five standalone validation queries — **fully decoupled from ingestion** so they can be run at any time against stored data |

The ingestion pipeline and the analytics queries are intentionally separate entry points. The pipeline writes data; the queries only read it. This means you can re-run validation queries multiple times against the same snapshot, or schedule them independently of ingestion.

## Setup Instructions

Requires Python ≥ 3.13 and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Hestaron/DnsCollector.git
cd DnsCollector
uv sync
```

## Running the ingestion pipeline

```bash
uv run python -m dns_collector
```

This reads `config.toml`, resolves all configured domains × record types, and writes records to `data/dns_collector.db`.

## Running the validation queries

```bash
uv run python -m dns_collector.queries
```

Runs six SQL queries against the stored data and logs the results:

1. **Record count by type** — verifies all six types were collected.
2. **Records per domain** — flags domains with zero records.
3. **Domains sharing nameservers** — clustering signal for ML models.
4. **IPv6 readiness** — which domains have AAAA records.
5. **Average TTL by domain** — low TTLs can indicate fast-flux DNS behaviour.
6. **Resolution success rate** — outcome of each resolution attempt per domain, surfacing failures.



## Data model

```
runs                            domains                         dns_records
────────────────────            ────────────────────            ──────────────────────────────────────
id          INTEGER PK          id          INTEGER PK          id           INTEGER PK
started_at  TIMESTAMPTZ         name        VARCHAR UNIQUE      run_id       INTEGER → runs.id
finished_at TIMESTAMPTZ         created_at  TIMESTAMPTZ         domain_id    INTEGER → domains.id
                                                                record_type  VARCHAR  (A/AAAA/MX/…)
                                                                value        VARCHAR  (raw text from rrset)
                                                                ttl          INTEGER  (seconds)
                                                                collected_at TIMESTAMPTZ

resolution_log
──────────────────────────────────────
id          INTEGER PK
run_id      INTEGER → runs.id
domain_id   INTEGER → domains.id
record_type VARCHAR  (A/AAAA/MX/…)
status      VARCHAR  (ok/noanswer/nxdomain/timeout/error)
resolved_at TIMESTAMPTZ
```

**Design choices and assumptions:**

- **Append-only.** Each pipeline run inserts new rows rather than upserting. This preserves history so that DNS changes (IP rotations, MX updates) are observable over time via `collected_at`. To get the current state, query the latest `collected_at` per `(domain_id, record_type, value)`.
- **Run tracking.** Every pipeline execution creates a `runs` row with `started_at` and `finished_at` timestamps. All `dns_records` and `resolution_log` rows are linked to a `run_id`, making it easy to query a specific snapshot or detect partial runs.
- **Resolution logging.** The `resolution_log` table records the outcome of every (domain, record_type) attempt — including failures. This means NXDOMAIN, timeouts, and "no answer" are distinguishable in the database rather than silently missing. Valuable for ML models that treat "domain stopped resolving" as a signal.
- **`value` is raw text.** MX priority (`10 aspmx.l.google.com.`) and CNAME targets are stored as the resolver returns them. This keeps the schema stable across all record types at the cost of extra parsing downstream.
- **No recursive resolution.** CNAME chains are not followed; only the CNAME record itself is stored.
- **Failures are non-fatal.** An NXDOMAIN or timeout for one (domain, type) pair is logged and skipped; the rest of the run continues.
- **Resolver choice.** dnspython is used based on this paper: Analyzing_and_Comparing_DNS_Lookup_Tools_in_Python. But the resolver is decoupled from the pipeline, so it could be swapped for another implementation if desired.
- **Explicit nameservers.** By default the resolver uses `1.1.1.1` and `8.8.8.8` (configurable in `config.toml`). This makes results reproducible across machines rather than depending on the OS resolver, which can vary between environments.
- **DuckDB for storage.** Chosen for its zero-configuration, single-file nature and good SQL support. In a production setting, this could be replaced with a more robust data store. Chosen for an analytics-focused workflow rather than high-throughput ingestion. Of course, the data model and queries would be portable to other SQL databases with minimal adjustments.
- **timeout=5s for all resolutions.** This is a balance between completeness and speed; it can be adjusted in `config.toml` if needed.

## Limitations & next steps

- **No parallel resolution.** DNS lookups are currently sequential (60 lookups at up to 5 s each). A `concurrent.futures.ThreadPoolExecutor` around the resolve calls in `pipeline.py` would reduce wall-clock time significantly and is a natural next step.
- **Bronze layer.** The `dns_records` table stores raw resolver output — MX values like `"10 aspmx.l.google.com."` are a single string, TXT records contain unescaped SPF/DKIM payloads, etc. A silver layer would be a good next step, if used for ML features, to parse and normalize these values into structured columns (e.g., `mx_priority`, `mx_host`, `txt_content`).
- **No incremental/delta ingestion.** Every run resolves all domains × all record types. For large domain lists, a change-detection layer (compare against previous run) would reduce unnecessary work.
- **Single-file DuckDB store.** Adequate for local analytics but not suitable for concurrent access or production workloads. In a real deployment this would be replaced with a proper data warehouse.
- **E2E tests.** Usefull for production readiness.
