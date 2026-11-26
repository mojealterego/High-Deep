import tempfile, unittest
from pathlib import Path
from highdeep.jobs import JobStore, Conflict
from highdeep.evolution import EvolutionEngine, compare, apply_policy
from highdeep.core import Backend, Router, Request

def backend(name,priority):
    return Backend(name,'cpu',frozenset({'chat'}),'http://127.0.0.1:12345','m',100,priority)
def cases(bad=False):
    return [{'id':str(i),'capability':'chat','max_tokens':20,'observations':{'a':{'correct':True,'latency_ms':100},'b':{'correct':not bad,'latency_ms':80}}} for i in range(4)]

class EvolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db'; self.s=JobStore(self.path)
        self.bs=[backend('a',0),backend('b',1)]
        self.e=EvolutionEngine(self.s)
    def test_replay_gate(self):
        self.assertTrue(compare(self.bs,['a','b'],['b','a'],cases())['accepted'])
        self.assertFalse(compare(self.bs,['a','b'],['b','a'],cases(True))['accepted'])
        self.assertFalse(compare(self.bs,['a','b'],['a','b'],cases())['accepted'])
    def test_missing_or_duplicate_observations(self):
        c=cases(); del c[0]['observations']['b']
        with self.assertRaises(ValueError): compare(self.bs,['a','b'],['b','a'],c)
        c=cases(); c[1]['id']=c[0]['id']
        with self.assertRaises(ValueError): compare(self.bs,['a','b'],['b','a'],c)
    def test_promote_restart_cas(self):
        r=self.e.initialize('t',self.bs)
        out=self.e.promote('t',self.bs,['b','a'],cases(),expected=r['head'])
        self.assertTrue(out['accepted'])
        active=EvolutionEngine(JobStore(self.path)).active('t')
        self.assertEqual(active['policy'],['b','a'])
        with self.assertRaises(Conflict): self.e.promote('t',self.bs,['a','b'],cases(),expected=r['head'])
        self.assertTrue(self.e.verify('t'))
    def test_rejected_does_not_activate(self):
        r=self.e.initialize('t',self.bs)
        self.assertFalse(self.e.promote('t',self.bs,['b','a'],cases(True),expected=r['head'])['accepted'])
        self.assertEqual(self.e.active('t')['policy'],['a','b'])
        self.assertIsNone(self.e.active('other'))
        self.assertTrue(self.e.verify('t'))
    def test_runtime_policy(self):
        r=Router(apply_policy(self.bs,['b','a']))
        self.assertEqual(r.choose(Request('chat','x',10)).name,'b')
        with self.assertRaises(ValueError): apply_policy(self.bs,['a','a'])
    def test_tamper_detected(self):
        self.e.initialize('t',self.bs)
        with self.s._tx() as db: db.execute("UPDATE evolution_events SET body='{}'")
        self.assertFalse(self.e.verify('t'))
    def test_reject_config_change_and_reuse(self):
        r=self.e.initialize('t',self.bs)
        result=self.e.promote('t',self.bs,['b','a'],cases(True),expected=r['head'])
        new_cases=cases()
        with self.assertRaises(Conflict):
            self.e.promote('t',self.bs,['b','a'],new_cases,expected=result['head'])
        with self.assertRaises(Conflict):
            self.e.runtime_backends('t',[backend('a',1),backend('b',0)])
    def test_collect_http(self):
        from highdeep.evolution import collect_replay
        from highdeep.core import HttpAdapter
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import threading,json
        class Echo(BaseHTTPRequestHandler):
            def do_POST(self):
                req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                raw=json.dumps({'choices':[{'message':{'content':req['messages'][0]['content']}}]}).encode()
                self.send_response(200); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def log_message(self,*args): pass
        server=HTTPServer(('127.0.0.1',0),Echo)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            b=Backend('local','cpu',frozenset({'math'}),'http://127.0.0.1:'+str(server.server_port),'m',100,0)
            tasks=[{'id':str(i),'capability':'math','max_tokens':20,'prompt':'2/4','rational_expected':'1/2'} for i in range(4)]
            observations=collect_replay([b],tasks,HttpAdapter())
            self.assertEqual(len(observations),4)
            self.assertTrue(all(x['observations']['local']['correct'] and x['observations']['local']['latency_ms']>0 for x in observations))
        finally:
            server.shutdown(); server.server_close(); thread.join()
    def test_fast_wrong_not_promoted(self):
        data=cases(True)
        for case in data: case['observations']['a']['correct']=False
        self.assertFalse(compare(self.bs,['a','b'],['b','a'],data)['accepted'])
