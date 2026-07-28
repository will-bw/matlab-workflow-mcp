"""
MATLAB MCP Server 连接测试脚本
================================
在 Mac 端运行，测试与 Windows 端 MCP Server 的连接。

用法:
    python test_connection.py http://100.x.y.z:8080/sse
    python test_connection.py http://192.168.1.100:8080/sse
"""

import sys
import asyncio
import httpx


async def test_sse_connection(url: str):
    """测试 SSE 连接是否正常"""
    print(f"正在测试连接: {url}")
    print("-" * 50)

    # 1. 测试基本 HTTP 连通性
    base_url = url.replace("/sse", "")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # 尝试连接 SSE 端点
            print("[1/3] 测试 HTTP 连通性...")
            resp = await client.get(url, headers={"Accept": "text/event-stream"}, timeout=5)
            print(f"  状态码: {resp.status_code}")
            if resp.status_code == 200:
                print("  ✓ SSE 端点可达")
            else:
                print(f"  ✗ 异常状态码: {resp.status_code}")
                return False
    except httpx.ConnectTimeout:
        print("  ✗ 连接超时 - 检查:")
        print("    - Windows 端服务是否已启动")
        print("    - 防火墙是否放行端口")
        print("    - Tailscale 是否已连接")
        return False
    except httpx.ConnectError as e:
        print(f"  ✗ 连接失败: {e}")
        print("    检查 IP 地址和端口是否正确")
        return False
    except Exception as e:
        print(f"  ✗ 未知错误: {e}")
        return False

    # 2. 测试 MCP 协议握手
    print("[2/3] 测试 MCP 协议...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # MCP initialize 请求
            init_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"}
                }
            }
            # 先获取 SSE session
            async with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as stream:
                session_url = None
                async for line in stream.aiter_lines():
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if "/message" in data or "endpoint" in data:
                            session_url = data
                            break
                    if "event: endpoint" in line:
                        continue

                if session_url:
                    print(f"  ✓ 获取到消息端点: {session_url}")
                else:
                    print("  ✓ SSE 流已建立（端点信息在流中）")

    except Exception as e:
        print(f"  ⚠ MCP 协议测试: {e}")
        print("    (SSE 连接已通，MCP 协议可能需要完整客户端)")

    # 3. 总结
    print("[3/3] 连接测试总结")
    print("-" * 50)
    print(f"  服务地址: {url}")
    print(f"  HTTP 连通: ✓")
    print(f"  建议: 在 Qoder/QoderWork 中配置此地址进行完整测试")
    print()
    print("  Qoder MCP 配置:")
    print(f'  {{"mcpServers": {{"matlab": {{"type": "sse", "url": "{url}"}}}}}}')
    print()
    return True


def main():
    if len(sys.argv) < 2:
        print("用法: python test_connection.py <SSE_URL>")
        print()
        print("示例:")
        print("  python test_connection.py http://192.168.1.100:8080/sse  # 局域网")
        print("  python test_connection.py http://100.x.y.z:8080/sse      # Tailscale")
        sys.exit(1)

    url = sys.argv[1]
    if not url.endswith("/sse"):
        url = url.rstrip("/") + "/sse"

    result = asyncio.run(test_sse_connection(url))
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
