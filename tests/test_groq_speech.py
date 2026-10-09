import os,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from shopping_bot.groq_speech import transcribe_audio
class GroqSpeechTests(unittest.TestCase):
    def test_multipart_language_and_file_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'key';key.write_text('test-key');wav=Path(folder)/'voice.wav';wav.write_bytes(b'RIFFtest')
            response=MagicMock();response.__enter__.return_value.read.return_value=b'{"text":"Milk"}'
            with patch.dict(os.environ,{'GROQ_API_KEY_FILE':str(key)}),patch('urllib.request.urlopen',return_value=response) as call:
                self.assertEqual(transcribe_audio(wav,'uk'),'Milk')
                request=call.call_args.args[0]
                self.assertIn(b'whisper-large-v3-turbo',request.data)
                self.assertIn(b'\r\n\r\nuk\r\n',request.data)
                self.assertEqual(request.get_header('Authorization'),'Bearer test-key')
                self.assertEqual(request.get_header('User-agent'),'FamilyShoppingBot/1.0')
                response.__enter__.return_value.read.return_value=b'{"text":12}'
                with self.assertRaises(ValueError):transcribe_audio(wav,'uk')
    def test_api_failure_falls_back_to_local(self):
        from shopping_bot.speech import transcribe
        with tempfile.TemporaryDirectory() as folder:
            cli=Path(folder)/'cli';model=Path(folder)/'model';cli.touch();model.touch()
            telegram=MagicMock()
            def run(args,**kwargs):
                if args[0]=='ffmpeg':Path(args[-1]).write_bytes(b'RIFF')
                else:Path(args[args.index('-of')+1]+'.txt').write_text('Молоко')
            with patch.dict(os.environ,{'SHOPPING_SPEECH_PROVIDER':'groq'}),patch('shopping_bot.speech.transcribe_audio',side_effect=TimeoutError),patch('shopping_bot.speech.subprocess.run',side_effect=run):
                self.assertEqual(transcribe(telegram,'file',cli,model),'Молоко')
