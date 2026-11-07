import json, tempfile, unittest
from pathlib import Path
from validate_receipt import check
class ValidationTests(unittest.TestCase):
 def test_template_is_not_a_science_pass(self):
  d=json.loads((Path(__file__).resolve().parents[1]/'contracts'/'receipt_template.json').read_text())
  self.assertEqual(check(d),[])
  self.assertEqual(d['gate_statuses']['scientific_admission'],'NOT_EXECUTED')
 def test_fabricated_pass_fails(self):
  d=json.loads((Path(__file__).resolve().parents[1]/'contracts'/'receipt_template.json').read_text())
  d['commands']=[{'status':'PASS','argv':['python','-m','pytest'], 'exit_code':1}]
  self.assertTrue(check(d))
 def test_rpc_without_auth_fails(self):
  d=json.loads((Path(__file__).resolve().parents[1]/'contracts'/'receipt_template.json').read_text())
  d['external_runtime']={'status':'PASS','actual_rpc_response_receipt':'rpc.json','server_identity':'fake'}
  self.assertTrue(check(d))
if __name__=='__main__': unittest.main()
