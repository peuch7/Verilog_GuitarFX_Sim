# wavsim.ps1 - Windows entry point.
#
# Runs everything inside the Linux container, so no simulator has to be
# installed on Windows (Verilator has no usable native Windows build).
#
#   .\wavsim.ps1 setup
#   .\wavsim.ps1 run --effect delay --param mix=0.5
#   .\wavsim.ps1 test
#   .\wavsim.ps1 shell
#
# Requires Docker Desktop with the WSL2 backend. If you use VS Code, "Reopen in
# Container" gives the same environment with a working terminal and editor.

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = "help",

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Compose = Join-Path $RepoRoot "docker/compose.yml"

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "Docker was not found." -ForegroundColor Red
        Write-Host "Install Docker Desktop (WSL2 backend): https://docs.docker.com/desktop/install/windows-install/"
        exit 1
    }
    try { docker info *> $null } catch {
        Write-Host "Docker is installed but not running. Start Docker Desktop and try again." -ForegroundColor Red
        exit 1
    }
}

function Invoke-Sim {
    param([string[]]$Arguments)
    docker compose -f $Compose run --rm sim @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Command.ToLower()) {
    "setup" {
        Assert-Docker
        Write-Host "Building the container (first run takes a few minutes)..." -ForegroundColor Cyan
        docker compose -f $Compose build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Invoke-Sim @("python3", "scripts/doctor.py")
        Write-Host ""
        Write-Host "Ready. Try:  .\wavsim.ps1 run --effect delay" -ForegroundColor Green
    }
    "shell" {
        Assert-Docker
        Invoke-Sim @("bash")
    }
    "test" {
        Assert-Docker
        Invoke-Sim (@("python3", "-m", "pytest") + $Rest)
    }
    "make" {
        Assert-Docker
        Invoke-Sim (@("make") + $Rest)
    }
    "help" {
        Write-Host @"
wavsim.ps1 - run the VerilogSim harness on Windows, inside the container.

  .\wavsim.ps1 setup                       build the container and check it
  .\wavsim.ps1 run --effect delay          wav -> effect -> wav
  .\wavsim.ps1 compare --effect delay      RTL vs the reference model
  .\wavsim.ps1 list                        what effects exist
  .\wavsim.ps1 test                        run the test suite
  .\wavsim.ps1 shell                       an interactive shell in the container
  .\wavsim.ps1 make <target>               run a Makefile target

Any other command is passed straight to the wavsim CLI, so
'.\wavsim.ps1 info delay' works too. Output wav files appear in audio\output.

Tip: keep this repository inside the WSL2 filesystem rather than on C:\ .
Bind mounts across the Windows boundary are far slower, which is very
noticeable on long clips. See docs/getting_started.md.
"@
    }
    default {
        # Anything else is a wavsim subcommand.
        Assert-Docker
        Invoke-Sim (@("wavsim", $Command) + $Rest)
    }
}
