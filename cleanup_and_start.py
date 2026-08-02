"""
cleanup_and_start.py - MATLAB MCP Server 安全启动器
====================================================
在启动 MCP Server 前清理残留的 MATLAB 进程，防止进程泄漏。
由 NSSM 服务调用，替代直接启动 matlab_mcp_server.py。

解决问题: Python 进程异常退出（如 OOM）后，matlab -batch 子进程可能残留，
NSSM 重启 Python 服务时旧 MATLAB 进程仍占用内存。
（v3.0 子进程池架构：以 matlab -batch 标志识别残留进程）
"""

import os
import sys
import time
import signal
import logging
import subprocess

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("cleanup-start")


def kill_matlab_processes():
    """清理本服务残留的 MATLAB 进程（仅清理 matlab -batch 后台进程）"""
    killed = 0

    if sys.platform == "win32":
        try:
            # 仅查找由本服务以 matlab -batch 启动的进程（无控制台窗口）
            # 使用 wmic 查找 CommandLine 包含 "-batch" 的 MATLAB 进程
            result = subprocess.run(
                ["wmic", "process", "where",
                 "name='MATLAB.exe'",
                 "get", "ProcessId,CommandLine", "/format:csv"],
                capture_output=True, text=True, timeout=10
            )
            engine_pids = []
            for line in result.stdout.splitlines():
                # 本服务启动的 MATLAB 进程命令行包含 -batch 标志
                if "MATLAB.exe" in line and "-batch" in line:
                    parts = line.strip().split(",")
                    if parts and parts[-1].strip().isdigit():
                        engine_pids.append(parts[-1].strip())

            if engine_pids:
                logger.info(f"检测到 {len(engine_pids)} 个残留 MATLAB batch 进程: {engine_pids}")
                for pid in engine_pids:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        capture_output=True, timeout=5
                    )
                    killed += 1
                time.sleep(2)
            else:
                # 回退: 如果 wmic 不可用，检查是否有 MATLAB 进程
                result = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq MATLAB.exe", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=10
                )
                if "MATLAB.exe" in result.stdout:
                    logger.warning(
                        "检测到 MATLAB 进程但无法确认是否为 batch 进程。"
                        "为避免误杀用户交互式 MATLAB，不执行强杀。"
                        "如需强制清理，请手动执行: taskkill /F /IM MATLAB.exe"
                    )
        except FileNotFoundError:
            # wmic 在 Windows 11 24H2+ 已移除，回退到 PowerShell
            try:
                ps_cmd = (
                    "Get-Process MATLAB -ErrorAction SilentlyContinue | "
                    "Where-Object {$_.CommandLine -like '*-batch*'} | "
                    "Stop-Process -Force"
                )
                subprocess.run(
                    ["powershell", "-Command", ps_cmd],
                    capture_output=True, timeout=10
                )
                killed += 1
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"清理 MATLAB 进程时出错: {e}")
    else:
        # Linux/macOS: 仅杀 matlab -batch 相关进程
        try:
            result = subprocess.run(
                ["pgrep", "-f", "matlab.*-batch"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                logger.info("检测到残留 MATLAB batch 进程，正在清理...")
                subprocess.run(["pkill", "-9", "-f", "matlab.*-batch"], timeout=10)
                killed += 1
                time.sleep(2)
        except Exception as e:
            logger.warning(f"清理 MATLAB 进程时出错: {e}")

    if killed > 0:
        logger.info(f"已清理 {killed} 个残留 MATLAB batch 进程")
    else:
        logger.info("无残留 MATLAB batch 进程")

    return killed


def main():
    logger.info("=" * 50)
    logger.info("MATLAB MCP Server 安全启动器")
    logger.info("=" * 50)

    # Step 1: 清理残留进程
    logger.info("[1/2] 检查并清理残留 MATLAB batch 进程...")
    kill_matlab_processes()

    # Step 2: 启动 MCP Server
    logger.info("[2/2] 启动 MCP Server...")
    server_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matlab_mcp_server.py")

    if not os.path.exists(server_script):
        logger.error(f"找不到服务脚本: {server_script}")
        sys.exit(1)

    # 使用 runpy 运行（保持正确的模块语义和堆栈信息）
    import runpy
    sys.argv = [server_script]
    runpy.run_path(server_script, run_name="__main__")


if __name__ == "__main__":
    main()
