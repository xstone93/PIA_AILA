"""Temporary local browser smoke test; never uses participant data."""
from pathlib import Path
import runpy
from unittest.mock import patch
import session_store
import study_flow

fixture = runpy.run_path(str(Path(__file__).parent / 'tests' / 'test_study.py'))['ready_snapshot']()
with patch.object(session_store, 'DB_PATH', Path(__file__).parent / '.study-preview' / 'sessions.sqlite3'), patch.object(study_flow, 'load_study', return_value=fixture), patch('guardrail.guarded_reply', return_value='Danke für deine Überlegungen. Was ist dein nächster Schritt?'):
    runpy.run_path(str(Path(__file__).parent / 'app.py'), run_name='__main__')