import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from highdeep.core import Backend, Request, RouteError
from highdeep.adaptive import AdaptiveExecutor

def backend(name,priority=0):
    return Backend(name,'cpu',frozenset({'chat'}),'http://127.0.0.1:12345','m',100,priority)

class Clock:
    now=0
    def __call__(self): return self.now

class Transport:
    def __init__(self):
        self.calls=[]; self.bad=set()
    def execute(self,b,r):
        self.calls.append(b.name)
        if b.name in self.bad: raise RouteError('failed')
        return b.name

class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock(); self.transport=Transport()
        self.a=backend('a'); self.b=backend('b',1)
        self.req=Request('chat','hello',20)
    def pool(self,bs=None,**kwargs):
        return AdaptiveExecutor(bs or [self.a,self.b],self.transport,clock=self.clock,**kwargs)
    def test_circuit_and_no_replay(self):
        p=self.pool(failure_threshold=1,cooldown=10)
        self.transport.bad.add('a')
        with self.assertRaises(RouteError): p.execute(self.req)
        self.assertEqual(self.transport.calls,['a'])
        self.assertEqual(p.execute(self.req),('b','b'))
        self.assertEqual(p.metrics()['a']['state'],'open')
        self.clock.now=10; self.transport.bad.clear()
        self.assertEqual(p.execute(self.req),('a','a'))
        self.assertEqual(p.metrics()['a']['state'],'closed')
    def test_fail_closed(self):
        p=self.pool([self.a],failure_threshold=1)
        self.transport.bad.add('a')
        with self.assertRaises(RouteError): p.execute(self.req)
        with self.assertRaises(RouteError): p.execute(self.req)
        self.assertEqual(self.transport.calls,['a'])
    def test_capability_and_budget(self):
        p=self.pool()
        for r in (Request('vision','x',1),Request('chat','x',101)):
            with self.assertRaises(RouteError): p.execute(r)
        self.assertEqual(self.transport.calls,[])
    def test_bulkhead(self):
        entered=threading.Event(); release=threading.Event()
        class Blocking:
            def execute(self,b,r):
                entered.set(); release.wait(3); return 'ok'
        p=AdaptiveExecutor([self.a],Blocking(),max_inflight=1)
        with ThreadPoolExecutor(max_workers=2) as e:
            f=e.submit(p.execute,self.req)
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(RouteError): p.execute(self.req)
            finally: release.set()
            self.assertEqual(f.result(timeout=3),('a','ok'))
        self.assertEqual(p.metrics()['a']['inflight'],0)
    def test_metrics_and_latency(self):
        clock=self.clock
        class Slow:
            def execute(self,b,r):
                clock.now+=0.25; return 'ok'
        p=AdaptiveExecutor([self.a],Slow(),clock=clock)
        p.execute(self.req)
        m=p.metrics()['a']
        self.assertEqual(m['successes'],1)
        self.assertEqual(m['ewma_ms'],250)
        self.assertEqual(m['inflight'],0)
        self.assertNotIn('prompt',m)
    def test_half_open_probe_exclusive(self):
        p=self.pool([self.a],failure_threshold=1,cooldown=10,max_inflight=4)
        self.transport.bad.add('a')
        with self.assertRaises(RouteError): p.execute(self.req)
        self.clock.now=10
        entered=threading.Event(); release=threading.Event()
        class Probe:
            def execute(self,b,r):
                entered.set(); release.wait(3); return 'ok'
        p.adapter=Probe()
        with ThreadPoolExecutor(max_workers=2) as e:
            f=e.submit(p.execute,self.req)
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(RouteError): p.execute(self.req)
            finally: release.set()
            self.assertEqual(f.result(timeout=3),('a','ok'))
    def test_unexpected_exception_releases_capacity(self):
        class Broken:
            def execute(self,b,r): raise RuntimeError('unexpected')
        p=AdaptiveExecutor([self.a],Broken(),max_inflight=1)
        with self.assertRaises(RuntimeError): p.execute(self.req)
        self.assertEqual(p.metrics()['a']['inflight'],0)
    def test_worker_integration(self):
        import tempfile
        from pathlib import Path
        from highdeep.jobs import JobStore
        from highdeep.core import Router
        from highdeep.worker import Worker
        with tempfile.TemporaryDirectory() as tmp:
            s=JobStore(Path(tmp)/'db')
            p=self.pool(failure_threshold=1)
            self.transport.bad.add('a')
            w=Worker(s,Router([self.a,self.b]),self.transport,clock=lambda:2,executor=p)
            a=s.submit('t','a',vars(self.req),now=1)
            w.run_once('t','w')
            self.assertEqual(s.get('t',a)['state'],'failed')
            b=s.submit('t','b',vars(self.req),now=1)
            w.run_once('t','w')
            self.assertEqual(s.get('t',b)['result'],{'backend':'b','content':'b'})
    def test_old_success_does_not_close_new_circuit(self):
        entered=threading.Event(); release=threading.Event()
        class Race:
            def execute(self,b,r):
                if r.prompt=='slow':
                    entered.set(); release.wait(3); return 'ok'
                raise RouteError('failed')
        p=AdaptiveExecutor([self.a],Race(),max_inflight=2,failure_threshold=1)
        with ThreadPoolExecutor(max_workers=2) as e:
            f=e.submit(p.execute,Request('chat','slow',20))
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(RouteError): p.execute(self.req)
            finally: release.set()
            self.assertEqual(f.result(timeout=3),('a','ok'))
        self.assertEqual(p.metrics()['a']['state'],'open')
        self.assertEqual(p.metrics()['a']['inflight'],0)
    def test_invalid_limits(self):
        for kw in ({'max_inflight':0},{'failure_threshold':0},{'cooldown':float('nan')}):
            with self.assertRaises(ValueError): self.pool(**kw)
    def test_cli_batch_real_http(self):
        import json, subprocess, sys, tempfile
        from pathlib import Path
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from test_core import Handler
        from highdeep.jobs import JobStore
        class Unavailable(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(503); self.end_headers()
            def log_message(self,*args): pass
        servers=[HTTPServer(('127.0.0.1',0),h) for h in (Unavailable,Handler)]
        threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in servers]
        for t in threads: t.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); db=root/'jobs.db'; config=root/'backends.json'
                config.write_text(json.dumps([{'name':n,'hardware':'cpu','capabilities':['chat'],'endpoint':'http://127.0.0.1:'+str(s.server_port),'model':'m','max_tokens':100,'priority':i} for i,(n,s) in enumerate(zip(('a','b'),servers))]))
                store=JobStore(db)
                a=store.submit('t','a',vars(self.req),now=1)
                b=store.submit('t','b',vars(self.req),now=2)
                proc=subprocess.run([sys.executable,'-m','highdeep','work-batch','--db',str(db),'--tenant','t','--worker','w','--config',str(config),'--max-jobs','3','--failure-threshold','1'],capture_output=True,text=True,timeout=15)
                self.assertEqual(proc.returncode,0,proc.stderr)
                report=json.loads(proc.stdout)
                self.assertEqual(report['processed'],2)
                self.assertEqual(store.get('t',a)['state'],'failed')
                self.assertEqual(store.get('t',b)['result'],{'backend':'b','content':'hello'})
                self.assertEqual(report['backends']['a']['state'],'open')
                self.assertEqual(report['backends']['b']['successes'],1)
        finally:
            for s in servers: s.shutdown(); s.server_close()
            for t in threads: t.join()
