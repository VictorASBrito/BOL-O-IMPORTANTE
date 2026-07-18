$ErrorActionPreference = "SilentlyContinue"

Write-Host "Encerrando processos do bolao..." -ForegroundColor Yellow

Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -match "server\.py"
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force
    }

Get-Process "cloudflared" -ErrorAction SilentlyContinue |
    Stop-Process -Force

Write-Host "Servidor e Cloudflare Tunnel encerrados." -ForegroundColor Green
Start-Sleep -Seconds 2
