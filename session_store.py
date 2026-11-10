"""Local persistence for activity sessions; no API credentials are stored."""
from contextlib import contextmanager
import json
import re
import secrets
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).parent / "data" / "sessions.sqlite3"


class SessionConflict(Exception):
    pass


class SessionStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    activity TEXT NOT NULL,
                    state TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
            for name in ("study_group", "participant_code", "study_version"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE sessions ADD COLUMN {name} TEXT")
            connection.execute("CREATE INDEX IF NOT EXISTS sessions_participant_code ON sessions(participant_code)")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, activity, state):
        session_id = secrets.token_urlsafe(32)
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO sessions (id, activity, state, study_group, participant_code, study_version) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, json.dumps(activity), json.dumps(state), state.get("group"),
                 state.get("participant_code"), state.get("study_version")),
            )
        return session_id

    def load(self, session_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", session_id):
            raise ValueError("Invalid session link")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT activity, state, revision FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise LookupError("Session not found")
        return json.loads(row[0]), json.loads(row[1]), row[2]

    def save(self, session_id, state, revision):
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT study_group, participant_code FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing and existing[0] is not None and existing != (state.get("group"), state.get("participant_code")):
                raise ValueError("Study enrollment cannot be changed")
            cursor = connection.execute(
                """UPDATE sessions SET state = ?, revision = revision + 1,
                   study_group = ?, participant_code = ?, study_version = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ? AND revision = ?""",
                (json.dumps(state), state.get("group"), state.get("participant_code"),
                 state.get("study_version"), session_id, revision),
            )
            if cursor.rowcount != 1:
                raise SessionConflict("Session changed in another tab")
        return revision + 1
