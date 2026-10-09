import threading,unittest
from shopping_bot.speech_race import race,LOCAL_SLOT
class SpeechRaceTests(unittest.TestCase):
    def test_returns_before_loser_finishes_and_records_both(self):
        gate=threading.Event();finished=threading.Event();records=[]
        def local():gate.wait(2);return 'Milk'
        def record(row):
            records.append(row)
            if row['local_status']=='ok' and row['winner']:finished.set()
        try:
            result=race(local,lambda:'Milk',record)
            self.assertEqual(result,'Milk');self.assertFalse(gate.is_set())
            self.assertEqual(records[-1]['winner'],'groq')
        finally:gate.set()
        self.assertTrue(finished.wait(2));self.assertTrue(records[-1]['agreement'])
    def test_error_does_not_win(self):
        def broken():raise ValueError('no result')
        self.assertEqual(race(lambda:'Milk',broken),'Milk')
    def test_busy_local_skipped(self):
        self.assertTrue(LOCAL_SLOT.acquire(timeout=2))
        records=[]
        try:self.assertEqual(race(lambda:'Local',lambda:'Cloud',records.append),'Cloud')
        finally:LOCAL_SLOT.release()
        self.assertTrue(any(row['local_status']=='skipped_busy' for row in records))
    def test_persisted_metrics_and_message_id(self):
        import tempfile,time
        from pathlib import Path
        from shopping_bot.analytics import Analytics
        from shopping_bot.families import Families
        from shopping_bot.store import Store
        with tempfile.TemporaryDirectory() as folder:
            analytics=Analytics(Families(Store(Path(folder)/'shopping.sqlite3'),Path(folder)/'photos'))
            row=dict(request_id='test',occurred=time.time(),language='uk',audio_ms=11000,local_ms=12000,groq_ms=400,local_status='ok',groq_status='ok',winner='groq',delivered_ms=401,agreement=True,message_id=42)
            analytics.record_speech_benchmark(1,row)
            saved=analytics.speech_benchmarks()['items'][0]
            self.assertEqual(saved['message_id'],42)
            self.assertEqual(saved['groq_ms'],400)
            self.assertNotIn('text',saved)
