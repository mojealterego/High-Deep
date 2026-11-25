"""High-Deep control plane; native model runtimes remain separate processes."""
from dataclasses import dataclass
from pathlib import Path
import http.client
import json
import os
import re
from urllib.parse import urlsplit

class RouteError(RuntimeError):
    pass

@dataclass(frozen=True)
class Registry:
    rows: tuple
    @classmethod
    def load(cls, path: Path):
        rows = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(rows, list) or len(rows) != 47:
            raise ValueError('Expected 47 upstream records')
        seen = set()
        for row in rows:
            name = row['name']
            if not re.fullmatch(r'[A-Za-z0-9._-]+',name) or name in ('.','..') or name.casefold() in seen:
                raise ValueError('Invalid or duplicate repository')
            if not re.fullmatch(r'[0-9a-f]{40}',row['commit']) or not re.fullmatch(r'[0-9a-f]{64}',row['sha256']):
                raise ValueError('Invalid provenance')
            if row['files'] <= 0 or row['bytes'] <= 0:
                raise ValueError('Invalid source inventory')
            seen.add(name.casefold())
        return cls(tuple(rows))

@dataclass(frozen=True)
class Backend:
    name: str
    hardware: str
    capabilities: frozenset
    endpoint: str
    model: str
    max_tokens: int
    priority: int
    token_env: str = ''
    def __post_init__(self):
        p = urlsplit(self.endpoint)
        if (p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in ('127.0.0.1','::1'))) or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/'):
            raise ValueError('Configure HTTPS or explicit loopback HTTP origin')
        if not self.name or not self.model or self.hardware not in ('cpu','cuda','ascend','remote') or not self.capabilities or type(self.max_tokens) is not int or self.max_tokens < 1 or type(self.priority) is not int:
            raise ValueError('Invalid backend')
        if self.token_env and not re.fullmatch(r'[A-Z_][A-Z0-9_]*', self.token_env):
            raise ValueError('Invalid token environment variable')
        _ = p.port

@dataclass(frozen=True)
class Request:
    capability: str
    prompt: str
    max_tokens: int
    def __post_init__(self):
        if not self.capability or not isinstance(self.prompt,str) or not self.prompt.strip() or len(self.prompt.encode('utf-8')) > 262144 or type(self.max_tokens) is not int or not 1 <= self.max_tokens <= 131072:
            raise ValueError('Invalid request')

class Router:
    def __init__(self, backends):
        self.backends = tuple(backends)
        if len({b.name for b in self.backends}) != len(self.backends):
            raise ValueError('Duplicate backend')
    def choose(self, request: Request):
        available = [b for b in self.backends if request.capability in b.capabilities and request.max_tokens <= b.max_tokens]
        if not available:
            raise RouteError('No configured backend satisfies capability and token budget')
        return min(available, key=lambda b:(b.priority,b.name))

class HttpAdapter:
    def __init__(self, timeout=30, max_response=2*1024*1024):
        if not 0 < timeout <= 120 or not 1 <= max_response <= 16*1024*1024:
            raise ValueError('Invalid transport limits')
        self.timeout, self.max_response = timeout, max_response
    def execute(self, backend: Backend, request: Request):
        if request.capability not in backend.capabilities or request.max_tokens > backend.max_tokens:
            raise RouteError('Backend capability or budget mismatch')
        if request.capability not in ('chat','code','math','reasoning'):
            raise RouteError('Text adapter does not support this modality')
        p = urlsplit(backend.endpoint)
        transport = http.client.HTTPSConnection if p.scheme == 'https' else http.client.HTTPConnection
        headers = {'Content-Type':'application/json','Accept':'application/json'}
        if backend.token_env:
            token = os.environ.get(backend.token_env)
            if not token:
                raise RouteError('Backend credential unavailable')
            headers['Authorization'] = 'Bearer '+token
        payload = json.dumps({'model':backend.model,'messages':[{'role':'user','content':request.prompt}],'max_tokens':request.max_tokens,'stream':False}).encode()
        conn = transport(p.hostname, p.port, timeout=self.timeout)
        try:
            conn.request('POST','/v1/chat/completions',body=payload,headers=headers)
            with conn.getresponse() as response:
                if response.status != 200:
                    raise RouteError('Backend HTTP status '+str(response.status))
                raw = response.read(self.max_response+1)
                if len(raw) > self.max_response:
                    raise RouteError('Backend response exceeds configured limit')
                result = json.loads(raw)['choices'][0]['message']['content']
                if not isinstance(result,str):
                    raise RouteError('Invalid backend result')
                return result
        except (OSError, http.client.HTTPException, ValueError, KeyError, IndexError, TypeError) as exc:
            raise RouteError('Backend protocol or transport failure') from exc
        finally:
            conn.close()
