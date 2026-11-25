"""One bounded, durable inference job per worker invocation."""
import time
from .core import Request, RouteError

class Worker:
    def __init__(self, store, router, adapter, *, clock=time.time, lease_seconds=180):
        self.store, self.router, self.adapter = store, router, adapter
        self.clock, self.lease_seconds = clock, lease_seconds

    def run_once(self, tenant, worker):
        job = self.store.claim(tenant,worker,now=self.clock(),lease_seconds=self.lease_seconds)
        if job is None:
            return None
        try:
            req = Request(**job['payload'])
            backend = self.router.choose(req)
            content = self.adapter.execute(backend,req)
        except (ValueError,TypeError,RouteError):
            self.store.fail(tenant,job['id'],job['lease'],now=self.clock())
        else:
            self.store.complete(tenant,job['id'],job['lease'],
                                {'backend':backend.name,'content':content},now=self.clock())
        return job['id']
