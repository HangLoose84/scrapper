#Requires -Version 5.1
# Supervisor con backoff exponencial: 10s, 20s, 40s... hasta 5 min.
# Si el bot sobrevive $ResetThreshold, el castigo vuelve a 10s.

$here    = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$LogFile = Join-Path $here 'bot.log'
$Python  = Join-Path $here '.venv\Scripts\python.exe'

$InitialDelay   = 10
$CurrentDelay   = $InitialDelay
$MaxDelay       = 300   # Tope de 5 minutos
$ResetThreshold = 300   # Resetear backoff si el bot sobrevive 5 minutos

# Python emite UTF-8; sin esto los emojis llegan rotos al log bajo powershell.exe 5.1.
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

function Write-Log([string]$Text, [string]$Color = 'Gray') {
    Write-Host $Text -ForegroundColor $Color
    Add-Content -LiteralPath $LogFile -Value $Text -Encoding UTF8
}

if (-not (Test-Path $Python)) { throw "No existe $Python. Crea el venv primero." }

while ($true) {
    Write-Log "=========================================" 'Green'
    Write-Log "🚀 Iniciando Deal Hunter Bot..." 'Green'
    Write-Log "=========================================" 'Green'

    $StartTime = Get-Date

    # 2>&1 junta stderr con stdout: $_ va a consola, Add-Content al archivo, ambos UTF-8.
    & $Python (Join-Path $here 'main.py') 2>&1 | ForEach-Object {
        $line = [string]$_
        $line
        Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    }

    $CrashTime   = Get-Date
    $RunDuration = ($CrashTime - $StartTime).TotalSeconds

    # Si el bot corrio estable por un buen rato, reseteamos el castigo.
    if ($RunDuration -ge $ResetThreshold) {
        $CurrentDelay = $InitialDelay
    }

    $Timestamp    = $CrashTime.ToString("yyyy-MM-dd HH:mm:ss")
    $CrashMessage = "[$Timestamp] ⚠️ El bot se detuvo tras $([int]$RunDuration)s (exit $LASTEXITCODE). Reiniciando en $CurrentDelay segundos..."
    Write-Log $CrashMessage 'Red'

    Start-Sleep -Seconds $CurrentDelay

    # Backoff exponencial para el proximo posible fallo.
    $CurrentDelay = $CurrentDelay * 2
    if ($CurrentDelay -gt $MaxDelay) {
        $CurrentDelay = $MaxDelay
    }
}
