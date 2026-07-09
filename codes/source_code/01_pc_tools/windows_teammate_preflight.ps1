param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$BoardHost = $(if ($env:BOARD_HOST) { $env:BOARD_HOST } else { "172.20.10.2" }),
  [string]$VmHost = $(if ($env:VM_SSH_HOST) { $env:VM_SSH_HOST } else { "192.168.247.129" }),
  [string]$VmUser = $(if ($env:VM_SSH_USER) { $env:VM_SSH_USER } else { "ebaina" }),
  [string]$VmPassword = $(if ($env:VM_SSH_PASSWORD) { $env:VM_SSH_PASSWORD } else { "ebaina" }),
  [switch]$CreateVenv,
  [switch]$InstallPythonDeps,
  [switch]$SkipNetworkProbes
)

$ErrorActionPreference = "Continue"
$results = New-Object System.Collections.Generic.List[object]
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$artifactDir = Join-Path $RepoRoot "artifacts\teammate_preflight"
$logPath = Join-Path $artifactDir "preflight_$stamp.log"
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null

function Write-Section($title) {
  Write-Host ""
  Write-Host "=== $title ==="
}

function Add-Result($Name, $Status, $Detail) {
  $results.Add([pscustomobject]@{ Name = $Name; Status = $Status; Detail = $Detail }) | Out-Null
  Write-Host ("[{0}] {1} - {2}" -f $Status, $Name, $Detail)
}

