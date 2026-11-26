import tempfile, unittest, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from highdeep.jobs import JobStore, Conflict
from highdeep.workflows import WorkflowEngine
from highdeep.core import Backend, Router, HttpAdapter
from highdeep.worker import Worker
from http.server import HTTPServer
from test_core import Handler

def step(name, deps=(), expected=None, tokens=20):
    r={'id':name,'depends_on':list(deps),'capability':'chat','prompt':name,'max_tokens':tokens}
    if expected is not None: r['expected']=expected
    return r

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'jobs.db'
        self.store=JobStore(self.path); self.engine=WorkflowEngine(self.store)
    def create(self,steps,budget=100):
        return self.engine.create('t','key',steps,token_budget=budget,now=1)
    def finish(self,content,now=3):
        job=self.store.claim('t','worker',now=now-1,lease_seconds=30)
        self.store.complete('t',job['id'],job['lease'],{'backend':'b','content':content},now=now)
        return job
    def test_cycle(self):
        with self.assertRaises(ValueError): self.create([step('a',['b']),step('b',['a'])])
    def test_unknown_dependency(self):
        with self.assertRaises(ValueError): self.create([step('a',['missing'])])
    def test_budget(self):
        with self.assertRaises(ValueError): self.create([step('a',tokens=90),step('b',tokens=20)])
    def test_duplicate_step(self):
        with self.assertRaises(ValueError): self.create([step('a'),step('a')])
    def test_idempotency_and_isolation(self):
        w=self.create([step('a')]); self.assertEqual(w,self.create([step('a')]))
        with self.assertRaises(Conflict): self.create([step('b')])
        self.assertIsNone(self.engine.status('other',w))
    def test_dependencies_and_restart(self):
        w=self.create([step('a'),step('b',['a'])])
        self.engine.advance('t',w,now=1)
        self.finish('proof')
        other=WorkflowEngine(JobStore(self.path))
        s=other.advance('t',w,now=4)
        self.assertEqual(s['steps']['a']['state'],'succeeded')
        j=self.store.claim('t','worker',now=5,lease_seconds=30)
        self.assertIn('proof',j['payload']['prompt'])
        self.store.complete('t',j['id'],j['lease'],{'backend':'b','content':'done'},now=6)
        self.assertEqual(other.advance('t',w,now=7)['state'],'succeeded')
    def test_gate_blocks_dependents(self):
        w=self.create([step('a',expected='approved'),step('b',['a'])])
        self.engine.advance('t',w,now=1); self.finish('wrong')
        s=self.engine.advance('t',w,now=4)
        self.assertEqual(s['state'],'failed'); self.assertEqual(s['steps']['b']['state'],'blocked')
        self.assertIsNone(self.store.claim('t','worker',now=5,lease_seconds=30))
    def test_concurrent_advance(self):
        w=self.create([step('a')])
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda _:self.engine.advance('t',w,now=2),range(6)))
        self.assertIsNotNone(self.store.claim('t','w1',now=3,lease_seconds=30))
        self.assertIsNone(self.store.claim('t','w2',now=3,lease_seconds=30))
    def test_real_http_worker(self):
        s=HTTPServer(('127.0.0.1',0),Handler)
        t=threading.Thread(target=s.serve_forever,daemon=True); t.start()
        try:
            backend=Backend('local','cpu',frozenset({'chat'}),'http://127.0.0.1:'+str(s.server_port),'test',100,1)
            worker=Worker(self.store,Router([backend]),HttpAdapter(),clock=lambda:2)
            w=self.create([step('a',expected='a')])
            self.engine.advance('t',w,now=1)
            worker.run_once('t','worker')
            self.assertEqual(self.engine.advance('t',w,now=3)['state'],'succeeded')
        finally: s.shutdown(); s.server_close(); t.join()
    def test_expiry_without_worker_poll(self):
        w=self.create([step('a'),step('b',['a'])])
        self.engine.advance('t',w,now=1)
        self.store.claim('t','worker',now=2,lease_seconds=2)
        s=self.engine.advance('t',w,now=4)
        self.assertEqual(s['state'],'failed')
        self.assertEqual(s['steps']['b']['state'],'blocked')
    def test_reserved_namespace(self):
        with self.assertRaises(ValueError):
            self.store.submit('t','workflow:fake',{},now=1)
    def test_status_read_only(self):
        w=self.create([step('a')])
        self.assertEqual(self.engine.status('t',w)['state'],'pending')
        self.assertIsNone(self.store.claim('t','worker',now=2,lease_seconds=30))
    def test_context_limit(self):
        w=self.create([step('a'),step('b',['a'])])
        self.engine.advance('t',w,now=1)
        self.finish('x'*262144)
        s=self.engine.advance('t',w,now=4)
        self.assertEqual(s['steps']['b']['reason'],'context_limit')
    def test_unrelated_branch_can_complete(self):
        w=self.create([step('a',expected='approved'),step('b',['a']),step('c')])
        self.engine.advance('t',w,now=1)
        for i in range(2):
            job=self.store.claim('t','worker',now=2+i,lease_seconds=30)
            self.store.complete('t',job['id'],job['lease'],{'backend':'b','content':'wrong'},now=3+i)
        s=self.engine.advance('t',w,now=5)
        self.assertEqual(s['steps']['c']['state'],'succeeded')
        self.assertEqual(s['steps']['b']['state'],'blocked')
