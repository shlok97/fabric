#!/usr/bin/env python3
"""Find an installed Python 3.11+, seed fictional data and serve. No downloads."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
if sys.version_info < (3, 11):
    candidates = [shutil.which("python3.13"), shutil.which("python3.12"), shutil.which("python3.11")]
    candidates += [str(p) for p in (Path.home() / ".local/share/uv/python").glob("cpython-3.1*-*/bin/python3.1*") if p.is_file()]
    for candidate in candidates:
        if candidate and subprocess.run([candidate, "-c", "import sys; sys.exit(sys.version_info < (3,11))"], capture_output=True).returncode == 0:
            os.execv(candidate, [candidate, str(Path(__file__).resolve()), *sys.argv[1:]])
    raise SystemExit("Fabric needs Python 3.11+. Install it, then rerun this script.")
sys.path.insert(0, str(root))
from fabric.demo import create_demo
from fabric.web import make_server

store, credentials = create_demo(root / "data/demo")
print("Fictional demo credentials — paste one into the local dashboard:", flush=True)
for name, token in credentials.items():
    print(f"  {name}: {token}", flush=True)
port = int(sys.argv[1]) if len(sys.argv) > 1 else 4790
server = make_server(store, port)
print(f"Fabric · http://127.0.0.1:{server.server_port} · Ctrl+C to stop", flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
