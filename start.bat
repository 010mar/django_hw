@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

".venv\Scripts\python.exe" manage.py migrate --noinput || goto :error

echo.
echo Site will be available at http://127.0.0.1:8000/
echo Press Ctrl+C to stop the server.
echo.

start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000/"
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
goto :eof

:error
echo.
echo Failed to start the site. See the error above.
pause
