# ============================================================
#  MATLAB MCP Server - Windows 防火墙配置脚本
#  以管理员身份在 PowerShell 中运行
# ============================================================

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MATLAB MCP Server - 防火墙配置" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 检查管理员权限
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[错误] 请以管理员身份运行此脚本！" -ForegroundColor Red
    Write-Host "右键 PowerShell -> 以管理员身份运行" -ForegroundColor Yellow
    Read-Host "按回车退出"
    exit 1
}

$Port = 8080
$RuleName = "MATLAB-MCP-Server"

# ============ 方案 1: 仅局域网需要（使用 Tailscale 可跳过）============
Write-Host ""
Write-Host "注意: 如果使用 Tailscale 组网，Tailscale 走虚拟网卡，" -ForegroundColor Yellow
Write-Host "      通常不需要额外配置防火墙。" -ForegroundColor Yellow
Write-Host "      仅在局域网直连或 Tailscale 不通时需要放行端口。" -ForegroundColor Yellow
Write-Host ""

$choice = Read-Host "是否配置防火墙规则? (y/n)"
if ($choice -ne 'y' -and $choice -ne 'Y') {
    Write-Host "已跳过防火墙配置。" -ForegroundColor Green
    exit 0
}

# 删除已有同名规则
$existing = Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[提示] 删除已有规则: $RuleName" -ForegroundColor Yellow
    Remove-NetFirewallRule -Name $RuleName
}

# 创建入站规则（TCP）
Write-Host "[1/3] 创建 TCP 入站规则 (端口 $Port)..." -ForegroundColor Cyan
New-NetFirewallRule `
    -Name $RuleName `
    -DisplayName "MATLAB MCP Server (TCP $Port)" `
    -Description "允许远程连接 MATLAB MCP Server SSE 服务" `
    -Enabled True `
    -Direction Inbound `
    -Protocol TCP `
    -Action Allow `
    -LocalPort $Port `
    -Profile Any `
    | Out-Null

Write-Host "  -> 规则已创建" -ForegroundColor Green

# 可选: 限制来源 IP（更安全）
Write-Host ""
$restrict = Read-Host "是否限制来源 IP? (y=限制/n=不限制)"
if ($restrict -eq 'y' -or $restrict -eq 'Y') {
    $allowedIP = Read-Host "输入允许的 IP 或网段 (如 192.168.1.0/24 或 100.64.0.0/10)"
    Set-NetFirewallRule -Name $RuleName -RemoteAddress $allowedIP
    Write-Host "  -> 已限制来源为: $allowedIP" -ForegroundColor Green
} else {
    Write-Host "  -> 允许所有来源连接" -ForegroundColor Yellow
}

# 验证规则
Write-Host ""
Write-Host "[2/3] 验证规则..." -ForegroundColor Cyan
$rule = Get-NetFirewallRule -Name $RuleName
$portFilter = $rule | Get-NetFirewallPortFilter
Write-Host "  规则名称: $($rule.DisplayName)" -ForegroundColor White
Write-Host "  状态: $($rule.Enabled)" -ForegroundColor White
Write-Host "  方向: $($rule.Direction)" -ForegroundColor White
Write-Host "  协议: $($portFilter.Protocol)" -ForegroundColor White
Write-Host "  端口: $($portFilter.LocalPort)" -ForegroundColor White

# 测试端口监听
Write-Host ""
Write-Host "[3/3] 检查端口 $Port 是否正在监听..." -ForegroundColor Cyan
$listener = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($listener) {
    Write-Host "  -> 端口 $Port 正在监听 (PID: $($listener.OwningProcess))" -ForegroundColor Green
} else {
    Write-Host "  -> 端口 $Port 未监听（服务可能未启动）" -ForegroundColor Yellow
    Write-Host "     启动服务后会自动监听" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  防火墙配置完成！" -ForegroundColor Green
Write-Host "" -ForegroundColor Cyan
Write-Host "  Tailscale 用户提示:" -ForegroundColor Yellow
Write-Host "  Tailscale 使用虚拟网卡 (100.64.0.0/10 网段)，" -ForegroundColor Yellow
Write-Host "  如果 Tailscale 连接不通，尝试:" -ForegroundColor Yellow
Write-Host "  1. 确保 Tailscale 已连接 (系统托盘图标为绿色)" -ForegroundColor Yellow
Write-Host "  2. 在 Tailscale 管理面板确认两台设备在线" -ForegroundColor Yellow
Write-Host "  3. 尝试 ping 100.x.y.z 测试连通性" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan

Read-Host "按回车退出"
