"""SQLite-backed persistence for experiment records and their audit history."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from pydantic import BaseModel

from ci_agent.models import (
    EvidenceReference,
    Experiment,
    ExperimentEvent,
    ExperimentStatus,
    Proposal,
    SharedGoal,
    SuccessContract,
    VerdictRecord,
)

T = TypeVar("T", bound=BaseModel)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contracts (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES goals(id),
    version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(goal_id, version)
);
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES goals(id),
    contract_id TEXT NOT NULL REFERENCES contracts(id),
    workflow_id TEXT NOT NULL,
    comparison_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL UNIQUE REFERENCES experiments(id),
    patch_fingerprint TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verdicts (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    evidence_fingerprint TEXT NOT NULL,
    method_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(experiment_id, evidence_fingerprint, method_version)
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    event_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    kind TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    uri TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(experiment_id, kind, fingerprint, uri)
);
CREATE INDEX IF NOT EXISTS idx_experiments_workflow_status ON experiments(workflow_id, status);
CREATE INDEX IF NOT EXISTS idx_events_experiment_time ON events(experiment_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_verdicts_experiment_time ON verdicts(experiment_id, created_at);
"""


class SQLiteExperimentStore:
    """Persist immutable Pydantic records in a local SQLite database.

    Pass ``:memory:`` for an ephemeral store. File-backed stores create their
    parent directory and enable foreign keys for each connection.
    """

    def __init__(self, database: str | Path) -> None:
        requested_database = str(database)
        self._use_uri = requested_database == ":memory:"
        self.database = (
            f"file:ci-agent-{uuid4()}?mode=memory&cache=shared"
            if self._use_uri
            else requested_database
        )
        self._memory_anchor: sqlite3.Connection | None = None
        if self.database != ":memory:":
            if not self._use_uri:
                Path(self.database).parent.mkdir(parents=True, exist_ok=True)
            else:
                self._memory_anchor = self._connect()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10, uri=self._use_uri)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            if connection is not self._memory_anchor:
                connection.close()

    def _initialize(self) -> None:
        with self._session() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (1)"
            )

    @staticmethod
    def _json(value: BaseModel) -> str:
        return value.model_dump_json()

    @staticmethod
    def _get(connection: sqlite3.Connection, table: str, record_id: str, model: type[T]) -> T | None:
        row = connection.execute(
            f"SELECT payload FROM {table} WHERE id = ?", (record_id,)
        ).fetchone()
        return model.model_validate_json(row["payload"]) if row else None

    def save_goal(self, goal: SharedGoal) -> None:
        with self._session() as connection:
            connection.execute(
                """INSERT INTO goals(id, workflow_id, payload) VALUES (?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET workflow_id=excluded.workflow_id,
                   payload=excluded.payload""",
                (goal.id, goal.workflow_id, self._json(goal)),
            )

    def get_goal(self, goal_id: str) -> SharedGoal | None:
        with self._session() as connection:
            return self._get(connection, "goals", goal_id, SharedGoal)

    def save_contract(self, contract: SuccessContract) -> None:
        with self._session() as connection:
            connection.execute(
                "INSERT INTO contracts(id, goal_id, version, payload) VALUES (?, ?, ?, ?)",
                (contract.id, contract.goal_id, contract.version, self._json(contract)),
            )

    def get_contract(self, contract_id: str) -> SuccessContract | None:
        with self._session() as connection:
            return self._get(connection, "contracts", contract_id, SuccessContract)

    def save_experiment(self, experiment: Experiment) -> None:
        with self._session() as connection:
            connection.execute(
                """INSERT INTO experiments
                   (id, goal_id, contract_id, workflow_id, comparison_key, status, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status, payload=excluded.payload""",
                (
                    experiment.id,
                    experiment.goal_id,
                    experiment.contract_id,
                    experiment.workflow_id,
                    experiment.comparison_key,
                    experiment.status.value,
                    self._json(experiment),
                ),
            )

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        with self._session() as connection:
            return self._get(connection, "experiments", experiment_id, Experiment)

    def get_experiment_by_comparison_key(self, comparison_key: str) -> Experiment | None:
        with self._session() as connection:
            row = connection.execute(
                "SELECT payload FROM experiments WHERE comparison_key = ?", (comparison_key,)
            ).fetchone()
            return Experiment.model_validate_json(row["payload"]) if row else None

    def list_experiments(
        self,
        workflow_id: str | None = None,
        *,
        statuses: tuple[ExperimentStatus, ...] | None = None,
    ) -> tuple[Experiment, ...]:
        """List saved history, optionally narrowed by workflow and status."""
        with self._session() as connection:
            if statuses:
                marks = ", ".join("?" for _ in statuses)
                filters = [f"status IN ({marks})"]
                values: list[str] = [status.value for status in statuses]
                if workflow_id is not None:
                    filters.append("workflow_id = ?")
                    values.append(workflow_id)
                rows = connection.execute(
                    "SELECT payload FROM experiments WHERE " + " AND ".join(filters) + " ORDER BY rowid",
                    values,
                ).fetchall()
            elif workflow_id is None:
                rows = connection.execute("SELECT payload FROM experiments ORDER BY rowid").fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload FROM experiments WHERE workflow_id = ? ORDER BY rowid",
                    (workflow_id,),
                ).fetchall()
        return tuple(Experiment.model_validate_json(row["payload"]) for row in rows)

    def save_proposal(self, proposal: Proposal) -> None:
        with self._session() as connection:
            connection.execute(
                """INSERT INTO proposals(id, experiment_id, patch_fingerprint, payload)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(experiment_id) DO UPDATE SET id=excluded.id,
                   patch_fingerprint=excluded.patch_fingerprint, payload=excluded.payload""",
                (proposal.id, proposal.experiment_id, proposal.patch_fingerprint, self._json(proposal)),
            )

    def get_proposal(self, experiment_id: str) -> Proposal | None:
        with self._session() as connection:
            row = connection.execute(
                "SELECT payload FROM proposals WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            return Proposal.model_validate_json(row["payload"]) if row else None

    def save_verdict(self, verdict: VerdictRecord) -> bool:
        """Append a verdict once per evidence fingerprint and method; return if inserted."""
        with self._session() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO verdicts
                   (id, experiment_id, evidence_fingerprint, method_version, created_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    verdict.id,
                    verdict.experiment_id,
                    verdict.evidence_fingerprint,
                    verdict.method_version,
                    verdict.created_at.isoformat(),
                    self._json(verdict),
                ),
            )
            return cursor.rowcount == 1

    def list_verdicts(self, experiment_id: str) -> tuple[VerdictRecord, ...]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT payload FROM verdicts WHERE experiment_id = ? ORDER BY created_at, rowid",
                (experiment_id,),
            ).fetchall()
        return tuple(VerdictRecord.model_validate_json(row["payload"]) for row in rows)

    def save_event(
        self,
        event_key: str,
        experiment_id: str,
        state: str,
        reason: str,
        *,
        details: dict[str, object] | None = None,
    ) -> bool:
        """Append an event once by key. Return ``False`` for a duplicate key."""
        event = ExperimentEvent(
            experiment_id=experiment_id,
            event_key=event_key,
            state=ExperimentStatus(state),
            reason=reason,
            details=details or {},
        )
        with self._session() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO events(id, experiment_id, event_key, state, occurred_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event.id,
                    event.experiment_id,
                    event.event_key,
                    event.state.value,
                    event.occurred_at.isoformat(),
                    self._json(event),
                ),
            )
            return cursor.rowcount == 1

    def list_events(self, experiment_id: str) -> tuple[ExperimentEvent, ...]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT payload FROM events WHERE experiment_id = ? ORDER BY occurred_at, rowid",
                (experiment_id,),
            ).fetchall()
        return tuple(ExperimentEvent.model_validate_json(row["payload"]) for row in rows)

    def save_evidence(self, evidence: EvidenceReference) -> bool:
        """Append evidence once per experiment, kind, fingerprint, and URI."""
        with self._session() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO evidence
                   (id, experiment_id, kind, fingerprint, uri, payload) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    evidence.id,
                    evidence.experiment_id,
                    evidence.kind.value,
                    evidence.fingerprint,
                    evidence.uri,
                    self._json(evidence),
                ),
            )
            return cursor.rowcount == 1

    def list_evidence(self, experiment_id: str) -> tuple[EvidenceReference, ...]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT payload FROM evidence WHERE experiment_id = ? ORDER BY rowid",
                (experiment_id,),
            ).fetchall()
        return tuple(EvidenceReference.model_validate_json(row["payload"]) for row in rows)

