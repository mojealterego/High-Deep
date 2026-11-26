import json, subprocess, sys, tempfile, unittest, threading
from pathlib import Path
from http.server import HTTPServer
from test_core import Handler
from highdeep.jobs import JobStore
from highdeep.core import Request

class StageCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.db=self.root/'jobs.db'
    def cli(self,*args,ok=True):
        p=subprocess.run([sys.executable,'-m','highdeep',*map(str,args)],capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0 if ok else 1,p.stderr)
        return p.stdout.strip()
    def scoped(self,command,*args,tenant='t',ok=True):
        return self.cli(command,'--db',self.db,'--tenant',tenant,*args,ok=ok)
    def test_memory_cli(self):
        a=self.scoped('memory-put','--key','k','--kind','episodic','DeepSeek memory')
        b=self.scoped('memory-put','--key','k2','graph')
        self.scoped('memory-link',a,b,'related')
        self.assertEqual(json.loads(self.scoped('memory-search','DeepSeek'))[0]['id'],a)
        self.assertEqual(json.loads(self.scoped('memory-neighbors',a))[0]['id'],b)
        self.assertEqual(json.loads(self.scoped('memory-episodes'))[0]['id'],a)
        self.assertEqual(json.loads(self.scoped('memory-search','DeepSeek',tenant='other')),[])
        self.scoped('memory-forget',b)
        self.assertEqual(json.loads(self.scoped('memory-neighbors',a)),[])
    def test_symbolic_cli(self):
        self.assertEqual(self.cli('symbolic','1/3+1/6'),'1/2')
        self.cli('symbolic','1/0',ok=False)
    def test_evolution_and_memory_inference(self):
        s=HTTPServer(('127.0.0.1',0),Handler); t=threading.Thread(target=s.serve_forever,daemon=True); t.start()
        try:
            config=self.root/'backends.json'
            config.write_text(json.dumps([{'name':n,'hardware':'cpu','capabilities':['chat'],'endpoint':'http://127.0.0.1:'+str(s.server_port),'model':'test','max_tokens':100,'priority':i} for i,n in enumerate(['a','b'])]))
            self.scoped('memory-put','--key','k','DeepSeek memory')
            text=self.cli('run','--config',config,'--memory-db',self.db,'--memory-tenant','t','--memory-query','DeepSeek','--max-tokens','20','hello')
            self.assertIn('DeepSeek memory',text)
            self.assertIn('untrusted data',text)
            state=json.loads(self.scoped('evolve-init','--config',config))
            cases=[{'id':str(i),'capability':'chat','max_tokens':20,'observations':{'a':{'correct':True,'latency_ms':100},'b':{'correct':True,'latency_ms':80}}} for i in range(4)]
            evidence=self.root/'replay.json'; evidence.write_text(json.dumps(cases))
            out=json.loads(self.scoped('evolve-promote','--config',config,'--evidence',evidence,'--expected',state['head'],'b','a'))
            self.assertTrue(out['accepted'])
            self.assertEqual(json.loads(self.scoped('evolve-status'))['policy'],['b','a'])
            store=JobStore(self.db); job=store.submit('t','job',vars(Request('chat','hello',20)),now=1)
            self.scoped('work-batch','--config',config,'--worker','w','--evolved-policy')
            self.assertEqual(store.get('t',job)['result']['backend'],'b')
        finally: s.shutdown(); s.server_close(); t.join()
