# install-env.ps1 — venv 创建 + requirements 安装（幂等）
# 退出码：0 成功；3 环境/依赖错误
# 参数：-Mirror 使用清华 PyPI 镜像（国内网络推荐）
param([switch]$Mirror)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$SkillRoot = Split-Path -Parent $PSScriptRoot
$InfoJson  = Get-Content (Join-Path $SkillRoot 'info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$VenvName  = $InfoJson.venv_name
$VenvRoot  = Join-Path $env:USERPROFILE ".openvino\venvs\$VenvName"
$VenvPy    = Join-Path $VenvRoot 'Scripts\python.exe'

# 依赖钉在 numpy<2.0 等预编译轮子只覆盖到 cp312：必须用 3.10–3.12 建 venv，
# 否则 pip 会回退到源码编译（需要 C 编译器，极易失败）
$MinVer = [version]'3.10'
$MaxVer = [version]'3.12'

function Test-PyVersion([string[]]$Invoke) {
    try {
        $exe = $Invoke[0]
        $pre = @(); if ($Invoke.Count -gt 1) { $pre = $Invoke[1..($Invoke.Count-1)] }
        $v = & $exe @pre -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $v) { return $false }
        $ver = [version]"$v".Trim()
        return ($ver -ge $MinVer -and $ver -le $MaxVer)
    } catch { return $false }
}

try {
    # 1. 定位基础 Python：py 启动器指定版本优先，再验 PATH 上的 python 版本范围
    $BaseInvoke = $null
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @('-3.12', '-3.11', '-3.10')) {
            if (Test-PyVersion @('py', $v)) { $BaseInvoke = @('py', $v); break }
        }
    }
    if (-not $BaseInvoke) {
        foreach ($cand in @('python', 'python3')) {
            if ((Get-Command $cand -ErrorAction SilentlyContinue) -and (Test-PyVersion @($cand))) {
                $BaseInvoke = @($cand); break
            }
        }
    }
    if (-not $BaseInvoke) {
        Write-Error "No Python 3.10-3.12 found (newer versions lack prebuilt wheels for pinned deps). Install Python 3.12 from python.org, then re-run."
        exit 3
    }
    Write-Host "[install-env] base python: $($BaseInvoke -join ' ')"

    # 1b. 旧 venv 若由超出范围的 Python 创建，提示重建
    if ((Test-Path $VenvPy) -and -not (Test-PyVersion @($VenvPy))) {
        Write-Error "Existing venv uses unsupported Python. Delete it then re-run:  Remove-Item -Recurse -Force '$VenvRoot'"
        exit 3
    }

    # 2. 幂等创建 venv
    if (-not (Test-Path $VenvPy)) {
        Write-Host "[install-env] creating venv: $VenvRoot"
        $BaseExe = $BaseInvoke[0]
        $BasePre = @(); if ($BaseInvoke.Count -gt 1) { $BasePre = $BaseInvoke[1..($BaseInvoke.Count-1)] }
        & $BaseExe @BasePre -m venv $VenvRoot
        if ($LASTEXITCODE -ne 0) { Write-Error 'venv creation failed'; exit 3 }
    } else {
        Write-Host "[install-env] venv exists: $VenvRoot"
    }

    # 3. 安装依赖（requirements 内容 hash 作为完成标记，幂等 & 变更重装）
    $ReqFile  = Join-Path $SkillRoot 'requirements.txt'
    $ReqHash  = (Get-FileHash $ReqFile -Algorithm SHA256).Hash
    $Sentinel = Join-Path $VenvRoot '.req.hash'
    $Installed = (Test-Path $Sentinel) -and ((Get-Content $Sentinel -Raw).Trim() -eq $ReqHash)

    if (-not $Installed) {
        Write-Host '[install-env] installing requirements ...'
        # 隔离全局 pip 配置：屏蔽 pip.ini 的 target= / PIP_TARGET / PYTHONPATH，
        # 否则包会装进外部目录而非 venv（报 Target directory already exists）
        $env:PIP_CONFIG_FILE = 'nul'
        $env:PYTHONNOUSERSITE = '1'
        Remove-Item Env:PIP_TARGET, Env:PIP_PREFIX, Env:PIP_USER, Env:PYTHONPATH -ErrorAction SilentlyContinue
        # 只装预编译轮子，禁止源码编译；加大超时与重试应对弱网
        $PipArgs = @('--only-binary', ':all:', '--timeout', '120', '--retries', '10')
        if ($Mirror) {
            $PipArgs += @('-i', 'https://pypi.tuna.tsinghua.edu.cn/simple')
            Write-Host '[install-env] using tsinghua mirror'
        }
        # 本地 wheels/ 优先（离线安装），否则走 PyPI/镜像
        $Wheels = Join-Path $SkillRoot 'wheels'
        if (Test-Path $Wheels) {
            & $VenvPy -m pip install --find-links $Wheels @PipArgs -r $ReqFile
        } else {
            & $VenvPy -m pip install @PipArgs -r $ReqFile
        }
        if ($LASTEXITCODE -ne 0) { Write-Error 'pip install failed'; exit 3 }
        # 安装验证：核心包必须能从 venv 里 import，防止装歪后误写完成标记
        & $VenvPy -c "import openvino, openvino_genai, chromadb, mcp, fitz, optimum"
        if ($LASTEXITCODE -ne 0) {
            Write-Error 'install verification failed: core packages not importable from venv (check pip.ini target= / PIP_TARGET env)'
            exit 3
        }
        Set-Content -Path $Sentinel -Value $ReqHash -Encoding ASCII
    } else {
        Write-Host '[install-env] requirements up-to-date, skip'
    }

    Write-Host "[install-env] OK: $VenvPy"
    exit 0
}
catch {
    Write-Error "[install-env] failed: $_"
    exit 3
}
