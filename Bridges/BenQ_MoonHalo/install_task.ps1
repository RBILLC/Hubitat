<#
.SYNOPSIS
    Registers the MoonHalo Bridge as a logon-triggered Scheduled Task, or removes it.

.DESCRIPTION
    Creates a task named MoonHaloBridge that runs run_bridge.cmd (next to this script) when you
    log on, only while you are logged on, as your ordinary user, with three automatic restarts a
    minute apart and no run-time limit. The Bridge must run in your interactive session because
    the monitor API it uses is not available to Windows services (session 0); see the README.

    Creating a Scheduled Task needs administrator rights, so the script re-launches itself
    elevated if necessary and passes your account name through so the task still runs as you.
    The account is named in DOMAIN\user form (for example RBILLC\RBILLC), which Task Scheduler
    requires for Microsoft-account logins. If the PowerShell cmdlet still rejects the account,
    the script falls back to schtasks.exe.

.PARAMETER Uninstall
    Remove the task instead of creating it.

.PARAMETER User
    The account the task runs as, in DOMAIN\user form. Defaults to the account running the
    script; filled in automatically when the script re-launches itself elevated.

.PARAMETER NoStart
    Register the task but do not start it now.

.EXAMPLE
    .\install_task.ps1
    .\install_task.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$User = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
    [switch]$NoStart,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$TaskName = "MoonHaloBridge"
$Port = 5000

function Pause-IfInteractive {
    if (-not $NoPause -and $Host.Name -eq "ConsoleHost") { Read-Host "Press Enter to close" | Out-Null }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Administrator rights are needed to create or remove a Scheduled Task; re-launching elevated..."
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-User", "`"$User`"")
    if ($Uninstall) { $argList += "-Uninstall" }
    if ($NoStart) { $argList += "-NoStart" }
    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argList -Wait
    exit
}

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed the $TaskName task."
    } else {
        Write-Host "No $TaskName task was registered."
    }
    Pause-IfInteractive
    exit
}

$launcher = Join-Path $PSScriptRoot "run_bridge.cmd"
if (-not (Test-Path $launcher)) { throw "Launcher not found: $launcher" }
if (-not (Test-Path (Join-Path $PSScriptRoot "config.json"))) {
    Write-Warning "No config.json next to the launcher. Copy config.example.json to config.json and edit it, or the Bridge will start with defaults and an open allowlist."
}

$registered = $false
try {
    $action    = New-ScheduledTaskAction -Execute $launcher -WorkingDirectory $PSScriptRoot
    $trigger   = New-ScheduledTaskTrigger -AtLogOn -User $User
    $settings  = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
    $registered = $true
    Write-Host "Registered the $TaskName task: runs $launcher at logon as $User, restarts up to 3 times on failure."
} catch {
    Write-Warning "Register-ScheduledTask refused the account '$User' ($($_.Exception.Message.Trim())); trying schtasks.exe instead."
    $tr = "`"$launcher`""
    & schtasks.exe /create /f /tn $TaskName /tr $tr /sc onlogon /ru $User /rl LIMITED /it | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "schtasks.exe could not create the task (exit code $LASTEXITCODE)." }
    # schtasks cannot set restart-on-failure or clear the run-time limit; apply those to the created task.
    $settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Set-ScheduledTask -TaskName $TaskName -Settings $settings -ErrorAction SilentlyContinue | Out-Null
    $registered = $true
    Write-Host "Registered the $TaskName task with schtasks.exe: runs $launcher at logon as $User."
}

if ($registered -and -not $NoStart) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        Write-Warning "Something is already listening on port $Port (process id $($listener.OwningProcess)). Stop it, then run: schtasks /run /tn $TaskName"
    } else {
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 3
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
            if ($health.ok) { Write-Host "The Bridge is running: http://127.0.0.1:$Port/health answered ok." }
        } catch {
            Write-Warning "The task started but the Bridge did not answer on port $Port yet. Check the log file named in config.json, or run 'py -m moonhalo_bridge serve' by hand to see errors."
        }
    }
}

Pause-IfInteractive
