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

                identifiers = [item['WFWorkflowActionIdentifier'] for item in workflow['WFWorkflowActions']]
                self.assertNotIn('is.workflow.actions.showresult', identifiers)
                self.assertEqual(identifiers[-1], 'is.workflow.actions.nothing')

    def test_audio_handoff_and_raw_upload(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'audio.shortcut'
            subprocess.run([sys.executable, str(root / 'scripts/build-shopping-shortcut.py'), '--mode', 'audio', '--output', str(output)], check=True, capture_output=True)
            workflow = plistlib.loads(output.read_bytes())
            actions = workflow['WFWorkflowActions']
            self.assertEqual(actions[1]['WFWorkflowActionIdentifier'], 'is.workflow.actions.url')
            self.assertEqual(actions[1]['WFWorkflowActionParameters']['WFURLActionURL'], 'shortcuts://')
            self.assertEqual(actions[2]['WFWorkflowActionIdentifier'], 'is.workflow.actions.openurl')
            self.assertEqual(actions[2]['WFWorkflowActionParameters']['WFInput']['Value']['OutputUUID'], actions[1]['WFWorkflowActionParameters']['UUID'])
            self.assertNotIn('is.workflow.actions.dismisssiri', [item['WFWorkflowActionIdentifier'] for item in actions])
            self.assertNotIn('is.workflow.actions.openapp', [item['WFWorkflowActionIdentifier'] for item in actions])
            self.assertNotIn('is.workflow.actions.handoff', [item['WFWorkflowActionIdentifier'] for item in actions])
            self.assertEqual(actions[3]['WFWorkflowActionIdentifier'], 'is.workflow.actions.recordaudio')
            request = actions[4]['WFWorkflowActionParameters']
            self.assertTrue(request['WFURL'].endswith('/shortcuts/audio'))
            self.assertEqual(request['WFHTTPBodyType'], 'File')
            self.assertNotIn('WFJSONValues', request)
            self.assertEqual(request['WFRequestVariable']['Value']['OutputUUID'], actions[3]['WFWorkflowActionParameters']['UUID'])
            self.assertEqual(workflow['WFWorkflowImportQuestions'][0]['ActionIndex'], 0)
