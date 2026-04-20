@echo off
REM Reinicia daphne en Windows CMD / PowerShell.
REM   restart_daphne.bat           -> puerto 8000
REM   restart_daphne.bat 8080      -> puerto custom
setlocal enabledelayedexpansion

set PORT=%1
if "%PORT%"=="" set PORT=8000
set HOST=0.0.0.0

cd /d "%~dp0"

echo [restart-daphne] Buscando procesos daphne en puerto %PORT%...

REM Kill por puerto (cualquier proceso LISTEN en :PORT)
for /f "tokens=5" %%P in ('netstat -aon ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    echo [restart-daphne] Matando PID %%P
    taskkill /F /PID %%P >nul 2>&1
)

REM Kill cualquier daphne huerfano
taskkill /F /IM daphne.exe >nul 2>&1

timeout /t 1 /nobreak >nul

REM Activar venv
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo [restart-daphne] WARNING: no encontre .venv
)

echo [restart-daphne] Levantando daphne en %HOST%:%PORT%...
echo [restart-daphne] Ctrl+C para detener.
echo.

daphne -b %HOST% -p %PORT% fastchatdj.asgi:application

endlocal
