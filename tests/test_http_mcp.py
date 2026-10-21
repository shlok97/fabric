import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from fabric.web import make_server


@pytest.fixture
def http(demo):
    store, keys, _ = demo
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", keys
    server.shutdown()
    server.server_close()
    thread.join()


def request(base, key="", operation="status", arguments=None, headers=None, raw=None):
    body = raw if raw is not None else json.dumps({"operation": operation, "arguments": arguments or {}}).encode()
    h = {"Content-Type": "application/json", "Authorization": "Bearer " + key, **(headers or {})}
    try:
        with urlopen(Request(base+"/api/call", data=body, headers=h), timeout=5) as r:
            return r.status, json.load(r), r.headers
    except HTTPError as e:
        return e.code, json.load(e), e.headers


def test_http_missing_auth_and_valid_auth(http):
    base, keys = http
    assert request(base)[0] == 401
    status, data, headers = request(base, keys["alice"])
    assert status == 200 and data["identity"]["tenant"] == "paper-kite"
    assert headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": "null"}, {"Host": "evil.example"}])
def test_cross_origin_and_rebinding_denied(http, headers):
    base, keys = http
    assert request(base, keys["alice"], headers=headers)[0] == 403


@pytest.mark.parametrize("body", [b"[]", b"null", b"{", b"x"*17000,
                                  b'{"operation":"status","tenant":"cedar-house"}',
                                  b'{"operation": [], "arguments":{}}'])
def test_http_bad_payloads(http, body):
    base, keys = http
    assert request(base, keys["alice"], raw=body)[0] == 400


def test_http_identity_controls_numeric_read(http):
    base, keys = http
    args = {"descriptor_id": "kite.estimate", "subjects": ["NORTHSTAR"], "period": "FY2026", "basis": "consolidated"}
    assert request(base, keys["alice"], "read", args)[1]["items"][0]["row"]["value"] == 110
    assert request(base, keys["chandra"], "read", args)[0] == 404


def test_http_static_assets_do_not_contain_private_content_or_credentials(http):
    base, keys = http
    for asset in ("/", "/app.js", "/style.css", "/health"):
        with urlopen(base + asset) as r:
            raw = r.read().decode()
            assert r.status == 200
            for secret in (*keys.values(), "KITE-MARIGOLD-741", "CEDAR-SAFFRON-963"):
                assert secret not in raw


def test_real_stdio_mcp_transport_and_live_revocation(demo):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    store, keys, _ = demo

    async def scenario():
        env = {**os.environ, "FABRIC_TOKEN": keys["alice"]}
        params = StdioServerParameters(command=sys.executable,
                                      args=["-m", "fabric", "--db", str(store.path), "mcp"], env=env,
                                      cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert len(tools) == 5
                for tool in tools:
                    assert not {"tenant", "workspace", "owner", "token", "sql"}.intersection(tool.inputSchema.get("properties", {}))
                result = await session.call_tool("fabric_search", {"query": "Northstar MARIGOLD"})
                payload = json.loads(result.content[0].text)
                assert "KITE-MARIGOLD-741" in json.dumps(payload)
                assert "CEDAR-SAFFRON-963" not in json.dumps(payload)
                with store.connect() as db:
                    db.execute("UPDATE principals SET active=0 WHERE id='alice'")
                revoked = await session.call_tool("fabric_status", {})
                assert json.loads(revoked.content[0].text)["error"]["code"] == "unauthorized"

    asyncio.run(scenario())
