import unittest, threading, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from highdeep.core import Registry, Backend, Router, Request, RouteError, HttpAdapter
class Handler(BaseHTTPRequestHandler):
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  body=json.dumps({'choices':[{'message':{'content':data['messages'][0]['content']}}]}).encode()
  self.send_response(200); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
 def log_message(self,*args): pass
class TestCore(unittest.TestCase):
 def setUp(self):
  self.a=Backend('a','cpu',frozenset({'chat'}),'http://127.0.0.1:12345','m',100,2)
  self.b=Backend('b','cuda',frozenset({'chat','vision'}),'http://127.0.0.1:12346','m',200,1)
 def test_inventory(self):
  rows=Registry.load(Path('inventory.json')).rows
  self.assertEqual(len(rows),47); self.assertEqual(len({x['commit'] for x in rows}),47)
 def test_route_capability(self):
  self.assertEqual(Router([self.a,self.b]).choose(Request('vision','x',20)).name,'b')
 def test_route_budget(self):
  self.assertEqual(Router([self.a,self.b]).choose(Request('chat','x',150)).name,'b')
 def test_fail_closed(self):
  with self.assertRaises(RouteError): Router([self.a]).choose(Request('vision','x',20))
 def test_invalid(self):
  with self.assertRaises(ValueError): Request('chat','',0)
 def test_ssrf_config(self):
  with self.assertRaises(ValueError): Backend('x','cpu',frozenset({'chat'}),'http://169.254.169.254','m',100,1)
 def test_duplicate_backend(self):
  with self.assertRaises(ValueError): Router([self.a,self.a])
 def test_http(self):
  s=HTTPServer(('127.0.0.1',0),Handler); t=threading.Thread(target=s.serve_forever,daemon=True); t.start()
  try:
   b=Backend('test','cpu',frozenset({'chat'}),'http://127.0.0.1:'+str(s.server_port),'m',100,1)
   self.assertEqual(HttpAdapter().execute(b,Request('chat','hello',20)),'hello')
  finally: s.shutdown(); s.server_close(); t.join()
if __name__=='__main__': unittest.main()
