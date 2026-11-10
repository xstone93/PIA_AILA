import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from session_store import SessionConflict, SessionStore


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "sessions.sqlite3"
        self.store = SessionStore(self.path)

    def test_restart_restores_state_and_activity_snapshot(self):
        activity = {"tasks": [{"task_title": "Original"}]}
        state = {"task_index": 1, "messages": [{"role": "user", "content": "Hello"}]}
        token = self.store.create(activity, {})
        revision = self.store.save(token, state, 0)
        activity["tasks"][0]["task_title"] = "Edited"
        restored_activity, restored_state, restored_revision = SessionStore(self.path).load(token)
        self.assertEqual(restored_activity["tasks"][0]["task_title"], "Original")
        self.assertEqual(restored_state, state)
        self.assertEqual(restored_revision, revision)

    def test_sessions_are_isolated_and_stale_writes_are_rejected(self):
        first = self.store.create({}, {"task_index": 0})
        second = self.store.create({}, {"task_index": 0})
        self.assertNotEqual(first, second)
        self.store.save(first, {"task_index": 1}, 0)
        with self.assertRaises(SessionConflict):
            self.store.save(first, {"task_index": 2}, 0)
        self.assertEqual(self.store.load(first)[1]["task_index"], 1)
        self.assertEqual(self.store.load(second)[1]["task_index"], 0)

    def test_invalid_and_missing_links_do_not_create_sessions(self):
        with self.assertRaises(ValueError):
            self.store.load("../secrets")
        with self.assertRaises(LookupError):
            self.store.load("a" * 43)


if __name__ == "__main__":
    unittest.main()
