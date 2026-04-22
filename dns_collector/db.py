"""Database connection and schema management for DnsCollector."""

from pathlib import Path

import duckdb

DEFAULT_DB_PATH = Path("data/dns_collector.db")

_SCHEMA: tuple[str, ...] = (
    "CREATE SEQUENCE IF NOT EXISTS runs_id_seq START 1",
    """
    CREATE TABLE IF NOT EXISTS runs (
        id          INTEGER DEFAULT nextval('runs_id_seq') PRIMARY KEY,
        started_at  TIMESTAMPTZ DEFAULT now(),
        finished_at TIMESTAMPTZ
    )
    """,
    "CREATE SEQUENCE IF NOT EXISTS domains_id_seq START 1",
    """
    CREATE TABLE IF NOT EXISTS domains (
        id          INTEGER DEFAULT nextval('domains_id_seq') PRIMARY KEY,
        name        VARCHAR NOT NULL UNIQUE,
        created_at  TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE SEQUENCE IF NOT EXISTS dns_records_id_seq START 1",
    """
    CREATE TABLE IF NOT EXISTS dns_records (
        id          INTEGER DEFAULT nextval('dns_records_id_seq') PRIMARY KEY,
        run_id      INTEGER NOT NULL REFERENCES runs(id),
        domain_id   INTEGER NOT NULL REFERENCES domains(id),
        record_type VARCHAR NOT NULL,
        value       VARCHAR NOT NULL,
        ttl         INTEGER,
        collected_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """CREATE INDEX IF NOT EXISTS idx_dns_records_lookup
    ON dns_records (domain_id, record_type, collected_at)
    """,
    # Supports query 1: GROUP BY record_type across all rows
    """CREATE INDEX IF NOT EXISTS idx_dns_records_record_type
    ON dns_records (record_type)
    """,
    "CREATE SEQUENCE IF NOT EXISTS resolution_log_id_seq START 1",
    """
    CREATE TABLE IF NOT EXISTS resolution_log (
        id          INTEGER DEFAULT nextval('resolution_log_id_seq') PRIMARY KEY,
        run_id      INTEGER NOT NULL REFERENCES runs(id),
        domain_id   INTEGER NOT NULL REFERENCES domains(id),
        record_type VARCHAR NOT NULL,
        status      VARCHAR NOT NULL,
        resolved_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    # Supports query 6: join on domain_id, group by status
    """CREATE INDEX IF NOT EXISTS idx_resolution_log_lookup
    ON resolution_log (domain_id, status)
    """,
)


def _apply_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create tables and sequences if they do not already exist."""
    for statement in _SCHEMA:
        conn.execute(statement)


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open a persistent DuckDB connection and ensure the schema exists.

    Args:
        db_path: Path to the DuckDB database file.

    Returns:
        An open DuckDB connection with the schema applied.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    _apply_schema(conn)
    return conn
