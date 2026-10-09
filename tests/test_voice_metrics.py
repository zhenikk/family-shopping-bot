import unittest
from shopping_bot.voice_metrics import VoiceMetrics

class VoiceMetricsTest(unittest.TestCase):
    def test_queue_wait_processing_and_cancellation(self):
        now=[0.0];m=VoiceMetrics(lambda:now[0])
        first=m.enqueue();second=m.enqueue()
        now[0]=3;start=m.start(first)
        self.assertEqual(m.snapshot()['oldest_wait_ms'],3000)
        now[0]=8;m.finish(start);m.cancel(second);m.reject()
        s=m.snapshot()
        self.assertEqual((s['waiting'],s['active'],s['completed'],s['rejected']),(0,0,1,1))
        self.assertEqual(s['wait']['p95_ms'],3000)
        self.assertEqual(s['processing']['p95_ms'],5000)
