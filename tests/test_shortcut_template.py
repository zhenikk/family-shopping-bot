import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ShortcutTemplateTests(unittest.TestCase):
    def test_dictation_uses_ios_speech_language_parameter(self):
        root = Path(__file__).resolve().parents[1]
        for locale, expected in [('uk', 'uk-UA'), ('en', 'en-US')]:
            with self.subTest(locale=locale), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / 'Shopping.shortcut'
                subprocess.run([sys.executable, str(root / 'scripts/build-shopping-shortcut.py'), '--language', locale, '--output', str(output)], check=True, capture_output=True)
                workflow = plistlib.loads(output.read_bytes())
                action = next(item for item in workflow['WFWorkflowActions'] if item['WFWorkflowActionIdentifier'].endswith('.dictatetext'))
                self.assertEqual(action['WFWorkflowActionParameters'].get('WFSpeechLanguage'), expected)
                self.assertNotIn('WFDictateTextLanguage', action['WFWorkflowActionParameters'])
