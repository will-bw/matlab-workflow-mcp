@echo off
REM ============================================================
REM  MATLAB MCP Server - Windows 服务安装脚本
REM  使用 NSSM 将服务注册为 Windows 服务（开机自启动）
REM  
REM  前置条件:
REM  1. 下载 NSSM: https://nssm.cc/download
REM  2. 将 nssm.exe 放入本目录或加入 PATH
REM  3. 以管理员身份运行本脚本
REM ============================================================

echo ============================================================
echo   MATLAB MCP Server - 服务安装
echo ============================================================
echo.

REM 检查管理员权限
net session >nul 2>&1
if errorlevel 1 (
    echo [错误] 请以管理员身份运行此脚本！
    echo 右键点击此文件 -^> "以管理员身份运行"
    pause
    exit /b 1
)

REM ============ 配置区域（根据实际环境修改）============
set SERVICE_NAME=MatlabMCPServer
set PYTHON_PATH=C:\Python310\python.exe
set SCRIPT_PATH=E:\code\WinServerBuild\cleanup_and_start.py
set WORKING_DIR=E:\code\Paper2
set LOG_DIR=E:\code\WinServerBuild\logs
REM ====================================================

REM 检查 NSSM 是否存在
where nssm >nul 2>&1
if errorlevel 1 (
    if not exist "nssm.exe" (
        echo [错误] 未找到 nssm.exe
        echo 请从 https://nssm.cc/download 下载并放入本目录
        pause
        exit /b 1
    )
    set NSSM=nssm.exe
) else (
    set NSSM=nssm
)

REM 检查 Python 路径
if not exist "%PYTHON_PATH%" (
    echo [错误] Python 路径不存在: %PYTHON_PATH%
    echo 请修改脚本中的 PYTHON_PATH 变量
    echo.
    echo 查找 Python 路径:
    where python
    pause
    exit /b 1
)

REM 创建日志目录
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM 如果服务已存在，先停止并删除
%NSSM% status %SERVICE_NAME% >nul 2>&1
if not errorlevel 1 (
    echo [提示] 服务已存在，正在重新安装...
    %NSSM% stop %SERVICE_NAME% >nul 2>&1
    %NSSM% remove %SERVICE_NAME% confirm >nul 2>&1
    timeout /t 2 >nul
)

echo [1/4] 安装服务...
%NSSM% install %SERVICE_NAME% "%PYTHON_PATH%" "%SCRIPT_PATH%"

echo [2/4] 配置服务参数...
%NSSM% set %SERVICE_NAME% AppDirectory "%WORKING_DIR%"
%NSSM% set %SERVICE_NAME% DisplayName "MATLAB MCP Server"
%NSSM% set %SERVICE_NAME% Description "MATLAB 远程执行 MCP 服务 (SSE 传输, 端口 8080)"
%NSSM% set %SERVICE_NAME% Start SERVICE_AUTO_START
%NSSM% set %SERVICE_NAME% ObjectName LocalSystem

REM 设置环境变量
%NSSM% set %SERVICE_NAME% AppEnvironmentExtra "MATLAB_WORKING_DIR=%WORKING_DIR%" "MCP_HOST=0.0.0.0" "MCP_PORT=8080"

REM 配置日志输出
%NSSM% set %SERVICE_NAME% AppStdout "%LOG_DIR%\service_stdout.log"
%NSSM% set %SERVICE_NAME% AppStderr "%LOG_DIR%\service_stderr.log"
%NSSM% set %SERVICE_NAME% AppRotateFiles 1
%NSSM% set %SERVICE_NAME% AppRotateBytes 10485760

REM 配置崩溃自动重启
%NSSM% set %SERVICE_NAME% AppExit Default Restart
%NSSM% set %SERVICE_NAME% AppRestartDelay 5000

echo [3/4] 启动服务...
%NSSM% start %SERVICE_NAME%

echo [4/4] 验证服务状态...
timeout /t 3 >nul
%NSSM% status %SERVICE_NAME%

echo.
echo ============================================================
echo   安装完成！
echo.
echo   服务名称: %SERVICE_NAME%
echo   服务地址: http://0.0.0.0:8080/sse
echo   日志目录: %LOG_DIR%
echo.
echo   管理命令:
echo     查看状态: nssm status %SERVICE_NAME%
echo     停止服务: nssm stop %SERVICE_NAME%
echo     启动服务: nssm start %SERVICE_NAME%
echo     重启服务: nssm restart %SERVICE_NAME%
echo     删除服务: nssm remove %SERVICE_NAME% confirm
echo ============================================================
pause
