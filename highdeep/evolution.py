"""Evidence-gated routing policy evolution. No source code or weight mutation."""
from dataclasses import replace
import hashlib
import json
import math
import time
from .core import Request, Router, RouteError
from .jobs import Conflict, _label, _json
from .symbolic import evaluate, verify_answer

def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()

def _config(backends):
    bs=Router(backends).backends
    if not 1<=len(bs)<=64: raise ValueError('Expected 1–64 backends')
    rows=[dict(vars(b),capabilities=sorted(b.capabilities)) for b in sorted(bs,key=lambda b:b.name)]
    return bs,_digest(rows)

def apply_policy(backends,policy):
    bs,_=_config(backends)
    if not isinstance(policy,list) or any(not isinstance(x,str) for x in policy) or len(policy)!=len(bs) or set(policy)!={b.name for b in bs}:
        raise ValueError('Policy must be a permutation of backend names')
    ranks={name:i for i,name in enumerate(policy)}
    return [replace(b,priority=ranks[b.name]) for b in bs]

def compare(backends,baseline,candidate,cases):
    bs,config=_config(backends)
    old=Router(apply_policy(bs,baseline)); new=Router(apply_policy(bs,candidate))
    if not isinstance(cases,list) or not 4<=len(cases)<=1024:
        raise ValueError('Expected 4–1024 paired replay cases')
    seen=set(); normalized=[]
    old_ms=[]; new_ms=[]; old_good=new_good=regressions=0
    for case in cases:
        if not isinstance(case,dict) or set(case)!={'id','capability','max_tokens','observations'}:
            raise ValueError('Invalid replay case')
        ident=case['id']; _label(ident)
        if ident in seen: raise ValueError('Duplicate case')
        seen.add(ident)
        cap=case['capability']
        if not isinstance(cap,str) or cap not in ('chat','code','math','reasoning'):
            raise ValueError('Unsupported replay capability')
        request=Request(cap,'replay',case['max_tokens'])
        names={b.name for b in bs if cap in b.capabilities and request.max_tokens<=b.max_tokens}
        obs=case['observations']
        if not isinstance(obs,dict) or set(obs)!=names: raise ValueError('Incomplete paired observations')
        for v in obs.values():
            if not isinstance(v,dict) or set(v)!={'correct','latency_ms'} or type(v['correct']) is not bool or type(v['latency_ms']) not in (int,float) or not 0<v['latency_ms']<=3600000 or not math.isfinite(v['latency_ms']):
                raise ValueError('Invalid replay observation')
        try: a=obs[old.choose(request).name]; b=obs[new.choose(request).name]
        except RouteError as exc: raise ValueError('Unroutable replay case') from exc
        old_good+=int(a['correct']); new_good+=int(b['correct'])
        regressions+=int(a['correct'] and not b['correct'])
        if a['correct'] and b['correct']:
            old_ms.append(a['latency_ms']); new_ms.append(b['latency_ms'])
        normalized.append(case)
    def p95(vals): return sorted(vals)[math.ceil(0.95*len(vals))-1]
    gain=(sum(old_ms)-sum(new_ms))/sum(old_ms) if old_ms else 0.0
    accepted=regressions==0 and len(old_ms)>=4 and gain>=0.05 and p95(new_ms)<=p95(old_ms)*1.05
    return {'accepted':accepted,'cases':len(cases),'baseline_correct':old_good,'candidate_correct':new_good,
            'correctness_regressions':regressions,'mean_latency_gain':gain,
            'paired_correct_cases':len(old_ms),'baseline_p95_ms':p95(old_ms) if old_ms else None,'candidate_p95_ms':p95(new_ms) if new_ms else None,
            'dataset_sha256':_digest(sorted(normalized,key=lambda x:x['id'])),
            'case_set_sha256':_digest(sorted([{k:x[k] for k in ('id','capability','max_tokens')} for x in normalized],key=lambda x:x['id'])),
            'config_sha256':config}

