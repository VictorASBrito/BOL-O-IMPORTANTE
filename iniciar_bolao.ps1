$ErrorActionPreference = "Stop"

$Projeto = $PSScriptRoot
$Porta = 8080
$ServidorUrl = "http://127.0.0.1:$Porta"

$PastaLogs = Join-Path $Projeto "logs"
$LogServidorSaida = Join-Path $PastaLogs "servidor_saida.log"
$LogServidorErro = Join-Path $PastaLogs "servidor_erro.log"
$LogCloudflareSaida = Join-Path $PastaLogs "cloudflare_saida.log"
$LogCloudflareErro = Join-Path $PastaLogs "cloudflare_erro.log"

$ProcessoServidor = $null
$ProcessoCloudflare = $null
$ServidorIniciadoPeloScript = $false


function Mostrar-Titulo {
    param(
        [string]$Texto
    )

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host " $Texto" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host ""
}


function Localizar-Python {
    $Candidatos = @(
        (Join-Path $Projeto ".venv\Scripts\python.exe"),
        (Join-Path $Projeto "venv\Scripts\python.exe")
    )

    foreach ($Candidato in $Candidatos) {
        if (Test-Path $Candidato) {
            return $Candidato
        }
    }

    $PythonComando = Get-Command "python.exe" -ErrorAction SilentlyContinue

    if ($PythonComando) {
        return $PythonComando.Source
    }

    throw "Python nao encontrado. Verifique se existe .venv\Scripts\python.exe ou venv\Scripts\python.exe."
}


function Localizar-Cloudflared {
    $Candidatos = @(
        (Join-Path $Projeto "cloudflared.exe"),
        "C:\Cloudflared\cloudflared.exe",
        "C:\Cloudflared\bin\cloudflared.exe"
    )

    foreach ($Candidato in $Candidatos) {
        if (Test-Path $Candidato) {
            return $Candidato
        }
    }

    $CloudflaredComando = Get-Command "cloudflared.exe" -ErrorAction SilentlyContinue

    if ($CloudflaredComando) {
        return $CloudflaredComando.Source
    }

    throw "cloudflared.exe nao encontrado. Coloque-o na pasta do projeto ou em C:\Cloudflared\cloudflared.exe."
}


function Testar-Porta {
    param(
        [string]$Endereco,
        [int]$NumeroPorta,
        [int]$TimeoutMs = 700
    )

    $Cliente = New-Object System.Net.Sockets.TcpClient

    try {
        $Resultado = $Cliente.BeginConnect(
            $Endereco,
            $NumeroPorta,
            $null,
            $null
        )

        $Conectou = $Resultado.AsyncWaitHandle.WaitOne(
            $TimeoutMs,
            $false
        )

        if (-not $Conectou) {
            return $false
        }

        $Cliente.EndConnect($Resultado)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $Cliente.Close()
    }
}


function Aguardar-Servidor {
    param(
        [int]$Tentativas = 40
    )

    for ($i = 1; $i -le $Tentativas; $i++) {
        if (Testar-Porta -Endereco "127.0.0.1" -NumeroPorta $Porta) {
            return $true
        }

        Write-Host "Aguardando o servidor... ($i/$Tentativas)" -ForegroundColor DarkGray
        Start-Sleep -Milliseconds 500
    }

    return $false
}


function Ler-Logs-Cloudflare {
    $Conteudo = ""

    if (Test-Path $LogCloudflareSaida) {
        try {
            $Conteudo += Get-Content $LogCloudflareSaida -Raw -ErrorAction SilentlyContinue
            $Conteudo += "`n"
        }
        catch {
        }
    }

    if (Test-Path $LogCloudflareErro) {
        try {
            $Conteudo += Get-Content $LogCloudflareErro -Raw -ErrorAction SilentlyContinue
            $Conteudo += "`n"
        }
        catch {
        }
    }

    return $Conteudo
}


function Aguardar-Link-Cloudflare {
    param(
        [int]$Tentativas = 90
    )

    $Padrao = "https://[a-zA-Z0-9-]+\.trycloudflare\.com"

    for ($i = 1; $i -le $Tentativas; $i++) {
        if ($null -ne $ProcessoCloudflare) {
            if ($ProcessoCloudflare.HasExited) {
                return $null
            }
        }

        $Conteudo = Ler-Logs-Cloudflare
        $Encontrado = [regex]::Match(
            $Conteudo,
            $Padrao
        )

        if ($Encontrado.Success) {
            return $Encontrado.Value
        }

        Write-Host "Criando link publico... ($i/$Tentativas)" -ForegroundColor DarkGray
        Start-Sleep -Seconds 1
    }

    return $null
}


function Encerrar-Processo {
    param(
        $Processo,
        [string]$Nome
    )

    if ($null -eq $Processo) {
        return
    }

    if ($Processo.HasExited) {
        return
    }

    Write-Host "Encerrando $Nome..." -ForegroundColor DarkGray

    try {
        Stop-Process -Id $Processo.Id -Force -ErrorAction Stop
        $Processo.WaitForExit(3000)
    }
    catch {
        Write-Host "Nao foi possivel encerrar $Nome automaticamente." -ForegroundColor Yellow
    }
}


