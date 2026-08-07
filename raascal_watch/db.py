from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .models import MarketRecord, MatchResult, ScanSourceSummary
from .text import isoformat


SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'unknown',
    source_created_at TEXT,
    closes_at TEXT,
    probability REAL,
    volume REAL,
    volume_24h REAL,
    liquidity REAL,
    open_interest REAL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_markets_source_seen
    ON markets(source, first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_markets_close
    ON markets(closes_at);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
    organization TEXT NOT NULL,
    matched_identity_terms_json TEXT NOT NULL DEFAULT '[]',
    matched_metric_terms_json TEXT NOT NULL DEFAULT '[]',
    categories_json TEXT NOT NULL DEFAULT '[]',
    risk_score INTEGER NOT NULL,
    severity TEXT NOT NULL,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    stakeholders_json TEXT NOT NULL DEFAULT '[]',
    actions_json TEXT NOT NULL DEFAULT '[]',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    alert_state TEXT NOT NULL DEFAULT 'new',
    notified_at TEXT,
    acknowledged_at TEXT,
    UNIQUE(market_id, organization)
);

CREATE INDEX IF NOT EXISTS idx_matches_severity
    ON matches(severity, risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_matches_state
    ON matches(alert_state, first_seen_at DESC);

CREATE TABLE IF NOT EXISTS source_state (
    source TEXT PRIMARY KEY,
    initialized_at TEXT,
    last_success_at TEXT,
    last_error_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    fetched INTEGER NOT NULL DEFAULT 0,
    pages INTEGER NOT NULL DEFAULT 0,
    new_markets INTEGER NOT NULL DEFAULT 0,
    matches INTEGER NOT NULL DEFAULT 0,
    new_matches INTEGER NOT NULL DEFAULT 0,
    notifications INTEGER NOT NULL DEFAULT 0,
    baseline_suppressed INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_scan_runs_started
    ON scan_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def source_initialized(self, source: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT initialized_at FROM source_state WHERE source = ?", (source,)
            ).fetchone()
            return bool(row and row["initialized_at"])

    def mark_source_success(self, source: str, at: datetime, initialize: bool = True) -> None:
        timestamp = isoformat(at)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_state(source, initialized_at, last_success_at, last_error_at, last_error)
                VALUES (?, ?, ?, NULL, NULL)
                ON CONFLICT(source) DO UPDATE SET
                    initialized_at = CASE
                        WHEN source_state.initialized_at IS NULL AND excluded.initialized_at IS NOT NULL
                        THEN excluded.initialized_at
                        ELSE source_state.initialized_at
                    END,
                    last_success_at = excluded.last_success_at,
                    last_error_at = NULL,
                    last_error = NULL
                """,
                (source, timestamp if initialize else None, timestamp),
            )

    def mark_source_error(self, source: str, at: datetime, error: str) -> None:
        timestamp = isoformat(at)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_state(source, last_error_at, last_error)
                VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_error_at = excluded.last_error_at,
                    last_error = excluded.last_error
                """,
                (source, timestamp, error[:4000]),
            )

    def reset_source_state(self, source: str | None = None) -> int:
        with self.connect() as connection:
            if source:
                cursor = connection.execute(
                    "UPDATE source_state SET initialized_at = NULL WHERE source = ?", (source,)
                )
            else:
                cursor = connection.execute(
                    "UPDATE source_state SET initialized_at = NULL"
                )
            return cursor.rowcount

    def upsert_market(
        self, market: MarketRecord, seen_at: datetime
    ) -> tuple[int, bool]:
        seen = isoformat(seen_at)
        values = (
            market.title,
            market.description,
            market.url,
            market.status,
            isoformat(market.created_at),
            isoformat(market.closes_at),
            market.probability,
            market.volume,
            market.volume_24h,
            market.liquidity,
            market.open_interest,
            seen,
            _json(market.raw),
            market.source,
            market.external_id,
        )
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM markets WHERE source = ? AND external_id = ?",
                (market.source, market.external_id),
            ).fetchone()
            if row:
                market_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE markets SET
                        title = ?, description = ?, url = ?, status = ?,
                        source_created_at = ?, closes_at = ?, probability = ?,
                        volume = ?, volume_24h = ?, liquidity = ?, open_interest = ?,
                        last_seen_at = ?, raw_json = ?
                    WHERE source = ? AND external_id = ?
                    """,
                    values,
                )
                return market_id, False

            cursor = connection.execute(
                """
                INSERT INTO markets(
                    source, external_id, title, description, url, status,
                    source_created_at, closes_at, probability, volume, volume_24h,
                    liquidity, open_interest, first_seen_at, last_seen_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market.source,
                    market.external_id,
                    market.title,
                    market.description,
                    market.url,
                    market.status,
                    isoformat(market.created_at),
                    isoformat(market.closes_at),
                    market.probability,
                    market.volume,
                    market.volume_24h,
                    market.liquidity,
                    market.open_interest,
                    seen,
                    seen,
                    _json(market.raw),
                ),
            )
            return int(cursor.lastrowid), True

    def upsert_match(
        self,
        market_id: int,
        result: MatchResult,
        seen_at: datetime,
        initial_alert_state: str,
    ) -> tuple[int, bool]:
        seen = isoformat(seen_at)
        values = (
            _json(result.matched_identity_terms),
            _json(result.matched_metric_terms),
            _json(result.categories),
            result.risk_score,
            result.severity,
            _json(result.reasons),
            _json(result.stakeholders),
            _json(result.actions),
            seen,
            market_id,
            result.organization,
        )
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM matches WHERE market_id = ? AND organization = ?",
                (market_id, result.organization),
            ).fetchone()
            if row:
                match_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE matches SET
                        matched_identity_terms_json = ?,
                        matched_metric_terms_json = ?,
                        categories_json = ?,
                        risk_score = ?, severity = ?, reasons_json = ?,
                        stakeholders_json = ?, actions_json = ?, last_seen_at = ?
                    WHERE market_id = ? AND organization = ?
                    """,
                    values,
                )
                return match_id, False

            cursor = connection.execute(
                """
                INSERT INTO matches(
                    market_id, organization, matched_identity_terms_json,
                    matched_metric_terms_json, categories_json, risk_score,
                    severity, reasons_json, stakeholders_json, actions_json,
                    first_seen_at, last_seen_at, alert_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market_id,
                    result.organization,
                    _json(result.matched_identity_terms),
                    _json(result.matched_metric_terms),
                    _json(result.categories),
                    result.risk_score,
                    result.severity,
                    _json(result.reasons),
                    _json(result.stakeholders),
                    _json(result.actions),
                    seen,
                    seen,
                    initial_alert_state,
                ),
            )
            return int(cursor.lastrowid), True

    def set_match_alert_state(
        self,
        match_id: int,
        state: str,
        *,
        notified_at: datetime | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE matches
                SET alert_state = ?, notified_at = COALESCE(?, notified_at)
                WHERE id = ?
                """,
                (state, isoformat(notified_at), match_id),
            )

    def acknowledge_match(self, match_id: int, at: datetime) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE matches
                SET acknowledged_at = ?, alert_state = 'acknowledged'
                WHERE id = ?
                """,
                (isoformat(at), match_id),
            )
            return cursor.rowcount > 0

    def log_notification(
        self,
        match_id: int,
        channel: str,
        at: datetime,
        status: str,
        detail: str = "",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO notification_log(match_id, channel, sent_at, status, detail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (match_id, channel, isoformat(at), status, detail[:4000]),
            )

    def record_scan(
        self,
        summary: ScanSourceSummary,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO scan_runs(
                    source, started_at, finished_at, fetched, pages, new_markets,
                    matches, new_matches, notifications, baseline_suppressed, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.source,
                    isoformat(started_at),
                    isoformat(finished_at),
                    summary.fetched,
                    summary.pages,
                    summary.new_markets,
                    summary.matches,
                    summary.new_matches,
                    summary.notifications,
                    summary.baseline_suppressed,
                    summary.error,
                ),
            )

    def get_match(self, match_id: int) -> dict[str, Any] | None:
        rows = self._query_matches("WHERE mt.id = ?", (match_id,), limit=1)
        return rows[0] if rows else None

    def list_matches(
        self,
        *,
        organization: str | None = None,
        severity: str | None = None,
        source: str | None = None,
        alert_state: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if organization:
            clauses.append("mt.organization = ?")
            params.append(organization)
        if severity:
            clauses.append("mt.severity = ?")
            params.append(severity)
        if source:
            clauses.append("m.source = ?")
            params.append(source)
        if alert_state:
            clauses.append("mt.alert_state = ?")
            params.append(alert_state)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self._query_matches(where, tuple(params), limit=max(1, min(limit, 1000)))

    def _query_matches(
        self, where: str, params: tuple[Any, ...], limit: int
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    mt.id AS match_id, mt.organization,
                    mt.matched_identity_terms_json, mt.matched_metric_terms_json,
                    mt.categories_json, mt.risk_score, mt.severity,
                    mt.reasons_json, mt.stakeholders_json, mt.actions_json,
                    mt.first_seen_at AS match_first_seen_at,
                    mt.last_seen_at AS match_last_seen_at,
                    mt.alert_state, mt.notified_at, mt.acknowledged_at,
                    m.id AS market_id, m.source, m.external_id, m.title,
                    m.description, m.url, m.status, m.source_created_at,
                    m.closes_at, m.probability, m.volume, m.volume_24h,
                    m.liquidity, m.open_interest, m.first_seen_at,
                    m.last_seen_at
                FROM matches mt
                JOIN markets m ON m.id = mt.market_id
                {where}
                ORDER BY
                    CASE mt.severity
                        WHEN 'critical' THEN 4
                        WHEN 'high' THEN 3
                        WHEN 'medium' THEN 2
                        ELSE 1
                    END DESC,
                    mt.risk_score DESC,
                    mt.first_seen_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for field in (
                "matched_identity_terms_json",
                "matched_metric_terms_json",
                "categories_json",
                "reasons_json",
                "stakeholders_json",
                "actions_json",
            ):
                clean_name = field.removesuffix("_json")
                item[clean_name] = _loads(item.pop(field), [])
            output.append(item)
        return output

    def dashboard_stats(self) -> dict[str, Any]:
        with self.connect() as connection:
            market_count = connection.execute(
                "SELECT COUNT(*) AS count FROM markets"
            ).fetchone()["count"]
            match_count = connection.execute(
                "SELECT COUNT(*) AS count FROM matches"
            ).fetchone()["count"]
            unacknowledged = connection.execute(
                """
                SELECT COUNT(*) AS count FROM matches
                WHERE acknowledged_at IS NULL AND alert_state NOT IN ('baseline', 'historical')
                """
            ).fetchone()["count"]
            high_risk = connection.execute(
                "SELECT COUNT(*) AS count FROM matches WHERE severity IN ('high', 'critical')"
            ).fetchone()["count"]
            last_scan = connection.execute(
                "SELECT MAX(finished_at) AS finished_at FROM scan_runs"
            ).fetchone()["finished_at"]
            organizations = [
                row["organization"]
                for row in connection.execute(
                    "SELECT DISTINCT organization FROM matches ORDER BY organization"
                ).fetchall()
            ]
            sources = [
                row["source"]
                for row in connection.execute(
                    "SELECT DISTINCT source FROM markets ORDER BY source"
                ).fetchall()
            ]
            source_states = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM source_state ORDER BY source"
                ).fetchall()
            ]
        return {
            "markets": int(market_count),
            "matches": int(match_count),
            "unacknowledged": int(unacknowledged),
            "high_risk": int(high_risk),
            "last_scan": last_scan,
            "organizations": organizations,
            "sources": sources,
            "source_states": source_states,
        }

    def recent_scans(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT ?",
                    (max(1, min(limit, 100)),),
                ).fetchall()
            ]

    def clear_all(self) -> None:
        """Used by tests and explicit local resets."""
        with self.connect() as connection:
            connection.execute("DELETE FROM notification_log")
            connection.execute("DELETE FROM matches")
            connection.execute("DELETE FROM markets")
            connection.execute("DELETE FROM source_state")
            connection.execute("DELETE FROM scan_runs")
