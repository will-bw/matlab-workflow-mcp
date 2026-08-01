@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM ============================================================
REM  MATLAB MCP Server v3.0 - 启动脚本 (子进程池架构)
REM  双击运行或在命令行执行即可启动服务
REM ============================================================

echo ============================================================
echo   MATLAB MCP Server v3.0 启动中...
echo   架构: matlab -batch 子进程池 (真正并行)
echo ============================================================
echo.

REM 加载 .env 配置
set ENV_FILE=%~dp0.env
if exist "%ENV_FILE%" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ENV_FILE%") do (
        set "_key=%%a"
        set "_val=%%b"
        if not "!_key!"=="" if not "!_val!"=="" (
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
if not defined MAX_CONCURRENT_TASKS set MAX_CONCURRENT_TASKS=3

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请确保 Python 3.9+ 已安装并加入 PATH
    pause
    exit /b 1
)

REM 检查 MATLAB 是否在 PATH 中
where matlab >nul 2>&1
if errorlevel 1 (
    if not defined MATLAB_EXE (
        echo [警告] matlab 不在 PATH 中，且未设置 MATLAB_EXE 环境变量
        echo 请设置: set MATLAB_EXE=C:\Program Files\MATLAB\R2022b\bin\matlab.exe
        echo 或将 MATLAB bin 目录加入 PATH
        pause
        exit /b 1
    )
)

REM 检查 MCP SDK
python -c "import mcp" >nul 2>&1
if errorlevel 1 (
    echo [提示] MCP SDK 未安装，正在安装...
    pip install "mcp[cli]>=1.10.0" uvicorn psutil starlette
)

echo.
echo 工作目录: %MATLAB_WORKING_DIR%
echo 监听地址: http://%MCP_HOST%:%MCP_PORT%/mcp
echo 最大并发: %MAX_CONCURRENT_TASKS% 个 MATLAB 进程
echo.
echo 按 Ctrl+C 停止服务
echo ============================================================
echo.

REM 启动服务
python matlab_mcp_server.py

pause
