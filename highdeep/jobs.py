"""Durable single-host job queue with tenant scoping and fenced leases."""
from contextlib import contextmanager
import json
import math
import sqlite3
import uuid

class Conflict(RuntimeError):
    pass

def _json(value):
    encoded = json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
    if len(encoded.encode()) > 1024*1024:
        raise ValueError('Payload exceeds limit')
    return encoded

def _label(value):
    if not isinstance(value,str) or not 1 <= len(value) <= 256 or not value.strip():
        raise ValueError('Invalid identifier')

def _time(now):
    if not isinstance(now,(int,float)) or not math.isfinite(now) or now < 0:
        raise ValueError('Invalid time')

class JobStore:
    def __init__(self,path):
        self.path=str(path)
        with self._tx() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, idem TEXT NOT NULL,
                payload TEXT NOT NULL, result TEXT, state TEXT NOT NULL,
                created REAL NOT NULL, available REAL NOT NULL, lease TEXT,
                expires REAL, worker TEXT, attempts INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL, UNIQUE(tenant,idem),
                CHECK(state IN ('queued','running','succeeded','failed')))""")
            db.execute('CREATE INDEX IF NOT EXISTS jobs_poll ON jobs(tenant,state,available,created,id)')
    @contextmanager
    def _tx(self):
        db=sqlite3.connect(self.path,timeout=5,isolation_level=None)
        db.row_factory=sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
    def submit(self,tenant,key,payload,*,now,max_attempts=3):
        _label(tenant); _label(key); _time(now)
        if key.startswith('workflow:'):
            raise ValueError('Reserved job key namespace')
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
            raise ValueError('Invalid retry budget')
        value=_json(payload)
        with self._tx() as db:
            row=db.execute('SELECT id,payload,max_attempts FROM jobs WHERE tenant=? AND idem=?',(tenant,key)).fetchone()
            if row:
                if row['payload'] != value or row['max_attempts'] != max_attempts:
                    raise Conflict('Idempotency key reused with different request')
                return row['id']
            job=uuid.uuid4().hex
            db.execute("INSERT INTO jobs(id,tenant,idem,payload,state,created,available,attempts,max_attempts) VALUES(?,?,?,?,'queued',?,?,0,?)",(job,tenant,key,value,now,now,max_attempts))
            return job
    def get(self,tenant,job):
        _label(tenant); _label(job)
        with self._tx() as db:
            r=db.execute('SELECT * FROM jobs WHERE tenant=? AND id=?',(tenant,job)).fetchone()
            return self._decode(r)
    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result=dict(row)
        for field in ('payload','result'):
            if result[field] is not None:
                result[field]=json.loads(result[field])
        return result
    def claim(self,tenant,worker,*,now,lease_seconds):
        _label(tenant); _label(worker); _time(now)
        if not isinstance(lease_seconds,(int,float)) or not math.isfinite(lease_seconds) or not 1 <= lease_seconds <= 3600:
            raise ValueError('Invalid lease duration')
        with self._tx() as db:
            db.execute("""UPDATE jobs SET state=CASE WHEN attempts>=max_attempts THEN 'failed' ELSE 'queued' END,
                         available=?,lease=NULL,expires=NULL,worker=NULL
                         WHERE tenant=? AND state='running' AND expires<=?""",(now,tenant,now))
            row=db.execute("SELECT id FROM jobs WHERE tenant=? AND state='queued' AND available<=? AND attempts<max_attempts ORDER BY created,id LIMIT 1",(tenant,now)).fetchone()
            if row is None:
                return None
            lease=uuid.uuid4().hex
            db.execute("UPDATE jobs SET state='running',lease=?,expires=?,worker=?,attempts=attempts+1 WHERE tenant=? AND id=?",(lease,now+lease_seconds,worker,tenant,row['id']))
            return self._decode(db.execute('SELECT * FROM jobs WHERE tenant=? AND id=?',(tenant,row['id'])).fetchone())
    def complete(self,tenant,job,lease,result,*,now):
        self._finish(tenant,job,lease,'succeeded',_json(result),now)
    def fail(self,tenant,job,lease,*,now):
        self._finish(tenant,job,lease,'failed',None,now)
    def _finish(self,tenant,job,lease,state,result,now):
        _label(tenant); _label(job); _label(lease); _time(now)
        with self._tx() as db:
            updated=db.execute("""UPDATE jobs SET state=?,result=?,lease=NULL,expires=NULL,worker=NULL
                WHERE tenant=? AND id=? AND state='running' AND lease=? AND expires>?""",(state,result,tenant,job,lease,now))
            if updated.rowcount != 1:
                raise Conflict('Lease expired, superseded or unknown job')
