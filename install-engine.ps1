$ErrorActionPreference = "Stop"
$TransYHRoot = $PSScriptRoot
$TransYHUv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $TransYHUv) {
    Write-Host "请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/"
    Write-Host "可使用 winget install --id=astral-sh.uv -e，然后重新运行此脚本。"
    exit 1
}
$TransYHEngine = Join-Path $env:LOCALAPPDATA "TransYH\engine"
& $TransYHUv.Source venv --python 3.12 --allow-existing $TransYHEngine
if ($LASTEXITCODE -ne 0) { throw "创建 Python 环境失败" }
$TransYHPython = Join-Path $TransYHEngine "Scripts\python.exe"
& $TransYHUv.Source pip install --python $TransYHPython -r (Join-Path $TransYHRoot "engine\requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "安装 BabelDOC 失败" }
'{"action":"check"}' | & $TransYHPython (Join-Path $TransYHRoot "engine\worker.py") --stdio
if ($LASTEXITCODE -ne 0) { throw "引擎检测未通过" }
Write-Host "安装完成。Zotero 设置 → TransYH → 检测本地引擎。首次翻译会下载模型和字体。"
