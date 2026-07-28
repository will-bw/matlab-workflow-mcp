#!/bin/bash
# ============================================================
#  fetch_results.sh - 从 Windows 拉取实验结果到 Mac
#  通过 MCP transfer_file 接口按需拉取
#  用法: ./fetch_results.sh <远程路径> [本地保存路径]
# ============================================================

set -e

# ============ 配置 ============
MCP_URL="${MCP_URL:-http://100.64.0.0:8080}"
# 结果分析通过 MCP 远程完成，无需同步到本地
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
    echo "在 Qoder 中说: \"列出 Windows 上 $DIR 目录的文件\""
    echo "或使用 MCP list_files 工具"
    echo ""
    echo "curl 方式 (需 MCP 客户端支持):"
    echo "  通过 Qoder 调用 list_files(directory='$DIR')"
    exit 0
fi

REMOTE_PATH="$1"
LOCAL_PATH="${2:-./$(basename "$REMOTE_PATH")}"

echo -e "${YELLOW}远程文件:${NC} $REMOTE_PATH"
echo -e "${YELLOW}保存到:${NC}   $LOCAL_PATH"
echo ""

# 确保本地目录存在
mkdir -p "$(dirname "$LOCAL_PATH")"

echo -e "${GREEN}提示: 在 Qoder 中说以下话即可拉取:${NC}"
echo ""
echo "  \"从 Windows 下载文件 $REMOTE_PATH\""
echo ""
echo "MCP 工具调用:"
echo "  transfer_file(file_path='$REMOTE_PATH')"
echo ""
echo "拉取后文件保存在: $LOCAL_PATH"
echo ""
echo "============================================================"
echo ""
echo "其他常用操作:"
echo "  查看结果: \"加载 $REMOTE_PATH 并显示 cost\""
echo "  对比分析: \"对比 results_matlab/A 和 results_matlab B 的结果\""
echo "  导出图表: \"绘制收敛曲线并导出为 PNG\""