try {
    $Host.UI.RawUI.WindowTitle = "Bolao - Servidor e Cloudflare"

    Mostrar-Titulo "INICIANDO O BOLAO"

    if (-not (Test-Path $PastaLogs)) {
        New-Item -ItemType Directory -Path $PastaLogs | Out-Null
    }

    $ArquivosLog = @(
        $LogServidorSaida,
        $LogServidorErro,
        $LogCloudflareSaida,
        $LogCloudflareErro
    )

    foreach ($ArquivoLog in $ArquivosLog) {
        if (Test-Path $ArquivoLog) {
            Remove-Item $ArquivoLog -Force
        }
    }

    $ArquivoServidor = Join-Path $Projeto "server.py"

    if (-not (Test-Path $ArquivoServidor)) {
        throw "O arquivo server.py nao foi encontrado em: $Projeto"
    }

    $Python = Localizar-Python
    $Cloudflared = Localizar-Cloudflared

    Write-Host "Projeto:     $Projeto"
    Write-Host "Python:      $Python"
    Write-Host "Cloudflared: $Cloudflared"
    Write-Host ""

    if (Testar-Porta -Endereco "127.0.0.1" -NumeroPorta $Porta) {
        Write-Host "O servidor ja esta ativo na porta $Porta." -ForegroundColor Yellow
    }
    else {
        Write-Host "Iniciando o servidor Flask/Waitress..." -ForegroundColor Green

        $ParametrosServidor = @{
            FilePath = $Python
            ArgumentList = @($ArquivoServidor)
            WorkingDirectory = $Projeto
            RedirectStandardOutput = $LogServidorSaida
            RedirectStandardError = $LogServidorErro
            WindowStyle = "Hidden"
            PassThru = $true
        }

        $ProcessoServidor = Start-Process @ParametrosServidor
        $ServidorIniciadoPeloScript = $true
    }

    $ServidorDisponivel = Aguardar-Servidor

    if (-not $ServidorDisponivel) {
        $ErroServidor = ""

        if (Test-Path $LogServidorErro) {
            $ErroServidor = Get-Content $LogServidorErro -Raw -ErrorAction SilentlyContinue
        }

        throw "O servidor nao respondeu na porta $Porta.`n`n$ErroServidor"
    }

    Write-Host "Servidor local disponivel em $ServidorUrl" -ForegroundColor Green
    Write-Host ""
    Write-Host "Iniciando o Cloudflare Tunnel..." -ForegroundColor Green

    $ParametrosCloudflare = @{
        FilePath = $Cloudflared
        ArgumentList = @(
            "tunnel",
            "--url",
            "http://localhost:$Porta"
        )
        WorkingDirectory = $Projeto
        RedirectStandardOutput = $LogCloudflareSaida
        RedirectStandardError = $LogCloudflareErro
        WindowStyle = "Hidden"
        PassThru = $true
    }

    $ProcessoCloudflare = Start-Process @ParametrosCloudflare

    $LinkPublico = Aguardar-Link-Cloudflare

    if (-not $LinkPublico) {
        $ErroCloudflare = Ler-Logs-Cloudflare

        throw "Nao foi possivel localizar o link publico do Cloudflare.`n`n$ErroCloudflare"
    }

    Mostrar-Titulo "SITE DISPONIVEL"

    Write-Host "Link publico:" -ForegroundColor White
    Write-Host ""
    Write-Host "    $LinkPublico" -ForegroundColor Green
    Write-Host ""

    try {
        Set-Clipboard -Value $LinkPublico
        Write-Host "O link foi copiado para a area de transferencia." -ForegroundColor Cyan
    }
    catch {
        Write-Host "Nao foi possivel copiar o link automaticamente." -ForegroundColor Yellow
    }

    try {
        Start-Process $LinkPublico
        Write-Host "O site foi aberto no navegador." -ForegroundColor Cyan
    }
    catch {
        Write-Host "Abra o link manualmente no navegador." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "Mantenha esta janela aberta enquanto o site estiver sendo usado." -ForegroundColor White
    Write-Host "Pressione ENTER para desligar o servidor e o tunel." -ForegroundColor Yellow
    Read-Host | Out-Null
}
catch {
    Write-Host ""
    Write-Host "ERRO AO INICIAR O BOLAO" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Consulte a pasta de logs:" -ForegroundColor Yellow
    Write-Host "    $PastaLogs" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Pressione ENTER para fechar" | Out-Null
}
finally {
    Encerrar-Processo -Processo $ProcessoCloudflare -Nome "Cloudflare Tunnel"

    if ($ServidorIniciadoPeloScript) {
        Encerrar-Processo -Processo $ProcessoServidor -Nome "servidor do bolao"
    }
}
