# ============================================================
#  Syncthing 安装与配置脚本 (Windows 端)
#  以管理员身份在 PowerShell 中运行
# ============================================================

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Syncthing 配置 (Windows 端)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ============ 配置区域 ============
$Paper2Dir = "E:\code\Paper2"
$SyncPort = 22000
# ==================================

# 1. 检查/下载 Syncthing
Write-Host "[1/5] 检查 Syncthing..." -ForegroundColor Yellow
$SyncPath = "$env:LOCALAPPDATA\Syncthing\syncthing.exe"

if (Test-Path $SyncPath) {
    Write-Host "  OK Syncthing 已存在: $SyncPath" -ForegroundColor Green
} else {
    Write-Host "  请下载 Syncthing:" -ForegroundColor Yellow
    Write-Host "  https://github.com/syncthing/syncthing/releases/latest" -ForegroundColor White
    Write-Host "  下载 syncthing-windows-amd64-v*.zip" -ForegroundColor White
    Write-Host "  解压到: $env:LOCALAPPDATA\Syncthing\" -ForegroundColor White
    Write-Host ""
    Write-Host "  或使用 winget:" -ForegroundColor Yellow
    Write-Host "  winget install Syncthing.Syncthing" -ForegroundColor White
    Write-Host ""

    $choice = Read-Host "是否尝试用 winget 安装? (y/n)"
    if ($choice -eq 'y') {
        winget install Syncthing.Syncthing --accept-package-agreements
        $SyncPath = (Get-Command syncthing -ErrorAction SilentlyContinue).Source
        if (-not $SyncPath) {
            $SyncPath = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\syncthing.exe"
        }
    }
}

# 2. 创建同步目录
Write-Host "[2/5] 创建同步目录..." -ForegroundColor Yellow
if (-not (Test-Path $Paper2Dir)) { New-Item -ItemType Directory -Path $Paper2Dir -Force | Out-Null }
Write-Host "  OK 代码目录: $Paper2Dir" -ForegroundColor Green

# 3. 复制 .stignore
Write-Host "[3/5] 配置忽略规则..." -ForegroundColor Yellow
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StignoreSrc = Join-Path $ScriptDir ".stignore"
if (Test-Path $StignoreSrc) {
    Copy-Item $StignoreSrc "$Paper2Dir\.stignore" -Force
    Write-Host "  OK .stignore 已复制" -ForegroundColor Green
} else {
    Write-Host "  !! 未找到 .stignore 文件" -ForegroundColor Red
}

# 4. 防火墙放行 Syncthing 端口
Write-Host "[4/5] 配置防火墙..." -ForegroundColor Yellow
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    $ruleName = "Syncthing-Sync"
    $existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule -Name $ruleName -DisplayName "Syncthing Sync Port" `
            -Enabled True -Direction Inbound -Protocol TCP -Action Allow `
            -LocalPort $SyncPort | Out-Null
        Write-Host "  OK 防火墙已放行端口 $SyncPort" -ForegroundColor Green
    } else {
        Write-Host "  OK 防火墙规则已存在" -ForegroundColor Green
    }

    # Web UI 端口
    $ruleName2 = "Syncthing-WebUI"
    $existing2 = Get-NetFirewallRule -Name $ruleName2 -ErrorAction SilentlyContinue
    if (-not $existing2) {
        New-NetFirewallRule -Name $ruleName2 -DisplayName "Syncthing Web UI" `
            -Enabled True -Direction Inbound -Protocol TCP -Action Allow `
            -LocalPort 8384 | Out-Null
    }
} else {
    Write-Host "  !! 非管理员模式，跳过防火墙配置" -ForegroundColor Yellow
    Write-Host "  手动放行: TCP $SyncPort 和 8384" -ForegroundColor Yellow
}

# 5. 配置开机自启动
Write-Host "[5/5] 配置开机自启动..." -ForegroundColor Yellow
$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "Syncthing.lnk"
if (-not (Test-Path $shortcutPath)) {
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($shortcutPath)
    $Shortcut.TargetPath = $SyncPath
    $Shortcut.Arguments = "--no-browser"
    $Shortcut.WindowStyle = 7  # Minimized
    $Shortcut.Save()
    Write-Host "  OK 已添加到启动文件夹" -ForegroundColor Green
} else {
    Write-Host "  OK 启动项已存在" -ForegroundColor Green
}

# 输出后续步骤
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  后续手动配置步骤:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1. 启动 Syncthing:" -ForegroundColor White
Write-Host "     syncthing --no-browser" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. 打开 Web UI: http://127.0.0.1:8384" -ForegroundColor White
Write-Host ""
Write-Host "  3. 获取本机 Device ID (操作 → 显示ID)" -ForegroundColor White
Write-Host "     将此 ID 告知 Mac 端" -ForegroundColor Gray
Write-Host ""
Write-Host "  4. 添加 Mac 设备:" -ForegroundColor White
Write-Host "     地址: tcp://<Mac-Tailscale-IP>:22000" -ForegroundColor Gray
Write-Host ""
Write-Host "  5. 添加同步文件夹 (代码，双向):" -ForegroundColor White
Write-Host "     文件夹ID: paper2-code" -ForegroundColor Gray
Write-Host "     路径: $Paper2Dir" -ForegroundColor Gray
Write-Host ""
Write-Host "  6. 在 Mac 端接受共享邀请" -ForegroundColor White
Write-Host ""
Write-Host "  注意: 实验结果(.mat)不需要同步，" -ForegroundColor Yellow
Write-Host "  通过 MCP 工具远程分析 (get_variable, execute_code, save_figure)" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan

Read-Host "按回车退出"
