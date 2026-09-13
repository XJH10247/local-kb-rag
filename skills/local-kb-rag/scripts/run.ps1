# run.ps1 — local-kb-rag 固定入口（不可改名）
# 流程：硬件检测 → 确保 venv 环境 → 启动 cli.py（透传全部参数）
# 退出码：0 成功；2 非 AIPC；3 环境错误；4 下载失败；5 server 不可用；6 参数错误
#
# 用法示例：
#   .\run.ps1 status
#   .\run.ps1 ingest --source "C:\notes\spec.pdf"
#   .\run.ps1 search --query "OpenVINO 如何部署到 NPU"
#   .\run.ps1 ask --query "本方案如何保证隐私不出机？"
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
# 隔离全局 Python 环境污染：PYTHONPATH 指向外部包目录时会遮蔽 venv 里的包
$env:PYTHONNOUSERSITE = '1'
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue

$SkillRoot = Split-Path -Parent $PSScriptRoot
$InfoJson  = Get-Content (Join-Path $SkillRoot 'info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$VenvPy    = Join-Path $env:USERPROFILE ".openvino\venvs\$($InfoJson.venv_name)\Scripts\python.exe"

# --- 1. 硬件检测：内存预算 -------------------------------------------------
$TotalGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
if ($TotalGB -lt $InfoJson.mem_need_gb) {
    Write-Error "[run] insufficient memory: ${TotalGB}GB < $($InfoJson.mem_need_gb)GB required"
    exit 2
}

# --- 2. 确保 venv 环境（幂等） ----------------------------------------------
if (-not (Test-Path $VenvPy)) {
    & (Join-Path $PSScriptRoot 'install-env.ps1')
    if ($LASTEXITCODE -ne 0) { exit 3 }
}

# --- 3. 硬件检测：OpenVINO device（venv 就绪后才能查） -----------------------
$Devices = & $VenvPy -c "import openvino; print(','.join(openvino.Core().available_devices))" 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Devices)) {
    Write-Error '[run] no OpenVINO device available (not an AIPC?)'
    exit 2
}
Write-Host "[run] OpenVINO devices: $Devices"

# --- 4. 启动 client（透传全部参数，透传退出码） -------------------------------
& $VenvPy (Join-Path $PSScriptRoot 'cli.py') @args
exit $LASTEXITCODE
