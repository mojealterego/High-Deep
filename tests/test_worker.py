import tempfile, unittest, threading
from pathlib import Path
from http.server import HTTPServer
from test_core import Handler
from highdeep.core import Backend, Router, HttpAdapter
from highdeep.jobs import JobStore
from highdeep.worker import Worker
class TestWorker(unittest.TestCase):
 def test_real_protocol_durable_result(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=JobStore(Path(tmp)/'jobs.db')
   server=HTTPServer(('127.0.0.1',0),Handler)
   thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
   try:
    backend=Backend('local','cpu',frozenset({'chat'}),'http://127.0.0.1:'+str(server.server_port),'test',100,1)
    job=store.submit('tenant','key',{'capability':'chat','prompt':'hello','max_tokens':20},now=1)
    worker=Worker(store,Router([backend]),HttpAdapter(),clock=lambda:2)
    self.assertEqual(worker.run_once('tenant','worker'),job)
    self.assertEqual(store.get('tenant',job)['result'],{'backend':'local','content':'hello'})
    self.assertIsNone(worker.run_once('tenant','worker'))
   finally: server.shutdown(); server.server_close(); thread.join()
 def test_bad_request_is_failed(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=JobStore(Path(tmp)/'jobs.db')
   job=store.submit('t','k',{'prompt':'bad'},now=1)
   Worker(store,Router([]),HttpAdapter(),clock=lambda:2).run_once('t','w')
   self.assertEqual(store.get('t',job)['state'],'failed')
