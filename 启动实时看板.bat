@echo off
cd /d "%~dp0"

set "CODEX_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PYTHONPATH=%~dp0..\.pydeps"

if exist "%CODEX_PY%" (
  "%CODEX_PY%" -c "import unicodedata" >nul 2>nul
  if errorlevel 1 (
    echo Codex Python runtime is being updated. Starting with the existing local data cache.
  ) else (
    "%CODEX_PY%" build_flow_periods.py
    "%CODEX_PY%" build_flow_history.py
    "%CODEX_PY%" build_index_weights.py
  )
  "%CODEX_PY%" server.py --open
  goto :end
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 build_flow_periods.py
  py -3 build_flow_history.py
  py -3 build_index_weights.py
  py -3 server.py --open
  goto :end
)

where python >nul 2>nul
if not errorlevel 1 (
  python build_flow_periods.py
  python build_flow_history.py
  python build_index_weights.py
  python server.py --open
  goto :end
)

echo Python 3 was not found.
echo Please install Python 3 or run this project inside Codex.

:end
pause
