param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot,
    [string]$Root = "C:\Users\Administrator\Desktop\v1_7.21_new",
    [string]$Python = "C:\Python314\python.exe"
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = "${Root}_backup_${stamp}"
$backend = Join-Path $Root "backend"
$frontend = Join-Path $Root "frontend"

if (-not (Test-Path (Join-Path $PackageRoot "backend\app"))) {
    throw "Invalid update package: backend\app is missing"
}
if (-not (Test-Path (Join-Path $PackageRoot "frontend\dist\index.html"))) {
    throw "Invalid update package: frontend\dist\index.html is missing"
}

New-Item -ItemType Directory -Path (Join-Path $backup "backend") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $backup "frontend") -Force | Out-Null
Copy-Item (Join-Path $backend "app") (Join-Path $backup "backend\app") -Recurse -Force
Copy-Item (Join-Path $frontend "dist") (Join-Path $backup "frontend\dist") -Recurse -Force
if (Test-Path (Join-Path $backend ".env")) {
    Copy-Item (Join-Path $backend ".env") (Join-Path $backup "backend\.env") -Force
}

$listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
foreach ($listener in $listeners) {
    Stop-Process -Id $listener.OwningProcess -Force
}
Start-Sleep -Seconds 2

Copy-Item (Join-Path $PackageRoot "backend\app\*") (Join-Path $backend "app") -Recurse -Force
Copy-Item (Join-Path $PackageRoot "backend\scripts\*") (Join-Path $backend "scripts") -Recurse -Force
Copy-Item (Join-Path $PackageRoot "backend\deploy\*") (Join-Path $backend "deploy") -Recurse -Force
Copy-Item (Join-Path $PackageRoot "backend\docs\*") (Join-Path $backend "docs") -Recurse -Force
Copy-Item (Join-Path $PackageRoot "frontend\dist\*") (Join-Path $frontend "dist") -Recurse -Force
Copy-Item (Join-Path $PackageRoot "frontend\nginx.conf") (Join-Path $frontend "nginx.conf") -Force

$envPath = Join-Path $backend ".env"
if (Test-Path $envPath) {
    $envText = [IO.File]::ReadAllText($envPath)
    if ($envText -match "(?m)^REPORT_RULE_VERSION=") {
        $envText = [regex]::Replace(
            $envText,
            "(?m)^REPORT_RULE_VERSION=.*$",
            "REPORT_RULE_VERSION=2026-07-23"
        )
    } else {
        $envText = $envText.TrimEnd() + [Environment]::NewLine + "REPORT_RULE_VERSION=2026-07-23" + [Environment]::NewLine
    }
    [IO.File]::WriteAllText($envPath, $envText, [Text.UTF8Encoding]::new($false))
}

Push-Location $backend
try {
    & $Python -m py_compile app\services\run_source_service.py app\services\preview_service.py app\pipeline\calculation\daily.py
    if ($LASTEXITCODE -ne 0) { throw "Python compile check failed" }
    & $Python -m scripts.ensure_20260724_schema
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed" }
    New-Item -ItemType Directory -Path (Join-Path $backend "logs") -Force | Out-Null
    $stdout = Join-Path $backend "logs\uvicorn_${stamp}.out.log"
    $stderr = Join-Path $backend "logs\uvicorn_${stamp}.err.log"
    $process = Start-Process -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $backend `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
} finally {
    Pop-Location
}

$healthy = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 2
        if ($health.status -eq "ok") {
            $healthy = $true
            break
        }
    } catch { }
}
if (-not $healthy) {
    throw "Backend did not become healthy; restore from $backup and inspect $stderr"
}

try {
    $nginx = Get-Process nginx -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $nginx -and $nginx.Path) {
        & $nginx.Path -s reload
    }
} catch {
    Write-Warning "Nginx reload was skipped: $($_.Exception.Message)"
}

[pscustomobject]@{
    status = "ok"
    backup = $backup
    backend_pid = $process.Id
    rule_version = "2026-07-23"
} | ConvertTo-Json
