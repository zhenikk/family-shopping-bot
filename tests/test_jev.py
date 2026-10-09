import json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from shopping_bot.jev import classify,submit
from shopping_bot.analytics import Analytics
from shopping_bot.families import Families
from shopping_bot.store import Store
class JevTests(unittest.TestCase):
    def test_validated_api_and_usage_cost(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'key';key.write_text('test')
            result={'model':'jev-test','answers':{'category':{'type':'choice','choice':'pets','confidence':.9}},'usage':{'input_tokens':1000,'output_tokens':20}}
            response=MagicMock();response.__enter__.return_value.read.side_effect=lambda size:json.dumps(result).encode()
            with patch.dict(os.environ,{'TYPESAFE_API_KEY_FILE':str(key)}),patch('urllib.request.urlopen',return_value=response) as call:
                answer=classify('Корм для кота');self.assertAlmostEqual(answer['estimated_usd'],.000042)
                self.assertEqual(answer['category'],'pets')
                self.assertEqual(call.call_args.args[0].full_url,'https://api.typesafe.ai/v1/systemone')
                result['answers']['category']['choice']='invalid'
                with self.assertRaises(ValueError):classify('Корм')
    def test_persisted_daily_cap_and_cost(self):
        with tempfile.TemporaryDirectory() as folder:
            analytics=Analytics(Families(Store(Path(folder)/'shopping.sqlite3'),Path(folder)/'photos'))
            for i in range(100):self.assertIsNotNone(analytics.reserve_jev(1,1,str(i),'other'))
            self.assertIsNone(analytics.reserve_jev(1,1,'extra','other'))
            data=analytics.jev_experiments();self.assertEqual(data['totals']['requests'],100)
            row=data['items'][0];self.assertNotIn('name',row)
            analytics.finish_jev(row['request_id'],'ok',dict(category='home',input_tokens=1000,output_tokens=20,estimated_usd=.000042,confidence=.8,latency_ms=100,model='test'))
            self.assertAlmostEqual(analytics.jev_experiments()['totals']['estimated_usd'],.000042)
    def test_off_does_not_submit(self):
        with patch.dict(os.environ,{'SHOPPING_JEV_MODE':'off'}),patch('shopping_bot.jev.POOL.submit') as pool:
            submit(None,1,1,{});pool.assert_not_called()
