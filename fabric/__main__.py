import argparse
import json
import os
import sys
import time
from pathlib import Path

from .core import FabricError, Store, canonical
from .demo import create_demo
from .sources import provision, sync_folder


def main(argv=None):
    p = argparse.ArgumentParser(description="Fabric local evidence gateway")
    p.add_argument("--db", default="data/demo/fabric.db", help="Local Fabric state, never a source database")
    p.add_argument("--semantic", action="store_true", help="Enable local semantic/hybrid reads with already downloaded weights")
    p.add_argument("--model-cache", default="data/models/bge-small")
    sub = p.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Create fictional sources and credentials; idempotent")
    demo.add_argument("--directory", default="data/demo")
    serve = sub.add_parser("serve", help="Serve the local dashboard and HTTP API")
    serve.add_argument("--port", type=int, default=4790)
    sub.add_parser("mcp", help="Run stdio MCP with FABRIC_TOKEN or FABRIC_TOKEN_FILE")
    embed = sub.add_parser("embed", help="Operator-only: embed changed current document passages locally")
    embed.add_argument("--download-model", action="store_true", help="Explicitly allow downloading model weights; never uploads source text")
    call = sub.add_parser("call", help="Run one authenticated read operation")
    call.add_argument("operation")
    call.add_argument("--arguments", default="{}")
    init = sub.add_parser("init", help="Operator-only bootstrap from a private JSON config")
    init.add_argument("config")
    sync = sub.add_parser("sync", help="Operator-only incremental folder sync")
    sync.add_argument("connection")
    watch = sub.add_parser("watch", help="Poll one configured folder; foreground, no scheduler installation")
    watch.add_argument("connection")
    watch.add_argument("--interval", type=int, default=30)
    revoke = sub.add_parser("revoke", help="Operator-only: revoke a collection grant immediately")
    revoke.add_argument("collection")
    revoke.add_argument("tenant")
    revoke.add_argument("--principal", default="")
    disable = sub.add_parser("disable-principal", help="Operator-only: invalidate a local principal credential")
    disable.add_argument("principal")
    args = p.parse_args(argv)
    try:
        store = Store(args.db)
        if args.command == "demo":
            store, credentials = create_demo(args.directory)
            print(f"Fictional demo ready: {store.path}\nLocal credentials (keep out of Git):")
            for name, token in credentials.items():
                print(f"  {name}: {token}")
            print(f"Run: python -m fabric --db '{store.path}' serve")
            return
        if args.command == "init":
            config_path = Path(args.config).resolve()
            path = store.path.parent / "credentials.json"
            if path.exists():
                raise FabricError("A credentials file already exists beside this state path. Use a separate directory.")
            credentials = provision(store, json.loads(config_path.read_text()))
            with path.open("x") as out:
                path.chmod(0o600)
                out.write(canonical(credentials) + "\n")
            print(f"Credentials written to {path}; no sources synced yet.")
            return
        if not store.path.exists():
            raise FabricError("State does not exist. Run demo or init first.")
        if args.semantic or args.command == "embed":
            from .embeddings import LocalEmbedder
            store.embedder = LocalEmbedder(args.model_cache, getattr(args, "download_model", False))
        if args.command == "embed":
            from .embeddings import index_documents
            print(canonical(index_documents(store, store.embedder)))
            return 0
        if args.command == "serve":
            from .web import make_server
            server = make_server(store, args.port)
            print(f"Fabric · http://127.0.0.1:{server.server_port} · local POC · Ctrl+C to stop", flush=True)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        elif args.command in {"sync", "watch"}:
            if args.command == "watch" and args.interval < 5:
                raise FabricError("Polling interval must be at least five seconds.")
            while True:
                try:
                    print(canonical(sync_folder(store, args.connection)), flush=True)
                except FabricError as e:
                    if args.command != "watch":
                        raise
                    print(canonical({"error": e.code, "message": str(e)}), file=sys.stderr, flush=True)
                if args.command == "sync":
                    break
                time.sleep(args.interval)
        elif args.command in {"revoke", "disable-principal"}:
            with store.connect() as db:
                if args.command == "revoke":
                    changed = db.execute("DELETE FROM grants WHERE collection_id=? AND tenant=? AND principal=?",
                                         (args.collection, args.tenant, args.principal)).rowcount
                else:
                    changed = db.execute("UPDATE principals SET active=0 WHERE id=?", (args.principal,)).rowcount
            print(canonical({"changed": changed}))
        else:
            token = os.environ.get("FABRIC_TOKEN", "")
            if not token and os.environ.get("FABRIC_TOKEN_FILE"):
                token = Path(os.environ["FABRIC_TOKEN_FILE"]).read_text().strip()
            if args.command == "mcp":
                from .mcp_server import create_mcp
                create_mcp(store, token).run(transport="stdio")
            else:
                print(json.dumps(store.execute(token, args.operation, json.loads(args.arguments)), indent=2))
    except (FabricError, OSError, ValueError, KeyError) as e:
        print(f"Fabric: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
