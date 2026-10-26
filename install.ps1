# Installs the Ustad Hotel voice agent on Windows 10/11 with one command
# (in PowerShell):
#
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/dev3-trojanitsolutions/voice-sandwich-demo/main/install.ps1 | iex"
#
# Environment: INSTALL_DIR (default .\voice-sandwich-demo), REPO_URL, BRANCH,
# NO_LLM=1 to skip Ollama and the local model (about 4 GB).
# The local voice service needs Apple silicon, so Windows doesn't get it.

$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:REPO_URL) { $env:REPO_URL } else { "https://github.com/dev3-trojanitsolutions/voice-sandwich-demo.git" }
$Branch = if ($env:BRANCH) { $env:BRANCH } else { "main" }
$InstallDir = if ($env:INSTALL_DIR) { $env:INSTALL_DIR } else { Join-Path (Get-Location) "voice-sandwich-demo" }
$WithLlm = -not $env:NO_LLM

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Has($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
        [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
        (Join-Path $HOME ".local\bin")
}
function Invoke-Checked {
    param([string]$Dir, [string]$Exe, [string[]]$Arguments)
    Push-Location $Dir
    try {
        & $Exe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "'$Exe $Arguments' failed in $Dir" }
    } finally { Pop-Location }
}
function Winget-Install($id) {
    if (-not (Has "winget")) {
        throw "winget is missing. Install 'App Installer' from the Microsoft Store, or install $id by hand."
    }
    winget install --id $id -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
}

Step "Checking system tools"
if (-not (Has "git")) { Step "Installing Git"; Winget-Install "Git.Git" }
$nodeOk = (Has "node") -and ([int](node -p "process.versions.node.split('.')[0]") -ge 18)
if (-not $nodeOk) { Step "Installing Node.js (LTS)"; Winget-Install "OpenJS.NodeJS.LTS" }
if (-not (Has "uv")) {
    Step "Installing uv (Python package manager)"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Refresh-Path
}
if (-not (Has "pnpm")) {
    Step "Installing pnpm"
    corepack enable pnpm 2>$null
    if (-not (Has "pnpm")) { npm install -g pnpm }
    Refresh-Path
}

Step "Downloading the application to $InstallDir"
if (Test-Path (Join-Path $InstallDir ".git")) {
    Invoke-Checked $InstallDir "git" @("pull", "--ff-only")
} else {
    git clone --branch $Branch $RepoUrl $InstallDir
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
}

Step "Installing packages"
Invoke-Checked (Join-Path $InstallDir "components\web") "pnpm" @("install")
Invoke-Checked (Join-Path $InstallDir "components\typescript") "pnpm" @("install")
Invoke-Checked (Join-Path $InstallDir "components\python") "uv" @("sync", "--dev")
$envFile = Join-Path $InstallDir ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $InstallDir ".env.example") $envFile
    Write-Host "Created .env from .env.example"
}

Step "Building the web pages"
Invoke-Checked (Join-Path $InstallDir "components\web") "pnpm" @("build")

if ($WithLlm) {
    if (-not (Has "ollama")) { Step "Installing Ollama (local LLM runtime)"; Winget-Install "Ollama.Ollama" }
    try { Invoke-RestMethod http://localhost:11434/api/version | Out-Null } catch {
        Step "Starting Ollama"
        Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
        foreach ($i in 1..30) {
            try { Invoke-RestMethod http://localhost:11434/api/version | Out-Null; break } catch { Start-Sleep 1 }
        }
    }
    $model = (Select-String -Path $envFile -Pattern "^OLLAMA_MODEL=(.+)$" | Select-Object -First 1).Matches.Groups[1].Value
    if (-not $model) { $model = "qwen3.5:4b" }
    Step "Downloading the local model $model (about 4 GB)"
    ollama pull $model
    if ($LASTEXITCODE -ne 0) { throw "ollama pull failed" }
}

Write-Host @"

==> Installed.

Next steps:
  cd "$InstallDir"
  .\run.ps1 set-admin-password   # set the desk admin password
  .\run.ps1 start                # start the server (Ctrl+C or '.\run.ps1 stop' stops it)

Then open http://localhost:8000/desk/, log in as "admin", and add your API
keys in Settings -> API Keys (Gemini is the default voice model).
Guide: components\install-doc.md
"@
