# Windows commands for the voice agent, in place of the Makefile:
#
#   .\run.ps1 start                          build the web pages and start the server
#   .\run.ps1 stop                           stop a server left running on ports 8000/8001
#   .\run.ps1 set-admin-password [username]  set or reset a desk admin password
#   .\run.ps1 update                         download the newest version and reinstall
#
# If PowerShell blocks the script: powershell -ExecutionPolicy Bypass -File .\run.ps1 start

param(
    [Parameter(Position = 0)][ValidateSet("start", "stop", "set-admin-password", "update")]
    [string]$Command = "start",
    [Parameter(Position = 1)][string]$Username = "admin"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

function Invoke-Checked {
    param([string]$Dir, [string]$Exe, [string[]]$Arguments)
    Push-Location $Dir
    try {
        & $Exe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "'$Exe $Arguments' failed in $Dir" }
    } finally { Pop-Location }
}

switch ($Command) {
    "start" {
        Invoke-Checked (Join-Path $Root "components\web") "pnpm" @("build")
        Write-Host "Starting the server on http://localhost:8000 (Ctrl+C stops it)"
        Invoke-Checked (Join-Path $Root "components\python") "uv" @("run", "src/main.py")
    }
    "stop" {
        $pids = Get-NetTCPConnection -LocalPort 8000, 8001 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
        if (-not $pids) { Write-Host "Nothing runs on ports 8000 or 8001."; break }
        foreach ($id in $pids) { Stop-Process -Id $id -Force; Write-Host "Stopped process $id" }
    }
    "set-admin-password" {
        Invoke-Checked $Root "uv" @("run", "--project", "components/python", "python",
            "components/python/scripts/set_admin_password.py", $Username)
    }
    "update" {
        Invoke-Checked $Root "git" @("pull", "--ff-only")
        Invoke-Checked (Join-Path $Root "components\web") "pnpm" @("install")
        Invoke-Checked (Join-Path $Root "components\typescript") "pnpm" @("install")
        Invoke-Checked (Join-Path $Root "components\python") "uv" @("sync", "--dev")
        Invoke-Checked (Join-Path $Root "components\web") "pnpm" @("build")
    }
}
