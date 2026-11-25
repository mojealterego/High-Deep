import argparse, json, sys
from pathlib import Path
from .core import Backend, Registry, Request, Router, HttpAdapter, RouteError

def main():
    p = argparse.ArgumentParser(prog='highdeep')
    subs = p.add_subparsers(dest='command',required=True)
    inv = subs.add_parser('inventory')
    inv.add_argument('--file',type=Path,default=Path('inventory.json'))
    chat = subs.add_parser('run')
    chat.add_argument('--config',type=Path,required=True)
    chat.add_argument('--capability',default='chat',choices=['chat','code','math','reasoning'])
    chat.add_argument('--max-tokens',type=int,default=256)
    chat.add_argument('prompt')
    args=p.parse_args()
    try:
        if args.command=='inventory':
            print(json.dumps(Registry.load(args.file).rows,indent=2))
        else:
            rows=json.loads(args.config.read_text())
            backends=[Backend(**dict(row,capabilities=frozenset(row['capabilities']))) for row in rows]
            request=Request(args.capability,args.prompt,args.max_tokens)
            backend=Router(backends).choose(request)
            print(HttpAdapter().execute(backend,request))
        return 0
    except (ValueError,KeyError,TypeError,OSError,RouteError) as exc:
        print(str(exc),file=sys.stderr)
        return 1
if __name__=='__main__':
    sys.exit(main())
