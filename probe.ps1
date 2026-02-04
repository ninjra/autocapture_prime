$root = $env:AUTOCAPTURE_ROOT
if ([string]::IsNullOrWhiteSpace($root)) { $root = $PSScriptRoot }
if ([string]::IsNullOrWhiteSpace($root) -and -not [string]::IsNullOrWhiteSpace($PSCommandPath)) {
    $root = Split-Path -Parent $PSCommandPath
}
if ([string]::IsNullOrWhiteSpace($root)) { throw "AUTOCAPTURE_ROOT not set; run via probe.cmd" }
$tool = Join-Path $root "tools\vllm_foreground_probe.ps1"
function Escape-Arg {
    param([string]$Arg)
    if ($Arg -match '[\s"]') {
        return '"' + ($Arg -replace '"', '`"') + '"'
    }
    return $Arg
}

function Invoke-ToolWithSpinner {
    param(
        [string]$File,
        [string[]]$Args
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "powershell"
    $argList = @("-NoProfile","-ExecutionPolicy","Bypass","-File",$File) + @($Args)
    $psi.Arguments = ($argList | ForEach-Object { Escape-Arg $_ }) -join " "
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi

    $script:lastActivity = Get-Date
    $script:spinnerActive = $false
    $handler = [System.Diagnostics.DataReceivedEventHandler]{
        param($sender, $e)
        if ($null -ne $e.Data) {
            if ($script:spinnerActive) {
                Write-Host "`r" -NoNewline
                $script:spinnerActive = $false
            }
            Write-Host $e.Data
            $script:lastActivity = Get-Date
        }
    }

    $null = $p.Start()
    $p.add_OutputDataReceived($handler)
    $p.add_ErrorDataReceived($handler)
    $p.BeginOutputReadLine()
    $p.BeginErrorReadLine()

    $spin = @("|","/","-","\\")
    $dots = @(".","..","...")
    $i = 0
    while (-not $p.HasExited) {
        $idle = (Get-Date) - $script:lastActivity
        if ($idle.TotalMilliseconds -gt 600) {
            $ch = $spin[$i % $spin.Count]
            $dot = $dots[$i % $dots.Count]
            Write-Host -NoNewline "`r[$ch] working$dot"
            $script:spinnerActive = $true
            $i++
        }
        Start-Sleep -Milliseconds 200
    }
    if ($script:spinnerActive) { Write-Host "`r" }
    $p.WaitForExit()
    try {
        $p.CancelOutputRead()
        $p.CancelErrorRead()
    } catch {
    }
    $remainingOut = $p.StandardOutput.ReadToEnd()
    $remainingErr = $p.StandardError.ReadToEnd()
    if ($remainingOut) {
        if ($script:spinnerActive) { Write-Host "`r" -NoNewline; $script:spinnerActive = $false }
        Write-Host $remainingOut.TrimEnd()
    }
    if ($remainingErr) {
        if ($script:spinnerActive) { Write-Host "`r" -NoNewline; $script:spinnerActive = $false }
        Write-Host $remainingErr.TrimEnd()
    }
    return $p.ExitCode
}

$code = Invoke-ToolWithSpinner -File $tool -Args $args
exit $code