class EvolutionEngine:
    def __init__(self,store):
        self.store=store
        with store._tx() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS evolution_events (
                tenant TEXT NOT NULL, seq INTEGER NOT NULL, previous TEXT NOT NULL,
                body TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(tenant,seq))""")
    @staticmethod
    def _read(db,tenant):
        rows=db.execute('SELECT * FROM evolution_events WHERE tenant=? ORDER BY seq',(tenant,)).fetchall()
        previous='0'*64; active=None; used=set(); config=None
        for i,row in enumerate(rows):
            try:
                body=json.loads(row['body'])
                digest=_digest({'tenant':tenant,'seq':i,'previous':previous,'body':body})
                if row['seq']!=i or row['previous']!=previous or row['digest']!=digest:
                    raise Conflict('Invalid evolution ledger')
                if i==0:
                    if body['event']!='initialize': raise Conflict('Invalid genesis')
                    active=body['policy']; config=body['config_sha256']
                else:
                    if body['event']!='evaluate' or body['baseline']!=active or body['report']['config_sha256']!=config:
                        raise Conflict('Invalid evolution transition')
                    dataset=body['report']['case_set_sha256']
                    if dataset in used: raise Conflict('Replay dataset already recorded')
                    used.add(dataset)
                    if body['report']['accepted']: active=body['candidate']
                previous=digest
            except (ValueError,KeyError,TypeError) as exc:
                raise Conflict('Invalid evolution ledger') from exc
        return None if not rows else {'head':previous,'policy':active,'config_sha256':config,'events':len(rows),'used':used}
    @staticmethod
    def _append(db,tenant,seq,previous,body):
        digest=_digest({'tenant':tenant,'seq':seq,'previous':previous,'body':body})
        db.execute('INSERT INTO evolution_events VALUES(?,?,?,?,?)',(tenant,seq,previous,_json(body),digest))
        return digest
    @staticmethod
    def _public(state):
        return None if state is None else {k:v for k,v in state.items() if k!='used'}
    def initialize(self,tenant,backends):
        _label(tenant); bs,config=_config(backends)
        with self.store._tx() as db:
            state=self._read(db,tenant)
            if state:
                if state['config_sha256']!=config: raise Conflict('Backend configuration changed')
                return self._public(state)
            policy=[b.name for b in sorted(bs,key=lambda b:(b.priority,b.name))]
            digest=self._append(db,tenant,0,'0'*64,{'event':'initialize','policy':policy,'config_sha256':config})
            return {'head':digest,'policy':policy,'config_sha256':config,'events':1}
    def active(self,tenant):
        _label(tenant)
        with self.store._tx() as db: return self._public(self._read(db,tenant))
    def runtime_backends(self,tenant,backends):
        bs,config=_config(backends)
        state=self.active(tenant)
        if state is None or state['config_sha256']!=config:
            raise Conflict('No active policy for this configuration')
        return apply_policy(bs,state['policy'])
    def promote(self,tenant,backends,candidate,cases,*,expected):
        _label(tenant); bs,config=_config(backends)
        with self.store._tx() as db:
            state=self._read(db,tenant)
            if state is None or state['head']!=expected or state['config_sha256']!=config:
                raise Conflict('Stale head or backend configuration changed')
            if state['events']>=1024: raise ValueError('Evolution ledger quota exhausted')
            report=compare(bs,state['policy'],candidate,cases)
            if report['case_set_sha256'] in state['used']:
                raise Conflict('Replay dataset already evaluated')
            body={'event':'evaluate','baseline':state['policy'],'candidate':candidate,'report':report}
            head=self._append(db,tenant,state['events'],state['head'],body)
            return dict(report,head=head,policy=candidate if report['accepted'] else state['policy'])
    def verify(self,tenant):
        try: return self.active(tenant) is not None
        except Conflict: return False

def collect_replay(backends,tasks,adapter,*,clock=time.perf_counter):
    """Collect observed wall-clock latency and checked correctness, never fabricate samples."""
    bs,_=_config(backends)
    if not isinstance(tasks,list) or not 4<=len(tasks)<=1024:
        raise ValueError('Expected 4–1024 tasks')
    prepared=[]; seen=set(); calls=0
    # Validate all inputs before any external inference.
    for task in tasks:
        if not isinstance(task,dict):
            raise ValueError('Invalid task')
        required={'id','capability','max_tokens','prompt'}
        if not required<=task.keys() or set(task)-required not in ({'expected'},{'rational_expected'}):
            raise ValueError('Exactly one trusted expected-answer gate required')
        _label(task['id'])
        if task['id'] in seen: raise ValueError('Duplicate task')
        seen.add(task['id'])
        req=Request(task['capability'],task['prompt'],task['max_tokens'])
        if req.capability not in ('chat','code','math','reasoning'):
            raise ValueError('Unsupported task capability')
        if 'rational_expected' in task: evaluate(task['rational_expected'])
        elif not isinstance(task['expected'],str) or len(task['expected'].encode())>65536:
            raise ValueError('Invalid expected answer')
        eligible=[b for b in sorted(bs,key=lambda x:x.name) if req.capability in b.capabilities and req.max_tokens<=b.max_tokens]
        if not eligible: raise ValueError('Unroutable task')
        calls+=len(eligible)
        prepared.append((task,req,eligible))
    if calls>2048: raise ValueError('Evaluation exceeds inference-call budget')
    output=[]
    for index,(task,req,eligible) in enumerate(prepared):
        obs={}
        # Alternate order to reduce systematic warm-up/order bias.
        for b in eligible if index%2==0 else reversed(eligible):
            start=clock()
            try:
                answer=adapter.execute(b,req)
                correct=verify_answer(answer,task['rational_expected']) if 'rational_expected' in task else answer==task['expected']
            except RouteError:
                correct=False
            elapsed=max(0.000001,(clock()-start)*1000)
            obs[b.name]={'correct':correct,'latency_ms':elapsed}
        output.append(dict(id=task['id'],capability=req.capability,max_tokens=req.max_tokens,observations=obs))
    return output