function Test-CommandExists($name) {
  return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Invoke-Capture($scriptBlock) {
  try {
    & $scriptBlock 2>&1 | Out-String
  } catch {
    $_.Exception.Message
  }
}

function Get-BasePython {
  if (Test-CommandExists "py") {
    $cmd = "py"
    $args = @("-3")
    $ver = Invoke-Capture { & $cmd @args --version }
    if ($LASTEXITCODE -eq 0 -or $ver -match "Python") {
      return @($cmd, $args)
    }
  }
  if (Test-CommandExists "python") {
    $cmd = "python"
    $ver = Invoke-Capture { & $cmd --version }
    if ($LASTEXITCODE -eq 0 -or $ver -match "Python") {
      return @($cmd, @())
    }
  }
  return $null
}

function Test-TcpPort($hostName, $port) {
  try {
    $client = New-Object Net.Sockets.TcpClient
    $iar = $client.BeginConnect($hostName, $port, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(2000, $false)
    if ($ok) {
      $client.EndConnect($iar)
      $client.Close()
      return $true
    }
    $client.Close()
    return $false
  } catch {
    return $false
  }
}

Write-Section "Repository"
if (Test-Path (Join-Path $RepoRoot "AGENTS.md")) {
  Add-Result "repo_root" "PASS" $RepoRoot
} else {
  Add-Result "repo_root" "FAIL" "AGENTS.md not found at $RepoRoot"
}

$requiredFiles = @(
  "tools\board_run.py",
  "tools\board_auto_ssh.py",
  "tools\vm_ssh_run.py",
  "tools\wifi_live_preview_control.py",
  "tools\wifi_sensor_suite_manager.py",
  "ros\parking_bridge"
)
foreach ($rel in $requiredFiles) {
  $path = Join-Path $RepoRoot $rel
  if (Test-Path $path) {
    Add-Result "required:$rel" "PASS" "present"
  } else {
    Add-Result "required:$rel" "FAIL" "missing"
  }
}

Write-Section "Python"
$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
  Add-Result "python_venv" "PASS" $venvPython
} else {
  Add-Result "python_venv" "WARN" ".venv missing"
  if ($CreateVenv) {
    $base = Get-BasePython
    if ($null -eq $base) {
      Add-Result "create_venv" "FAIL" "no base Python found; install Python 3.10+ first"
    } else {
      $cmd = $base[0]
      $args = @($base[1]) + @("-m", "venv", (Join-Path $RepoRoot ".venv"))
      $out = Invoke-Capture { & $cmd @args }
      if (Test-Path $venvPython) {
        Add-Result "create_venv" "PASS" ".venv created"
      } else {
        Add-Result "create_venv" "FAIL" $out.Trim()
      }
    }
  }
}

if (Test-Path $venvPython) {
  $version = Invoke-Capture { & $venvPython --version }
  Add-Result "python_version" "PASS" $version.Trim()

  if ($InstallPythonDeps) {
    $req = Join-Path $RepoRoot "requirements-windows.txt"
    if (Test-Path $req) {
      $out = Invoke-Capture { & $venvPython -m pip install -r $req }
      if ($LASTEXITCODE -eq 0) {
        Add-Result "pip_install" "PASS" "requirements-windows.txt installed"
      } else {
        Add-Result "pip_install" "FAIL" $out.Trim()
      }
    } else {
      Add-Result "pip_install" "FAIL" "requirements-windows.txt missing"
    }
  }

  $depCheck = Invoke-Capture { & $venvPython -c "import paramiko, serial, numpy; print('deps_ok')" }
  if ($depCheck -match "deps_ok") {
    Add-Result "python_deps" "PASS" "paramiko, pyserial, numpy import"
  } else {
    Add-Result "python_deps" "WARN" "missing deps; rerun with -InstallPythonDeps"
  }
} else {
  Add-Result "python_deps" "WARN" "skipped because .venv is missing"
}

Write-Section "USB and Serial"
try {
  $ports = [System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object
  if ($ports.Count -gt 0) {
    Add-Result "windows_com_ports" "PASS" ($ports -join ",")
  } else {
    Add-Result "windows_com_ports" "WARN" "no COM ports reported"
  }
} catch {
  Add-Result "windows_com_ports" "WARN" $_.Exception.Message
}

$usbMatches = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
  Where-Object {
    $_.InstanceId -match "VID_0483|VID_1A86|VID_10C4|VID_0403|VID_067B" -or
    $_.FriendlyName -match "STM|STLink|ST-Link|CH340|CH341|CP210|FTDI|Prolific|USB-SERIAL|USB Serial"
  } |
  Select-Object Status,Class,FriendlyName,InstanceId
if ($usbMatches) {
  Add-Result "usb_serial_devices" "PASS" (($usbMatches | Format-Table -AutoSize | Out-String).Trim())
} else {
  Add-Result "usb_serial_devices" "WARN" "no present ST-LINK/CH340/CP210/FTDI-like devices"
}

Write-Section "Network"
$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { $_.AddressState -eq "Preferred" } |
  Select-Object InterfaceAlias,IPAddress,PrefixLength
if ($ips) {
  Add-Result "windows_ipv4" "PASS" (($ips | Format-Table -AutoSize | Out-String).Trim())
} else {
  Add-Result "windows_ipv4" "WARN" "no preferred IPv4 addresses found"
}

if (-not $SkipNetworkProbes) {
  if (Test-TcpPort $BoardHost 22) {
    Add-Result "board_ssh_port" "PASS" "${BoardHost}:22 reachable"
  } else {
    Add-Result "board_ssh_port" "WARN" "${BoardHost}:22 not reachable; check board IP/Wi-Fi/Ethernet"
  }
  if (Test-TcpPort $VmHost 22) {
    Add-Result "vm_ssh_port" "PASS" "${VmHost}:22 reachable"
  } else {
    Add-Result "vm_ssh_port" "WARN" "${VmHost}:22 not reachable; check VM network"
  }
  foreach ($port in @(8766, 8765)) {
    if (Test-TcpPort $VmHost $port) {
      Add-Result "foxglove_ws_$port" "PASS" "ws://${VmHost}:$port reachable"
    } else {
      Add-Result "foxglove_ws_$port" "WARN" "ws://${VmHost}:$port not listening now"
    }
  }
}

Write-Section "Safe SSH Smoke Tests"
if ((Test-Path $venvPython) -and (-not $SkipNetworkProbes)) {
  $boardTool = Join-Path $RepoRoot "tools\board_run.py"
  if ((Test-Path $boardTool) -and (Test-TcpPort $BoardHost 22)) {
    $out = Invoke-Capture { & $venvPython $boardTool --host $BoardHost "hostname; whoami" }
    if ($LASTEXITCODE -eq 0) {
      Add-Result "board_safe_command" "PASS" $out.Trim()
    } else {
      Add-Result "board_safe_command" "WARN" $out.Trim()
    }
  }

  $vmTool = Join-Path $RepoRoot "tools\vm_ssh_run.py"
  if ((Test-Path $vmTool) -and (Test-TcpPort $VmHost 22)) {
    $out = Invoke-Capture { & $venvPython $vmTool --host $VmHost --user $VmUser --password $VmPassword run "hostname; whoami" }
    if ($LASTEXITCODE -eq 0) {
      Add-Result "vm_safe_command" "PASS" $out.Trim()
    } else {
      Add-Result "vm_safe_command" "WARN" $out.Trim()
    }
  }
}

Write-Section "Summary"
$results | Format-Table -AutoSize
$results | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $artifactDir "preflight_$stamp.json")
@"
Generated: $(Get-Date -Format o)
RepoRoot: $RepoRoot
BoardHost: $BoardHost
VmHost: $VmHost

$($results | Format-Table -AutoSize | Out-String)
"@ | Set-Content -Encoding UTF8 $logPath
Write-Host ""
Write-Host "LOG $logPath"

$failCount = ($results | Where-Object { $_.Status -eq "FAIL" }).Count
if ($failCount -gt 0) {
  exit 2
}
exit 0
