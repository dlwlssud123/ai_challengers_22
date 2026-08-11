param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$venvDirectory = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvDirectory "Scripts\python.exe"
$venvReady = $false

if (Test-Path $venvPython) {
    try {
        & $venvPython -c "import sys; print(sys.executable)" *> $null
        $venvReady = ($LASTEXITCODE -eq 0)
    } catch {
        $venvReady = $false
    }
}

if ((Test-Path $venvPython) -and -not $venvReady) {
    Write-Warning "기존 .venv가 사용할 수 없는 Python을 가리킵니다. .venv-rebuilt를 사용합니다."
    $venvDirectory = Join-Path $PSScriptRoot ".venv-rebuilt"
    $venvPython = Join-Path $venvDirectory "Scripts\python.exe"
}

if (-not (Test-Path $venvPython)) {
    if (-not $PythonPath) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        $pyCommand = Get-Command py -ErrorAction SilentlyContinue
        $streamlitCommand = Get-Command streamlit -ErrorAction SilentlyContinue

        if ($pythonCommand) {
            $PythonPath = $pythonCommand.Source
        } elseif ($pyCommand) {
            $PythonPath = $pyCommand.Source
        } elseif ($streamlitCommand) {
            $scriptsDirectory = Split-Path $streamlitCommand.Source
            $candidate = Join-Path (Split-Path $scriptsDirectory) "python.exe"
            if (Test-Path $candidate) {
                $PythonPath = $candidate
            }
        }
    }

    if (-not $PythonPath) {
        throw "Python을 찾지 못했습니다. .\run_app.ps1 -PythonPath 'C:\path\to\python.exe' 형식으로 실행해 주세요."
    }

    & $PythonPath -m venv $venvDirectory
}

& $venvPython -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
& $venvPython -m streamlit run (Join-Path $PSScriptRoot "app.py")
