import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from shopping_bot.version import release, configure_logging
from shopping_bot.support import Support
from shopping_bot.analytics import Analytics
from shopping_bot.families import Families
from shopping_bot.store import Store


class ReleaseTests(unittest.TestCase):
    def test_build_identity_and_local_fallback(self):
        with patch.object(Path, 'read_text', return_value=json.dumps({'version':'0.2.0','commit':'a'*40})):
            self.assertEqual(release(), {'version':'0.2.0','commit':'a'*40})
        with patch.object(Path, 'read_text', side_effect=FileNotFoundError):
            self.assertTrue(release()['version'].endswith('-dev'))
            self.assertEqual(release()['commit'], 'unknown')

    def test_logging_records_have_release_identity(self):
        factory = logging.getLogRecordFactory()
        try:
            with patch('shopping_bot.version.release', return_value={'version':'0.2.0','commit':'a'*40}), patch('logging.basicConfig') as config:
                configure_logging()
                record = logging.getLogger('test').makeRecord('test', 20, '', 1, 'test', (), None)
                self.assertEqual(record.release_version, '0.2.0')
                self.assertEqual(record.release_commit, 'a'*40)
                self.assertIn('release_version', config.call_args.kwargs['format'])
        finally:
            logging.setLogRecordFactory(factory)

    def test_support_captures_submission_version_and_keeps_it_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            families = Families(Store(Path(tmp)/'shopping.sqlite3'), Path(tmp)/'photos')
            support = Support(families)
            support.begin(1)
            draft = support.describe(1, 'The shared list did not update')
            with patch('shopping_bot.support.release', return_value={'version':'0.2.0','commit':'a'*40}):
                ticket = support.submit({'id':1}, draft['token'], {})
            with patch('shopping_bot.support.release', return_value={'version':'0.2.1','commit':'b'*40}):
                self.assertEqual(support.submit({'id':1}, draft['token'], {}), ticket)
            self.assertEqual(support.tickets()['items'][0]['metadata']['release']['version'], '0.2.0')

    def test_existing_analytics_rows_remain_unknown_after_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            families = Families(Store(Path(tmp)/'shopping.sqlite3'), Path(tmp)/'photos')
            with families.db() as db:
                db.execute('CREATE TABLE analytics_events(id INTEGER PRIMARY KEY,user_id INTEGER,kind TEXT NOT NULL,occurred REAL NOT NULL,status TEXT NOT NULL,value INTEGER NOT NULL,duration_ms INTEGER)')
                db.execute("INSERT INTO analytics_events VALUES (1,1,'bot_start',0,'ok',1,NULL)")
            analytics = Analytics(families)
            with analytics.db() as db:
                row = db.execute('SELECT * FROM analytics_events WHERE id=1').fetchone()
                self.assertEqual(row['version'], 'unknown')
                self.assertEqual(row['commit_sha'], 'unknown')
