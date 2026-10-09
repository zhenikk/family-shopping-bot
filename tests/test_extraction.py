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
