"""
MATLAB MCP Server 连接测试脚本
================================
在 Mac 端运行，测试与 Windows 端 MCP Server 的 Streamable HTTP 连接。

用法:
    python test_connection.py [BASE_URL] [--token <MCP_TOKEN>]

参数:
    BASE_URL    服务器地址，默认 http://localhost:8080。
                 若未以 /mcp 或 /sse 结尾，自动追加 /mcp。
    --token     可选 Bearer token（对应服务器 MCP_TOKEN）。

示例:
    python test_connection.py http://192.168.1.100:8080        # 局域网
    python test_connection.py http://100.x.y.z:8080 --token xxx # Tailscale + 认证

实现: 使用标准库 urllib.request，无第三方依赖。
握手流程: 1) GET /health 连通性 → 2) POST /mcp initialize → 3) POST notifications/initialized
"""

import argparse
import json
import sys
import urllib.request
import urllib.error


def get(url: str, token: str = "", timeout: int = 15):
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, dict(resp.headers), resp.read().decode(errors="replace")


def post(url: str, payload: dict, token: str = "", timeout: int = 15):
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    body = json.dumps(payload, ensure_ascii=False).encode()
    with urllib.request.urlopen(req, data=body, timeout=timeout) as resp:
        return resp.status, dict(resp.headers), resp.read().decode(errors="replace")


def _client_info():
    return {"protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test-connection", "version": "1.0.0"}}


def test_connection(base: str, token: str = "") -> bool:
    base = base.rstrip("/")
    # 端点推断：/mcp 为 Streamable HTTP，/sse 向后兼容
    if base.endswith("/mcp") or base.endswith("/sse"):
        endpoint = base
        server_root = base[: base.rfind("/")]
    else:
        endpoint = f"{base}/mcp"
        server_root = base
    print(f"服务器: {base}")
    print(f"端点: {endpoint}")
    print(f"认证: {'已启用 (Bearer ' + token[:4] + '...)' if token else '未启用'}")
    print("-" * 50)

    ok = True

    # 1) HTTP 连通性（/health 为白名单，无需 token）
    print("[1/4] HTTP 连通性 (GET /health)...")
    try:
        status, _, _ = get(f"{server_root}/health", token="", timeout=5)
        if status == 200:
            print(f"  ✓ /health 可达 (HTTP {status})")
        else:
            print(f"  ✗ /health 返回 HTTP {status}")
            ok = False
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        print(f"  ✗ 连接失败: {e}")
        print("    检查: 服务是否启动 / 防火墙放行 / Tailscale 连接 / 地址端口")
        return False

    # 2) MCP initialize 握手（真实 JSON-RPC）
    print("[2/4] MCP initialize 握手...")
    init_payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": _client_info()}
    try:
        status, headers, body = post(endpoint, init_payload, token=token)
        print(f"  HTTP {status} | Content-Type: {headers.get('Content-Type', '?')}")
        if status not in (200, 202):
            print(f"  ✗ 握手 HTTP 异常: {body[:300]}")
            ok = False
        else:
            found_id = '"id": 1' in body or '"id":1' in body
            found_result = '"result"' in body or '"capabilities"' in body
            print(f"  ✓ 收到 JSON-RPC 响应" if found_id or found_result else f"  ✗ 响应缺少 result: {body[:300]}")
            if not (found_id or found_result):
                ok = False
    except urllib.error.HTTPError as e:
        print(f"  ✗ 握手 HTTP {e.code}")
        if e.code == 401:
            print("    → 认证被拒，请检查 --token 是否与服务器 MCP_TOKEN 一致")
        ok = False
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        print(f"  ✗ 握手连接异常: {e}")
        ok = False

    # 3) notifications/initialized 通知
    print("[3/4] 发送 notifications/initialized...")
    notif_payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    try:
        status, _, _ = post(endpoint, notif_payload, token=token)
        # 通知通常无响应体（202/204）；即便非 200 只要未抛错即可视为已送达
        print(f"  ✓ 通知已发送 (HTTP {status})")
    except urllib.error.HTTPError as e:
        print(f"  ⚠ 通知异常 HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
        ok = False
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        print(f"  ⚠ 通知发送异常: {e}")
        ok = False

    # 4) 总结与客户端配置示例
    print("[4/4] 总结")
    print("-" * 50)
    print(f"  服务地址: {endpoint}")
    print(f"  传输: Streamable HTTP")
    ok_str = "EVERYTHING_OK" if ok else "WITH_ISSUES"
    print(f"  结果: {ok_str}")
    print()
    print("  Qoder MCP 配置 (type=http):")
    token_field = f'\n        "Authorization": "Bearer {token}"' if token else ""
    print(f'  {{"mcpServers": {{"matlab": {{"type": "http", "url": "{endpoint}",\n        "headers": {{{token_field}\n        }}}}}}')  # noqa: E501
    print()
    return ok


def main():
    parser = argparse.ArgumentParser(description="MATLAB MCP Server 连接测试 (Streamable HTTP)")
    parser.add_argument("url", nargs="?", default="http://localhost:8080",
                        help="服务器地址 (默认 http://localhost:8080)")
    parser.add_argument("--token", default="", help="Bearer token (对应 MCP_TOKEN)")
    args = parser.parse_args()

    result = test_connection(args.url, args.token)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()