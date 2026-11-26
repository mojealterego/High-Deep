import tempfile, unittest
from pathlib import Path
from highdeep.jobs import JobStore, Conflict
from highdeep.memory import MemoryFabric

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db'; self.m=MemoryFabric(JobStore(self.path),max_records=3)
    def add(self,key,text,kind='semantic',tenant='t',now=1):
        return self.m.remember(tenant,key,text,kind=kind,now=now)
    def test_persistence_and_rank(self):
        a=self.add('a','DeepSeek model model routing')
        self.add('b','photography image')
        m=MemoryFabric(JobStore(self.path))
        self.assertEqual(m.search('t','model routing')[0]['id'],a)
        self.assertEqual(m.search('other','model'),[])
    def test_idempotency(self):
        a=self.add('a','hello')
        self.assertEqual(a,self.add('a','hello'))
        with self.assertRaises(Conflict): self.add('a','different')
    def test_limit(self):
        for i in range(3): self.add(str(i),'x')
        with self.assertRaises(ValueError): self.add('overflow','x')
        self.add('other','x',tenant='other')
    def test_graph_isolation_and_cycle(self):
        a=self.add('a','one'); b=self.add('b','two'); c=self.add('c','three',tenant='other')
        self.m.link('t',a,b,'related')
        self.m.link('t',b,a,'related')
        self.assertEqual([r['id'] for r in self.m.neighbors('t',a,depth=3)],[b])
        with self.assertRaises(ValueError): self.m.link('t',a,c,'related')
    def test_episode_order(self):
        a=self.add('a','one','episodic',now=1); b=self.add('b','two','episodic',now=2)
        self.assertEqual([r['id'] for r in self.m.episodes('t')],[b,a])
    def test_invalid(self):
        with self.assertRaises(ValueError): self.add('a','   ')
        with self.assertRaises(ValueError): self.m.search('t','x',limit=101)
    def test_delete_edges(self):
        a=self.add('a','one'); b=self.add('b','two')
        self.m.link('t',a,b,'related')
        self.assertTrue(self.m.forget('t',b))
        self.assertEqual(self.m.neighbors('t',a),[])
        self.assertFalse(self.m.forget('other',a))
    def test_bounded_context(self):
        import json
        a=self.add('a','routing memory')
        self.add('b','routing '+'x'*9000)
        context=self.m.context('t','routing',budget_bytes=512)
        self.assertLessEqual(len(context.encode()),512)
        self.assertEqual([x['id'] for x in json.loads(context)],[a])
        self.assertEqual(json.loads(self.m.context('other','routing')),[])
