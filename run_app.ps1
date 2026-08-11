param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

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

    & $PythonPath -m venv (Join-Path $PSScriptRoot ".venv")
}

& $venvPython -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
& $venvPython -m streamlit run (Join-Path $PSScriptRoot "app.py")
