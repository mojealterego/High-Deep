"""Thread-safe process-local routing and circuit breaker; no automatic replay."""
from dataclasses import dataclass
import math
import threading
import time
from .core import RouteError, Router

@dataclass
class _State:
    state: str = 'closed'
    epoch: int = 0
    opened_at: float = 0.0
    inflight: int = 0
    failures: int = 0
    successes: int = 0
    consecutive_failures: int = 0
    ewma_ms: float | None = None

class AdaptiveExecutor:
    def __init__(self, backends, adapter, *, max_inflight=2, failure_threshold=3,
                 cooldown=30.0, clock=time.monotonic):
        self.backends=Router(backends).backends
        if type(max_inflight) is not int or not 1 <= max_inflight <= 128:
            raise ValueError('Invalid concurrency limit')
        if type(failure_threshold) is not int or not 1 <= failure_threshold <= 100:
            raise ValueError('Invalid failure threshold')
        if not isinstance(cooldown,(int,float)) or not math.isfinite(cooldown) or not 0 < cooldown <= 3600:
            raise ValueError('Invalid cooldown')
        self.adapter=adapter
        self.max_inflight=max_inflight
        self.failure_threshold=failure_threshold
        self.cooldown=cooldown
        self.clock=clock
        self._lock=threading.Lock()
        self._states={b.name:_State() for b in self.backends}

    def _reserve(self, request):
        if request.capability not in ('chat','code','math','reasoning'):
            raise RouteError('Unsupported text modality')
        with self._lock:
            now=self.clock()
            candidates=[]
            for b in self.backends:
                s=self._states[b.name]
                if request.capability not in b.capabilities or request.max_tokens > b.max_tokens:
                    continue
                if s.inflight >= self.max_inflight or s.state=='half_open':
                    continue
                if s.state=='open' and (now-s.opened_at < self.cooldown or s.inflight):
                    continue
                candidates.append(b)
            if not candidates:
                raise RouteError('No eligible backend has available capacity')
            def rank(b):
                s=self._states[b.name]
                return (b.priority,s.inflight,s.ewma_ms if s.ewma_ms is not None else 0,b.name)
            b=min(candidates,key=rank)
            s=self._states[b.name]
            if s.state=='open':
                s.state='half_open'
            s.inflight+=1
            return b,s.epoch,now

    def _finish(self,b,epoch,started,success):
        with self._lock:
            s=self._states[b.name]
            s.inflight-=1
            elapsed=max(0.0,(self.clock()-started)*1000)
            if success:
                s.successes+=1
                s.ewma_ms=elapsed if s.ewma_ms is None else 0.2*elapsed+0.8*s.ewma_ms
            else:
                s.failures+=1
            # An older in-flight completion cannot reverse a newer circuit transition.
            if epoch!=s.epoch:
                return
            if success:
                s.state='closed'
                s.consecutive_failures=0
            else:
                s.consecutive_failures+=1
                if s.state=='half_open' or s.consecutive_failures>=self.failure_threshold:
                    s.state='open'
                    s.epoch+=1
                    s.opened_at=self.clock()

    def execute(self,request):
        b,epoch,started=self._reserve(request)
        success=False
        try:
            content=self.adapter.execute(b,request)
            if not isinstance(content,str):
                raise RouteError('Invalid backend content')
            success=True
            return b.name,content
        finally:
            self._finish(b,epoch,started,success)

    def metrics(self):
        with self._lock:
            return {name:{'state':s.state,'inflight':s.inflight,'successes':s.successes,
                          'failures':s.failures,'consecutive_failures':s.consecutive_failures,
                          'ewma_ms':None if s.ewma_ms is None else round(s.ewma_ms,3)}
                    for name,s in sorted(self._states.items())}
