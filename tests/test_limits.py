import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shopping_bot.limits import RateLimiter, VoiceAdmission
from shopping_bot.speech import transcribe, SpeechError


class LimitsTests(unittest.TestCase):
    def test_refill_and_identity_flood_do_not_reset_existing_limits(self):
        now = [0]
        limiter = RateLimiter(2, 1, max_keys=2, clock=lambda: now[0])
        self.assertTrue(limiter.allow(1))
        self.assertTrue(limiter.allow(1))
        self.assertFalse(limiter.allow(1))
        self.assertTrue(limiter.allow(2))
        self.assertFalse(limiter.allow(3))
        self.assertFalse(limiter.allow(1))
        now[0] = 3
        self.assertTrue(limiter.allow(3))
        self.assertLessEqual(len(limiter.buckets), 2)

    def test_global_voice_capacity_and_release(self):
        admission = VoiceAdmission(total=3, per_user=2)
        self.assertTrue(admission.acquire(1))
        self.assertTrue(admission.acquire(1))
        self.assertFalse(admission.acquire(1))
        self.assertTrue(admission.acquire(2))
        self.assertFalse(admission.acquire(3))
        admission.release(1)
        self.assertTrue(admission.acquire(3))

    def test_decoded_audio_limit_and_whisper_execution_deadline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cli = root / 'cli'; cli.touch()
            model = root / 'model'; model.touch()
            class Telegram:
                def download(self, file_id, destination):
                    destination.write_bytes(b'audio')
            calls = []
            def long_audio(command, **kwargs):
                calls.append(command)
                with Path(command[-1]).open('wb') as wav:
                    wav.truncate(121 * 16000 * 2)
            with patch('shopping_bot.speech.subprocess.run', side_effect=long_audio):
                with self.assertRaises(SpeechError):
                    transcribe(Telegram(), 'id', cli, model)
            self.assertEqual(len(calls), 1)  # Never invoke Whisper for overlong audio.
            def timeout(command, **kwargs):
                if command[0] == 'ffmpeg':
                    Path(command[-1]).write_bytes(b'wav')
                else:
                    self.assertEqual(kwargs['timeout'], 300)
                    raise subprocess.TimeoutExpired(command, 300)
            with patch('shopping_bot.speech.subprocess.run', side_effect=timeout):
                with self.assertRaises(SpeechError):
                    transcribe(Telegram(), 'id', cli, model)
