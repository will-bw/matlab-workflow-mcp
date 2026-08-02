#!/bin/bash
# ============================================================
#  fetch_results.sh - 从 Windows 拉取实验结果到 Mac
#  默认打印操作提示；设 REAL=1 时通过 MCP transfer_file 实际拉取。
#  用法: ./fetch_results.sh <远程路径> [本地保存路径]
#  真实模式: REAL=1 ./fetch_results.sh <远程路径> [本地保存路径]
#  依赖: python3 + mcp_cli.py (标准库，无第三方包)
# ============================================================

set -e

# ============ 配置 ============
MCP_URL="${MCP_URL:-http://100.64.0.0:8080}"
MCP_TOKEN="${MCP_TOKEN:-}"
MCP_CLI="$(dirname "$0")/mcp_cli.py"
# 真实调用开关：REAL=1 时通过 MCP transfer_file 实际拉取文件
# 默认关闭（仅打印提示），避免误发起远端请求。
REAL="${REAL:-0}"
# ==============================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "============================================================"
echo "  实验结果拉取工具"
echo "============================================================"
echo ""

# 检查参数
if [ -z "$1" ]; then
    echo "用法:"
    echo "  ./fetch_results.sh <远程文件路径> [本地保存路径]"
    echo ""
    echo "示例:"
    echo "  ./fetch_results.sh results_matlab/test/model_1_result.mat"
    echo "  ./fetch_results.sh results_matlab/test/model_1_result.mat ./my_result.mat"
    echo ""
    echo "批量拉取 (列出目录):"
    echo "  ./fetch_results.sh --list results_matlab/test/"
    echo ""
    echo "提示: 如果 Syncthing results 同步已配置，结果会自动同步，"
    echo "      无需手动拉取。此脚本用于按需获取单个文件。"
    exit 0
fi

# 列出目录模式
if [ "$1" = "--list" ]; then
    DIR="${2:-.}"
    echo -e "${YELLOW}列出远程目录: $DIR${NC}"
    echo ""
    if [ "$REAL" = "1" ]; then
        echo -e "${GREEN}[真实调用]${NC} list_files(directory='$DIR')"
        python3 "$MCP_CLI" call list_files "{\"directory\": \"$DIR\"}" \
            --url "$MCP_URL" --token "$MCP_TOKEN"
        exit 0
    fi
    echo "在 Qoder 中说: \"列出 Windows 上 $DIR 目录的文件\""
    echo "或使用 MCP list_files 工具"
    echo ""
    if [ -x "$(command -v python3)" ]; then
      echo -e "${YELLOW}可选真实调用 (REAL=1):${NC}"
      echo "  REAL=1 $0 --list $DIR"
      echo ""
      echo "  python3 mcp_cli.py call list_files '{\"directory\":\"$DIR\"}'"
    fi
    exit 0
fi

REMOTE_PATH="$1"
LOCAL_PATH="${2:-./$(basename "$REMOTE_PATH")}"

echo -e "${YELLOW}远程文件:${NC} $REMOTE_PATH"
echo -e "${YELLOW}保存到:${NC}   $LOCAL_PATH"
echo ""

# 确保本地目录存在
mkdir -p "$(dirname "$LOCAL_PATH")"

# 真实调用：通过 MCP transfer_file 实际拉取并保存
if [ "$REAL" = "1" ]; then
    echo -e "${GREEN}[真实调用]${NC} transfer_file(file_path='$REMOTE_PATH')"
    python3 "$MCP_CLI" transfer "$REMOTE_PATH" "$LOCAL_PATH" \
        --url "$MCP_URL" --token "$MCP_TOKEN"
    echo -e "${GREEN}✓ 文件已保存到: $LOCAL_PATH${NC}"
    exit 0
fi

echo -e "${GREEN}提示: 在 Qoder 中说以下话即可拉取:${NC}"
echo ""
echo "  \"从 Windows 下载文件 $REMOTE_PATH\""
echo ""
echo "MCP 工具调用:"
echo "  transfer_file(file_path='$REMOTE_PATH')"
echo ""
if [ -x "$(command -v python3)" ]; then
  echo -e "${YELLOW}可选真实调用 (REAL=1):${NC}"
  echo "  REAL=1 $0 '$REMOTE_PATH' '$LOCAL_PATH'"
  echo ""
fi

echo "拉取后文件保存在: $LOCAL_PATH"
echo ""
echo "============================================================"
echo ""
echo "其他常用操作:"
echo "  查看结果: \"加载 $REMOTE_PATH 并显示 cost\""
echo "  对比分析: \"对比 results_matlab/A 和 results_matlab B 的结果\""
echo "  导出图表: \"绘制收敛曲线并导出为 PNG\""
