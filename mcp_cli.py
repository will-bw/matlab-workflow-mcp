#!/usr/bin/env python3
"""
mcp_cli.py - 供 shell 脚本使用的轻量 MCP (Streamable HTTP) 客户端
=================================================================
仅用标准库 urllib.request 实现，无第三方依赖。
实现对 MATLAB MCP Server 的真实 JSON-RPC 调用。

子命令:
  call TOOL '{"arg": val, ...}' [--url U] [--token T]
        调用单个 MCP tool，打印其返回文本。原型:
        `python3 mcp_cli.py call run '{"code":"disp(1+1)"}'`

  transfer REMOTE [LOCAL] [--url U] [--token T] [--all]
       通过 transfer_file 拉取远端文件（base64 解码）到 LOCAL。
       --all 时输出原始返回文本（便于调试）。

  submit CODE [--url U] [--token T]
       调用 submit_task 提交后台任务，打印 task_id。

示例:
  python3 mcp_cli.py call sync_status --url http://100.x.y.z:8080 --token secret
  python3 mcp_cli.py transfer results_matlab/a.mat ./a.mat
"""

import argparse
import base64
import json
import re
import sys
import urllib.request
import urllib.error
import os


def _parse_data(text: str):
    """将响应体解析为 JSON-RPC 对象（兼容 application/json 与 SSE）。"""
    text = text.strip()
    # 直接 JSON
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    # SSE: 收集 data: 行，取最后一个有效 JSON
    obj = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                obj = json.loads(line[5:].strip())
            except ValueError:
                pass
    return obj


def _client():
    return {"protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "mcp_cli", "version": "1.0"}}


class McpClient:
    def __init__(self, url, token=""):
        # 端点默认 /mcp
        self.url = url.rstrip("/")
        if not (self.url.endswith("/mcp") or self.url.endswith("/sse")):
            self.url += "/mcp"
        self.token = token
        self._session = None

    def _post(self, payload, timeout=120):
        req = urllib.request.Request(self.url, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if self._session:
            req.add_header("Mcp-Session-Id", self._session)
        body = json.dumps(payload, ensure_ascii=False).encode()
        try:
            with urllib.request.urlopen(req, data=body, timeout=timeout) as resp:
                headers = {k.lower(): v for k, v in resp.headers.items()}
                data = resp.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
        if self._session is None:
            self._session = headers.get("mcp-session-id")
        return data

    def connect(self):
        """initialize + initialized 通知，建立会话。"""
        self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": _client()})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def call(self, tool: str, arguments: dict, timeout=120):
        """调用 MCP tool，返回 (text, is_error)。"""
        self.connect()
        data = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": tool, "arguments": arguments}},
                          timeout=timeout)
        obj = _parse_data(data)
        if obj is None:
            return f"[无法解析响应]\n{data[:500]}", True
        if "error" in obj:
            return obj["error"].get("message", "RPC error"), True
        res = obj.get("result", {})
        is_err = bool(res.get("isError"))
        if isinstance(res, dict):
            content = res.get("content", [])
            texts = [c.get("text", "") for c in content
                     if isinstance(c, dict) and c.get("type") == "text"]
            return ("\n".join(texts) if texts else json.dumps(res, ensure_ascii=False)), is_err
        return str(res), is_err


def _arg_parser():
    p = argparse.ArgumentParser(description="MATLAB MCP Streamable HTTP 轻量客户端")
    sub = p.add_subparsers(dest="cmd", required=True)

    def base(subp):
        subp.add_argument("--url", default=os.environ.get("MCP_URL", "http://localhost:8080"))
        subp.add_argument("--token", default=os.environ.get("MCP_TOKEN", ""))

    c = sub.add_parser("call", help="调用单个 tool")
    c.add_argument("tool")
    c.add_argument("arguments", nargs="?", default="{}")
    base(c)

    t = sub.add_parser("transfer", help="拉取远端文件")
    t.add_argument("remote")
    t.add_argument("local", nargs="?", default=None)
    t.add_argument("--all", action="store_true", help="输出原始返回文本")
    base(t)

    s = sub.add_parser("submit", help="提交后台任务")
    s.add_argument("code")
    base(s)
    return p


def main():
    args = _arg_parser().parse_args()
    client = McpClient(args.url, getattr(args, "token", ""))
    try:
        if args.cmd == "call":
            arguments = json.loads(args.arguments) if args.arguments else {}
            text, is_err = client.call(args.tool, arguments)
            print(text)
            sys.exit(1 if is_err else 0)

        elif args.cmd == "transfer":
            text, is_err = client.call("transfer_file", {"file_path": args.remote})
            if args.all:
                print(text)
            if is_err:
                print(text, file=sys.stderr)
                sys.exit(1)
            m = re.search(r"\[BASE64_START\]\n(.*)\n\[BASE64_END\]", text, re.S)
            if not m:
                print(f"[错误] 未能从响应中提取 base64:\n{text[:500]}", file=sys.stderr)
                sys.exit(1)
            local = args.local or os.path.basename(args.remote)
            os.makedirs(os.path.dirname(os.path.abspath(local)) or ".", exist_ok=True)
            with open(local, "wb") as f:
                f.write(base64.b64decode(m.group(1)))
            print(f"[已写入] {local}")

        elif args.cmd == "submit":
            text, is_err = client.call("submit_task", {"code": args.code})
            print(text)
            sys.exit(1 if is_err else 0)
    except (RuntimeError, urllib.error.URLError, ConnectionError, OSError) as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()