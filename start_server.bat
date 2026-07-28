@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM ============================================================
REM  MATLAB MCP Server - 快速启动脚本
REM  双击运行或在命令行执行即可启动服务
REM ============================================================

echo ============================================================
echo   MATLAB MCP Server 启动中...
echo ============================================================
echo.

REM P1-B 修复: 正确的 .env 解析逻辑
set ENV_FILE=%~dp0.env
if exist "%ENV_FILE%" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ENV_FILE%") do (
        set "_key=%%a"
        set "_val=%%b"
        REM 跳过空行和注释
        if not "!_key!"=="" if not "!_val!"=="" (
            REM 去除可能的空格
            for /f "tokens=*" %%x in ("!_key!") do set "_key=%%x"
            for /f "tokens=*" %%x in ("!_val!") do set "_val=%%x"
            set "!_key!=!_val!"
        )
    )
)
REM 回退默认值
if not defined MATLAB_WORKING_DIR set MATLAB_WORKING_DIR=E:\code\Paper2
if not defined MCP_HOST set MCP_HOST=0.0.0.0
if not defined MCP_PORT set MCP_PORT=8080
if not defined MAX_OUTPUT_LENGTH set MAX_OUTPUT_LENGTH=50000

REM 检查 Python 是否可用
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请确保 Python 3.8-3.10 已安装并加入 PATH
    echo 下载地址: https://www.python.org/downloads/release/python-31011/
    pause
    exit /b 1
)

REM 检查 matlab.engine 是否已安装
python -c "import matlab.engine" >nul 2>&1
if errorlevel 1 (
    echo [错误] MATLAB Engine API for Python 未安装
    echo 请执行:
    echo   cd "C:\Program Files\MATLAB\R2022b\extern\engines\python"
    echo   python setup.py install
    pause
    exit /b 1
)

REM 检查 mcp 是否已安装
python -c "import mcp" >nul 2>&1
if errorlevel 1 (
    echo [提示] MCP SDK 未安装，正在安装...
    pip install "mcp[cli]" uvicorn
)

echo.
echo 工作目录: %MATLAB_WORKING_DIR%
echo 监听地址: http://%MCP_HOST%:%MCP_PORT%/sse
echo.
echo 按 Ctrl+C 停止服务
echo ============================================================
echo.

REM 启动服务（使用环境变量配置）
python matlab_mcp_server.py

pause
