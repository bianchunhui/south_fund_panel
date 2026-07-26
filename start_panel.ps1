$dir  = 'C:\Users\chunh\ZCodeProject\south_fund_panel'
$py   = 'C:\Users\chunh\.workbuddy\binaries\python\envs\akshare\Scripts\python.exe'
$port = 8701
$log  = Join-Path $dir 'start_panel.log'

$ErrorActionPreference = 'Stop'

# kill a whole process tree (root + all descendants) by PID
function Stop-Tree($pidv) {
    if (-not $pidv) { return }
    try { taskkill.exe /F /T /PID $pidv 2>$null } catch {}
}

try {
    Set-Content -Path $log -Value 'start' -Encoding utf8
    Set-Location -Path $dir

    # precheck python / streamlit
    & $py -c 'import streamlit' 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Add-Content -Path $log -Value 'py_err'
        Write-Host '[ERROR] Python or streamlit not found. See start_panel.log'
        Read-Host 'Press Enter to exit'
        exit 1
    }
    Add-Content -Path $log -Value 'py_ok'

    # kill stale OWN streamlit (only python procs) occupying the port, so a previous
    # orphaned server does not block the new launch. Foreign (non-python) procs are left alone.
    try {
        $occ = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        if ($occ) {
            $occ.OwningProcess | Sort-Object -Unique | ForEach-Object {
                $p = Get-Process -Id $_ -ErrorAction SilentlyContinue
                if ($p -and $p.Name -match 'python') { Stop-Tree $_ }
            }
            Start-Sleep -Seconds 1
            Add-Content -Path $log -Value 'killed_stale'
        }
    } catch {}

    # Launch streamlit inside a Job so this powershell owns the whole process tree
    # (python -m streamlit -> python -c bootstrap server). We can then kill it all on exit.
    Add-Content -Path $log -Value 'launching'
    $job = Start-Job -ScriptBlock {
        param($py, $script, $port)
        & $py -m streamlit run $script --server.port $port --server.headless true --browser.gatherUsageStats false
    } -ArgumentList $py, (Join-Path $dir 'panel.py'), $port

    $rootPid = $job.ChildJobs[0].Process.Id

    # On console close (click X) the engine exits -> this handler kills the entire
    # streamlit process tree, including the detached server child that would otherwise orphan.
    Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
        param($id)
        try { taskkill.exe /F /T /PID $id 2>$null } catch {}
    } -MessageData $rootPid | Out-Null

    Add-Content -Path $log -Value "job_pid_$rootPid"
    Write-Host "[INFO] Southbound Capital Monitor starting on http://localhost:$port"
    Write-Host "[INFO] Streamlit job PID: $rootPid  |  Close this window to stop the service."

    # wait for port, then open browser
    $ready = $false
    for ($i = 1; $i -le 60; $i++) {
        if (Test-NetConnection -ComputerName localhost -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if ($ready) {
        Add-Content -Path $log -Value 'ready'
        Write-Host "[INFO] Ready - opening browser"
        Start-Process "http://localhost:$port"
    } else {
        Add-Content -Path $log -Value 'timeout'
        Write-Host "[ERROR] Start timeout (120s). Check start_panel.log or run manually:"
        Write-Host "  $py -m streamlit run panel.py --server.port $port --server.headless true"
        Read-Host 'Press Enter to exit'
    }

    # Keep THIS powershell alive so the window stays open and the exit-handler is armed.
    # Closing the window triggers PowerShell.Exiting -> the whole streamlit tree is killed.
    Write-Host "[INFO] Running. Close this window to stop the service."
    Wait-Job $job
} catch {
    Add-Content -Path $log -Value "exception: $_"
    Write-Host "[EXCEPTION] $_"
    Read-Host 'Press Enter to exit'
}
