#!/bin/bash
# ============================================================
#  Syncthing 安装与配置脚本 (Mac 端)
#  用于 Paper2 项目的 Mac↔Windows 代码同步
# ============================================================

set -e

echo "============================================================"
echo "  Syncthing 配置 (Mac 端)"
echo "============================================================"
echo ""

# ============ 配置区域 ============
PAPER2_DIR="$HOME/Desktop/codes/Paper2"
SYNCTHING_PORT=8384  # Web UI 端口（默认 8384）
# ==================================

# 1. 安装 Syncthing
echo "[1/5] 安装 Syncthing..."
if command -v syncthing &> /dev/null; then
    echo "  ✓ Syncthing 已安装: $(syncthing --version)"
else
    if command -v brew &> /dev/null; then
        brew install syncthing
        echo "  ✓ Syncthing 安装完成"
    else
        echo "  ✗ 请先安装 Homebrew: https://brew.sh"
        exit 1
    fi
fi

# 2. 创建同步目录
echo "[2/5] 创建同步目录..."
mkdir -p "$PAPER2_DIR"
echo "  ✓ 代码目录: $PAPER2_DIR"

# 3. 复制 .stignore 到 Paper2 目录
echo "[3/5] 配置忽略规则..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/.stignore" ]; then
    cp "$SCRIPT_DIR/.stignore" "$PAPER2_DIR/.stignore"
    echo "  ✓ .stignore 已复制到 $PAPER2_DIR/"
else
    echo "  ⚠ 未找到 .stignore，请手动复制"
fi

# 4. 设置开机自启动
echo "[4/5] 配置开机自启动..."
brew services start syncthing 2>/dev/null || true
echo "  ✓ Syncthing 已设为后台服务"

# 5. 输出配置指引
echo "[5/5] 后续配置步骤"
echo ""
echo "============================================================"
echo "  Syncthing 已安装！请完成以下手动配置："
echo ""
echo "  1. 打开 Syncthing Web UI:"
echo "     open http://127.0.0.1:${SYNCTHING_PORT}"
echo ""
echo "  2. 获取本机 Device ID:"
echo "     点击右上角 '操作' → '显示ID'"
echo "     将此 ID 发给 Windows 端（或扫码）"
echo ""
echo "  3. 添加 Windows 设备:"
echo "     点击 '添加远程设备' → 输入 Windows 的 Device ID"
echo "     地址填: tcp://<Windows-Tailscale-IP>:22000"
echo "     (如 tcp://100.x.y.z:22000)"
echo ""
echo "  4. 添加同步文件夹 (代码，双向):"
echo "     文件夹ID: paper2-code"
echo "     路径: $PAPER2_DIR"
echo "     共享给: Windows 设备"
echo "     文件版本控制: Staggered (保留7天)"
echo ""
echo "  5. 在 Windows 端接受共享邀请"
echo ""
echo "  注意: 实验结果(.mat)不需要同步回 Mac，"
echo "  通过 MCP 工具远程分析即可 (get_variable, execute_code, save_figure)"
echo ""
echo "  提示: 两台机器需先通过 Tailscale 组网"
echo "============================================================"
