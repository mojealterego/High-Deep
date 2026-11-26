import unittest, tempfile
from pathlib import Path
from fractions import Fraction
from highdeep.symbolic import evaluate, verify_answer
from highdeep.jobs import JobStore
from highdeep.workflows import WorkflowEngine

class SymbolicTests(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(evaluate('1/3 + 1/6'),Fraction(1,2))
        self.assertTrue(verify_answer('2/4','1/2'))
        self.assertFalse(verify_answer('1/3','1/2'))
    def test_reject_code(self):
        for expr in ["__import__('os')","a+1","[1]","1.5","True","2**10000","1/0","1//2"]:
            with self.subTest(expr=expr):
                with self.assertRaises(ValueError): evaluate(expr)
    def test_bounds(self):
        for expr in ['1+'*1000+'1','9'*300,'('*100+'1'+')'*100]:
            with self.assertRaises(ValueError): evaluate(expr)
    def test_workflow_gate(self):
        with tempfile.TemporaryDirectory() as t:
            s=JobStore(Path(t)/'db'); e=WorkflowEngine(s)
            nodes=[{'id':'math','capability':'math','prompt':'Return 1/2 as a rational expression','max_tokens':30,'rational_expected':'1/2'}]
            w=e.create('t','k',nodes,token_budget=30,now=1); e.advance('t',w,now=1)
            j=s.claim('t','w',now=2,lease_seconds=30)
            s.complete('t',j['id'],j['lease'],{'backend':'b','content':'2/4'},now=3)
            self.assertEqual(e.advance('t',w,now=4)['state'],'succeeded')
    def test_wrong_answer_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            s=JobStore(Path(t)/'db'); e=WorkflowEngine(s)
            nodes=[{'id':'math','capability':'math','prompt':'Return rational','max_tokens':30,'rational_expected':'1/2'},{'id':'next','depends_on':['math'],'capability':'chat','prompt':'continue','max_tokens':20}]
            w=e.create('t','k',nodes,token_budget=50,now=1); e.advance('t',w,now=1)
            j=s.claim('t','w',now=2,lease_seconds=30)
            s.complete('t',j['id'],j['lease'],{'backend':'b','content':'1/3'},now=3)
            self.assertEqual(e.advance('t',w,now=4)['steps']['next']['state'],'blocked')
