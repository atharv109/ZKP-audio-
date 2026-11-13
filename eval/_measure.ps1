#!/usr/bin/env pwsh
# eval/_measure.ps1 -- run one command; measure wall time + peak working set
# (MB) of node/python processes STARTED during the measurement window.
#
# Output: one JSON line on stdout:
#   {"exit": n, "ms": n, "peak_node_mb": n, "peak_python_mb": n}
# exit = -1000 if the process could not be started at all. A fast child that
# exits before the first poll contributes peak 0 (a lower bound).
#
# Attribution: only processes whose StartTime >= measurement start are
# sampled, excluding long-lived pre-existing node/python (e.g. MCP servers).
# Peak = max over polls of WorkingSet64 (NOT lifetime PeakWorkingSet64,
# which would be contaminated by pre-existing processes).
param(
    [Parameter(Mandatory=$true)][string]$Exe,
    [Parameter(Mandatory=$true)][string]$ArgList,
    [string]$WorkDir = (Get-Location).Path,
    [Parameter(Mandatory=$true)][string]$StdoutFile,
    [Parameter(Mandatory=$true)][string]$StderrFile
)
$ErrorActionPreference = 'SilentlyContinue'

$startWall = Get-Date
$sw = [System.Diagnostics.Stopwatch]::StartNew()

$p = Start-Process -FilePath $Exe -ArgumentList $ArgList `
        -WorkingDirectory $WorkDir -NoNewWindow -PassThru `
        -RedirectStandardOutput $StdoutFile -RedirectStandardError $StderrFile
if ($null -eq $p) {
    Write-Output '{"exit": -1000, "ms": 0, "peak_node_mb": 0, "peak_python_mb": 0}'
    exit 0
}
$null = $p.Handle  # force handle creation early (PS 5.1 ExitCode-null workaround)
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ExitReader {
    [DllImport("kernel32.dll", SetLastError=false)]
    public static extern bool GetExitCodeProcess(IntPtr hProcess, out Int32 lpExitCode);
}
"@

$peakNode = 0.0
$peakPy = 0.0
while (-not $p.HasExited) {
    Start-Sleep -Milliseconds 500
    $procs = Get-Process node, python, python3.12 -ErrorAction SilentlyContinue
    foreach ($proc in $procs) {
        try {
            if ($proc.StartTime -ge $startWall) {
                $ws = $proc.WorkingSet64 / 1MB
                if ($proc.Name -eq 'node') {
                    if ($ws -gt $peakNode) { $peakNode = $ws }
                } else {
                    if ($ws -gt $peakPy) { $peakPy = $ws }
                }
            }
        } catch { continue }
    }
}

$t0 = $sw.Elapsed.TotalMilliseconds
[void]$p.WaitForExit()
[int]$exitCode = 258  # STILL_ACTIVE sentinel
if (-not [ExitReader]::GetExitCodeProcess($p.Handle, [ref]$exitCode)) {
    $exitCode = -1002
}
$json = '{"exit": ' + $exitCode + ', "ms": ' + [math]::Round($t0) + ', "peak_node_mb": ' + [math]::Round($peakNode, 1) + ', "peak_python_mb": ' + [math]::Round($peakPy, 1) + '}'
Write-Output $json