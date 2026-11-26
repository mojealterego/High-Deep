import argparse, json, sys, time
from pathlib import Path
from .core import Backend, Registry, Request, Router, HttpAdapter, RouteError
from .jobs import JobStore, Conflict
from .worker import Worker
from .workflows import WorkflowEngine

def load_router(path):
    rows=json.loads(path.read_text())
    return Router([Backend(**dict(row,capabilities=frozenset(row['capabilities']))) for row in rows])

def main():
    p = argparse.ArgumentParser(prog='highdeep')
    subs = p.add_subparsers(dest='command',required=True)
    inv = subs.add_parser('inventory')
    inv.add_argument('--file',type=Path,default=Path('inventory.json'))
    for name in ('run','submit'):
        cmd=subs.add_parser(name)
        cmd.add_argument('--capability',default='chat',choices=['chat','code','math','reasoning'])
        cmd.add_argument('--max-tokens',type=int,default=256)
        cmd.add_argument('prompt')
        if name=='run':
            cmd.add_argument('--config',type=Path,required=True)
        else:
            cmd.add_argument('--db',type=Path,required=True)
            cmd.add_argument('--tenant',required=True)
            cmd.add_argument('--key',required=True)
    for name in ('work','status'):
        cmd=subs.add_parser(name)
        cmd.add_argument('--db',type=Path,required=True)
        cmd.add_argument('--tenant',required=True)
        if name=='work':
            cmd.add_argument('--config',type=Path,required=True)
            cmd.add_argument('--worker',required=True)
        else:
            cmd.add_argument('job')
    for name in ('flow-submit','flow-tick','flow-status'):
        cmd=subs.add_parser(name)
        cmd.add_argument('--db',type=Path,required=True)
        cmd.add_argument('--tenant',required=True)
        if name=='flow-submit':
            cmd.add_argument('--key',required=True)
            cmd.add_argument('--budget',type=int,required=True)
            cmd.add_argument('--plan',type=Path,required=True)
        else:
            cmd.add_argument('workflow')
    args=p.parse_args()
    try:
        if args.command=='inventory':
            print(json.dumps(Registry.load(args.file).rows,indent=2))
        elif args.command=='run':
            request=Request(args.capability,args.prompt,args.max_tokens)
            backend=load_router(args.config).choose(request)
            print(HttpAdapter().execute(backend,request))
        elif args.command=='submit':
            request=Request(args.capability,args.prompt,args.max_tokens)
            print(JobStore(args.db).submit(args.tenant,args.key,vars(request),now=time.time()))
        elif args.command=='work':
            job=Worker(JobStore(args.db),load_router(args.config),HttpAdapter()).run_once(args.tenant,args.worker)
            print(json.dumps({'job':job}))
        elif args.command.startswith('flow-'):
            engine=WorkflowEngine(JobStore(args.db))
            if args.command=='flow-submit':
                if args.plan.stat().st_size > 1024*1024:
                    raise ValueError('Plan exceeds size limit')
                steps=json.loads(args.plan.read_text(encoding='utf-8'))
                print(engine.create(args.tenant,args.key,steps,token_budget=args.budget,now=time.time()))
            else:
                flow=engine.advance(args.tenant,args.workflow,now=time.time()) if args.command=='flow-tick' else engine.status(args.tenant,args.workflow)
                if flow is None:
                    raise ValueError('Unknown workflow')
                print(json.dumps(flow,indent=2))
        else:
            job=JobStore(args.db).get(args.tenant,args.job)
            if job is None:
                raise ValueError('Unknown job')
            print(json.dumps({k:v for k,v in job.items() if k not in ('lease','idem')},indent=2))
        return 0
    except (ValueError,KeyError,TypeError,OSError,RouteError,Conflict) as exc:
        print(str(exc),file=sys.stderr)
        return 1
if __name__=='__main__':
    sys.exit(main())
