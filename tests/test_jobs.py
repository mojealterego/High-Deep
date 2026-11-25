import tempfile, unittest
from pathlib import Path
from highdeep.jobs import JobStore, Conflict
class TestJobs(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name)/'jobs.db'
  self.s=JobStore(self.path)
 def test_idempotency(self):
  a=self.s.submit('tenant','key',{'prompt':'a'},now=1)
  self.assertEqual(a,self.s.submit('tenant','key',{'prompt':'a'},now=2))
  with self.assertRaises(Conflict): self.s.submit('tenant','key',{'prompt':'b'},now=3)
 def test_tenant_scope(self):
  a=self.s.submit('a','key',{'prompt':'a'},now=1)
  b=self.s.submit('b','key',{'prompt':'a'},now=1)
  self.assertNotEqual(a,b)
  self.assertIsNone(self.s.get('b',a))
 def test_lease_fencing(self):
  a=self.s.submit('t','k',{'prompt':'a'},now=1)
  first=self.s.claim('t','w1',now=2,lease_seconds=3)
  self.assertIsNone(self.s.claim('t','w2',now=3,lease_seconds=3))
  second=self.s.claim('t','w2',now=5,lease_seconds=3)
  self.assertEqual(second['id'],a)
  with self.assertRaises(Conflict): self.s.complete('t',a,first['lease'],{'answer':'old'},now=6)
  self.s.complete('t',a,second['lease'],{'answer':'new'},now=6)
  self.assertEqual(self.s.get('t',a)['state'],'succeeded')
 def test_restart(self):
  a=self.s.submit('t','k',{'prompt':'a'},now=1)
  self.assertEqual(JobStore(self.path).get('t',a)['state'],'queued')
 def test_retry_limit(self):
  a=self.s.submit('t','k',{'prompt':'a'},now=1,max_attempts=1)
  self.s.claim('t','w',now=2,lease_seconds=1)
  self.assertIsNone(self.s.claim('t','w',now=3,lease_seconds=1))
  self.assertEqual(self.s.get('t',a)['state'],'failed')
 def test_failure(self):
  a=self.s.submit('t','k',{'prompt':'a'},now=1)
  j=self.s.claim('t','w',now=2,lease_seconds=10)
  self.s.fail('t',a,j['lease'],now=3)
  self.assertEqual(self.s.get('t',a)['state'],'failed')
 def test_concurrent_claim(self):
  from concurrent.futures import ThreadPoolExecutor
  self.s.submit('t','k',{'prompt':'a'},now=1)
  with ThreadPoolExecutor(max_workers=8) as pool:
   results=list(pool.map(lambda i: self.s.claim('t','w'+str(i),now=2,lease_seconds=10),range(8)))
  self.assertEqual(sum(x is not None for x in results),1)
 def test_wrong_tenant_cannot_finish(self):
  a=self.s.submit('t','k',{},now=1)
  j=self.s.claim('t','w',now=2,lease_seconds=10)
  with self.assertRaises(Conflict): self.s.complete('other',a,j['lease'],{},now=3)
 def test_invalid_json(self):
  with self.assertRaises(ValueError): self.s.submit('t','k',{'x':float('nan')},now=1)
