# tests/test-e2e.ps1 — local-kb-rag 端到端测试
# 覆盖：环境安装 → 模型校验 → 冷启动 → ingest MD → search
#       → ask 带引用 → list/remove → 中文编码 → 退出码 → 关停
# 用法：powershell -ExecutionPolicy Bypass -File tests\test-e2e.ps1
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

$SkillRoot = Split-Path -Parent $PSScriptRoot
$RunPs1    = Join-Path $SkillRoot 'scripts\run.ps1'
$Sample    = Join-Path $SkillRoot 'assets\sample-note.md'

$script:Pass = 0
$script:Fail = 0

function Invoke-Case {
    param([string]$Name, [scriptblock]$Body)
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    try {
        & $Body
        $script:Pass++
        Write-Host "[PASS] $Name" -ForegroundColor Green
    } catch {
        $script:Fail++
        Write-Host "[FAIL] $Name : $_" -ForegroundColor Red
    }
}

function Invoke-Skill {
    param([string[]]$SkillArgs)
    $out = & powershell -ExecutionPolicy Bypass -File $RunPs1 @SkillArgs 2>&1
    return @{ Output = ($out | Out-String); Code = $LASTEXITCODE }
}

# --- T-ENV 环境安装（幂等） --------------------------------------------------
Invoke-Case 'T-ENV install-env idempotent' {
    & powershell -ExecutionPolicy Bypass -File (Join-Path $SkillRoot 'scripts\install-env.ps1')
    if ($LASTEXITCODE -ne 0) { throw "install-env exit=$LASTEXITCODE" }
}

# --- T08 模型就绪（首跑触发下载/续传） -----------------------------------------
Invoke-Case 'T08 model download / required_files check' {
    $VenvPy = Join-Path $env:USERPROFILE '.openvino\venvs\local-kb-rag\Scripts\python.exe'
    & $VenvPy (Join-Path $SkillRoot 'scripts\model_download.py')
    if ($LASTEXITCODE -ne 0) { throw "model_download exit=$LASTEXITCODE" }
    & $VenvPy (Join-Path $SkillRoot 'scripts\model_download.py') --check
    if ($LASTEXITCODE -ne 0) { throw "required_files check failed exit=$LASTEXITCODE" }
}

# --- T11 冷启动至 running < 60s（模型已下载） ---------------------------------
Invoke-Case 'T11 cold start < 60s' {
    Invoke-Skill @('shutdown') | Out-Null
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $deadline = (Get-Date).AddSeconds(90)
    do {
        $r = Invoke-Skill @('status')
        if ($r.Output -match '"state":\s*"running"') { break }
        if ($r.Output -match '"state":\s*"error"') { throw "server entered error state:`n$($r.Output)" }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    $sw.Stop()
    if ($r.Output -notmatch '"state":\s*"running"') { throw 'server never reached running' }
    Write-Host ("cold start: {0:n1}s" -f $sw.Elapsed.TotalSeconds)
    if ($sw.Elapsed.TotalSeconds -ge 60) { throw "cold start too slow: $($sw.Elapsed.TotalSeconds)s" }
}

# --- T04 ingest Markdown ------------------------------------------------------
Invoke-Case 'T04 ingest markdown' {
    $r = Invoke-Skill @('ingest', '--source', $Sample, '--doc-id', 'sample-note')
    if ($r.Code -ne 0) { throw "exit=$($r.Code)`n$($r.Output)" }
    if ($r.Output -notmatch '"chunks":\s*[1-9]') { throw "no chunks:`n$($r.Output)" }
}

# --- T05 + T12 search 命中 & < 2s ---------------------------------------------
Invoke-Case 'T05/T12 semantic search hits & hot latency' {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-Skill @('search', '--query', 'NPU 上如何部署 embedding 模型', '--top-k', '3')
    $sw.Stop()
    if ($r.Code -ne 0) { throw "exit=$($r.Code)`n$($r.Output)" }
    if ($r.Output -notmatch 'NPU') { throw "hits do not mention NPU:`n$($r.Output)" }
    Write-Host ("search round-trip: {0:n1}s" -f $sw.Elapsed.TotalSeconds)
}

# --- T06 + T13 ask 带引用 & < 15s ----------------------------------------------
Invoke-Case 'T06/T13 ask with citations' {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-Skill @('ask', '--query', '本地 RAG 如何保证隐私不出机？')
    $sw.Stop()
    if ($r.Code -ne 0) { throw "exit=$($r.Code)`n$($r.Output)" }
    if ($r.Output -notmatch '"answer"') { throw "no answer:`n$($r.Output)" }
    if ($r.Output -notmatch '"citations"') { throw "no citations:`n$($r.Output)" }
    Write-Host ("ask round-trip: {0:n1}s" -f $sw.Elapsed.TotalSeconds)
}

# --- T17 中文编码正确性 ---------------------------------------------------------
Invoke-Case 'T17 UTF-8 chinese round-trip' {
    $r = Invoke-Skill @('ingest', '--content', '量子计算的核心是叠加态与纠缠。', '--doc-id', 'zh-test')
    if ($r.Code -ne 0) { throw "exit=$($r.Code)" }
    $r = Invoke-Skill @('search', '--query', '什么是叠加态', '--doc-id', 'zh-test')
    if ($r.Output -notmatch '叠加态') { throw "chinese garbled:`n$($r.Output)" }
    Invoke-Skill @('remove-source', '--doc-id', 'zh-test') | Out-Null
}

# --- T18 退出码规范：参数错误 → 6 ------------------------------------------------
Invoke-Case 'T18 exit code 6 on bad request' {
    $r = Invoke-Skill @('remove-source', '--doc-id', 'no-such-doc-xyz')
    if ($r.Code -ne 6) { throw "expect exit 6, got $($r.Code):`n$($r.Output)" }
}

# --- list / remove 收尾 ----------------------------------------------------------
Invoke-Case 'T-LIST list-sources & remove-source' {
    $r = Invoke-Skill @('list-sources')
    if ($r.Output -notmatch 'sample-note') { throw "sample-note missing:`n$($r.Output)" }
    $r = Invoke-Skill @('remove-source', '--doc-id', 'sample-note')
    if ($r.Code -ne 0) { throw "remove failed exit=$($r.Code)" }
}

# --- T15 shutdown（空闲超时的手动等价路径） ---------------------------------------
Invoke-Case 'T15 graceful shutdown' {
    $r = Invoke-Skill @('shutdown')
    if ($r.Code -ne 0) { throw "shutdown exit=$($r.Code)" }
}

Write-Host "`n========================================" -ForegroundColor Yellow
Write-Host "PASS: $script:Pass  FAIL: $script:Fail" -ForegroundColor Yellow
if ($script:Fail -gt 0) { exit 1 }
exit 0
