"""Bounded, tenant-scoped persistent lexical, graph and episodic memory."""
from collections import Counter, deque
import math
import json
import heapq
import re
import unicodedata
import uuid
from .jobs import Conflict, _label, _time

def _words(text):
    return Counter(re.findall(r'[^\W_]+',unicodedata.normalize('NFKC',text).casefold()))

def _text(text):
    if not isinstance(text,str) or not text.strip() or len(text.encode())>16384:
        raise ValueError('Invalid memory text')

def _limit(limit):
    if type(limit) is not int or not 1<=limit<=100:
        raise ValueError('Invalid memory limit')

class MemoryFabric:
    def __init__(self,store,*,max_records=10000,max_edges=40000):
        if type(max_records) is not int or not 1<=max_records<=10000 or type(max_edges) is not int or not 1<=max_edges<=40000:
            raise ValueError('Invalid memory quota')
        self.store,self.max_records,self.max_edges=store,max_records,max_edges
        with store._tx() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS memories (
              tenant TEXT NOT NULL,id TEXT NOT NULL,idem TEXT NOT NULL,
              kind TEXT NOT NULL,text TEXT NOT NULL,created REAL NOT NULL,
              PRIMARY KEY(tenant,id),UNIQUE(tenant,idem))""")
            db.execute("""CREATE TABLE IF NOT EXISTS memory_edges (
              tenant TEXT NOT NULL,src TEXT NOT NULL,dst TEXT NOT NULL,relation TEXT NOT NULL,
              PRIMARY KEY(tenant,src,dst,relation))""")
            db.execute('CREATE INDEX IF NOT EXISTS memories_episode ON memories(tenant,kind,created,id)')
    def remember(self,tenant,key,text,*,kind='semantic',now):
        _label(tenant); _label(key); _time(now); _text(text)
        if kind not in ('semantic','episodic'):
            raise ValueError('Invalid memory kind')
        with self.store._tx() as db:
            row=db.execute('SELECT id,text,kind FROM memories WHERE tenant=? AND idem=?',(tenant,key)).fetchone()
            if row:
                if row['text']!=text or row['kind']!=kind:
                    raise Conflict('Memory key reused with different payload')
                return row['id']
            if db.execute('SELECT count(*) FROM memories WHERE tenant=?',(tenant,)).fetchone()[0]>=self.max_records:
                raise ValueError('Memory quota exhausted')
            ident=uuid.uuid4().hex
            db.execute('INSERT INTO memories VALUES(?,?,?,?,?,?)',(tenant,ident,key,kind,text,now))
            return ident
    @staticmethod
    def _record(row):
        return {k:row[k] for k in ('id','kind','text','created')}
    def search(self,tenant,query,*,limit=10):
        _label(tenant); _text(query); _limit(limit)
        q=_words(query); qn=math.sqrt(sum(v*v for v in q.values()))
        if not qn: return []
        with self.store._tx() as db:
            def scored():
                for row in db.execute('SELECT * FROM memories WHERE tenant=?',(tenant,)):
                    words=_words(row['text']); dot=sum(v*words.get(k,0) for k,v in q.items())
                    if dot:
                        score=dot/(qn*math.sqrt(sum(v*v for v in words.values())))
                        yield dict(self._record(row),score=score)
            return heapq.nsmallest(limit,scored(),key=lambda r:(-r['score'],-r['created'],r['id']))
    def context(self,tenant,query,*,budget_bytes=8192,limit=10):
        if type(budget_bytes) is not int or not 2<=budget_bytes<=32768:
            raise ValueError('Invalid context budget')
        selected=[]
        for row in self.search(tenant,query,limit=limit):
            item={k:row[k] for k in ('id','kind','text')}
            encoded=json.dumps(selected+[item],ensure_ascii=False,separators=(',',':'))
            if len(encoded.encode())<=budget_bytes:
                selected.append(item)
        return json.dumps(selected,ensure_ascii=False,separators=(',',':'))
    def episodes(self,tenant,*,limit=10):
        _label(tenant); _limit(limit)
        with self.store._tx() as db:
            return [self._record(r) for r in db.execute("SELECT * FROM memories WHERE tenant=? AND kind='episodic' ORDER BY created DESC,id LIMIT ?",(tenant,limit))]
    def link(self,tenant,src,dst,relation):
        for value in (tenant,src,dst,relation): _label(value)
        if src==dst: raise ValueError('Self edge')
        with self.store._tx() as db:
            if db.execute('SELECT count(*) FROM memories WHERE tenant=? AND id IN (?,?)',(tenant,src,dst)).fetchone()[0]!=2:
                raise ValueError('Unknown memory in tenant')
            if db.execute('SELECT 1 FROM memory_edges WHERE tenant=? AND src=? AND dst=? AND relation=?',(tenant,src,dst,relation)).fetchone():
                return
            if db.execute('SELECT count(*) FROM memory_edges WHERE tenant=?',(tenant,)).fetchone()[0]>=self.max_edges:
                raise ValueError('Graph quota exhausted')
            db.execute('INSERT INTO memory_edges VALUES(?,?,?,?)',(tenant,src,dst,relation))
    def neighbors(self,tenant,src,*,depth=1,limit=100):
        _label(tenant); _label(src); _limit(limit)
        if type(depth) is not int or not 1<=depth<=8: raise ValueError('Invalid graph depth')
        with self.store._tx() as db:
            if not db.execute('SELECT 1 FROM memories WHERE tenant=? AND id=?',(tenant,src)).fetchone():
                raise ValueError('Unknown memory')
            seen={src}; queue=deque([(src,0)]); result=[]
            while queue and len(result)<limit:
                node,d=queue.popleft()
                if d>=depth: continue
                for row in db.execute("""SELECT m.*,e.relation FROM memory_edges e JOIN memories m
                    ON m.tenant=e.tenant AND m.id=e.dst WHERE e.tenant=? AND e.src=? ORDER BY e.dst,e.relation""",(tenant,node)):
                    if row['id'] in seen: continue
                    seen.add(row['id']); result.append(dict(self._record(row),depth=d+1,relation=row['relation']))
                    queue.append((row['id'],d+1))
                    if len(result)>=limit: break
            return result
    def forget(self,tenant,ident):
        _label(tenant); _label(ident)
        with self.store._tx() as db:
            db.execute('DELETE FROM memory_edges WHERE tenant=? AND (src=? OR dst=?)',(tenant,ident,ident))
            return db.execute('DELETE FROM memories WHERE tenant=? AND id=?',(tenant,ident)).rowcount==1
