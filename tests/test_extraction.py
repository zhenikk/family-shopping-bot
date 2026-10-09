import json,os,unittest
from unittest.mock import patch,MagicMock
from shopping_bot.extraction import extract_products
class ExtractionTests(unittest.TestCase):
    def call(self,items):
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'items':items})}}]}).encode()
        with patch.dict(os.environ,{'SHOPPING_EXTRACTOR':'deepseek','DEEPSEEK_API_KEY':'test'}),patch('urllib.request.urlopen',return_value=response):return extract_products('купи молоко')
    def test_disabled(self):
        with patch.dict(os.environ,{'SHOPPING_EXTRACTOR':'rules'}):self.assertIsNone(extract_products('молоко'))
    def test_valid_empty_and_dedup(self):
        self.assertEqual(self.call([]),[])
        self.assertEqual(self.call([{'name':'молоко','note':''},{'name':'Молоко','note':''}]),[('Молоко',None)])
    def test_reject_invalid(self):
        with self.assertRaises(ValueError):self.call([{'name':'молоко','note':42}])
    def test_secret_file_takes_precedence(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            secret=Path(folder)/'key';secret.write_text('file-test-key\n')
            response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"items":[]}'}}]}).encode()
            with patch.dict(os.environ,{'SHOPPING_EXTRACTOR':'deepseek','DEEPSEEK_API_KEY_FILE':str(secret),'DEEPSEEK_API_KEY':'ignored'}),patch('urllib.request.urlopen',return_value=response) as call:
                self.assertEqual(extract_products('молоко'),[])
                self.assertEqual(call.call_args.args[0].get_header('Authorization'),'Bearer file-test-key')
