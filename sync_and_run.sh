#!/bin/bash
# ============================================================
#  sync_and_run.sh - Mac 端一键同步+运行实验
#  默认打印操作提示；设 REAL=1 时通过 MCP submit_task 真实提交。
#  用法: ./sync_and_run.sh [实验命令]
#  真实模式: REAL=1 ./sync_and_run.sh "RunAblationChunk(1,1,'output_base','results_matlab/test')"
#  依赖: python3 + mcp_cli.py (标准库，无第三方包)
# ============================================================

set -e

# ============ 配置 ============
MCP_URL="${MCP_URL:-http://100.64.0.0:8080}"  # 替换为你的 Tailscale IP
MCP_TOKEN="${MCP_TOKEN:-}"
MCP_CLI="$(dirname "$0")/mcp_cli.py"
REAL="${REAL:-0}"
SYNCTHING_URL="http://127.0.0.1:8384"
# ==============================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================================"
echo "  MATLAB 实验迭代工具"
echo "============================================================"
echo ""

# 1. 检查 Syncthing 同步状态
echo -e "${YELLOW}[1/3] 检查文件同步状态...${NC}"
SYNC_STATUS=$(curl -s "$SYNCTHING_URL/rest/system/connections" 2>/dev/null || echo "UNREACHABLE")

if [ "$SYNC_STATUS" = "UNREACHABLE" ]; then
    echo -e "  ${YELLOW}⚠ Syncthing 未运行或不可达${NC}"
    echo "  代码可能未同步到 Windows，继续执行需确认代码已手动同步"
else
    CONNECTED=$(echo "$SYNC_STATUS" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    conns = data.get('connections', {})
    for k, v in conns.items():
        if v.get('connected'):
            print('YES')
            break
    else:
        print('NO')
except:
    print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN")

    if [ "$CONNECTED" = "YES" ]; then
        echo -e "  ${GREEN}✓ Syncthing 已连接，代码自动同步中${NC}"
        # 等待同步完成
        sleep 2
    else
        echo -e "  ${YELLOW}⚠ Syncthing 未连接到 Windows${NC}"
    fi
fi

# 2. 检查 MCP Server 连通性（/health 为认证白名单，无需 token）
echo -e "${YELLOW}[2/3] 检查 MCP Server...${NC}"
MCP_SERVER="${MCP_URL%/mc*}"  # 去掉 /mcp 或 /sse 得到 server 根
MCP_CHECK=$(curl -s -o /dev/null -w "%{http_code}" "$MCP_SERVER/health" --max-time 5 2>/dev/null || echo "000")

if [ "$MCP_CHECK" = "000" ]; then
    echo -e "  ${RED}✗ MCP Server 不可达: $MCP_URL${NC}"
    echo "  请确认:"
    echo "    - Windows 端 matlab_mcp_server.py 已启动"
    echo "    - Tailscale 已连接"
    echo "    - MCP_URL 环境变量设置正确"
    exit 1
else
    echo -e "  ${GREEN}✓ MCP Server 可达 ($MCP_URL)${NC}"
fi

# 3. 提交实验
echo -e "${YELLOW}[3/3] 提交实验...${NC}"
echo ""

if [ -z "$1" ]; then
    echo "用法: ./sync_and_run.sh \"<MATLAB 命令>\""
    echo ""
    echo "示例:"
    echo "  ./sync_and_run.sh \"RunAblationChunk(1, 1, 'output_base', 'results_matlab/test')\""
    echo "  ./sync_and_run.sh \"run('Main.m')\""
    echo "  ./sync_and_run.sh \"x = 1:10; disp(sum(x))\""
    echo ""
    echo "提示: 短命令用 execute_code，长实验用 submit_task"
    echo "      在 Qoder 中直接对话即可，无需此脚本"
    exit 0
fi

MATLAB_CMD="$1"
echo "  命令: $MATLAB_CMD"
echo ""

# 真实调用：通过 MCP submit_task 将命令作为后台任务提交
if [ "$REAL" = "1" ]; then
    echo -e "${GREEN}[真实调用]${NC} submit_task 提交中..."
    python3 "$MCP_CLI" submit "$MATLAB_CMD" --url "$MCP_URL" --token "$MCP_TOKEN"
    exit 0
fi

echo -e "  ${GREEN}提示: 在 Qoder 中直接说以下话即可执行:${NC}"
echo "  \"在 MATLAB 中提交后台任务: $MATLAB_CMD\""
echo ""
if [ -x "$(command -v python3)" ]; then
  echo -e "${YELLOW}可选真实调用 (REAL=1):${NC}"
  echo "  REAL=1 $0 \"$MATLAB_CMD\""
fi
echo ""
echo "============================================================"
