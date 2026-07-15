@echo off
cd /d "%~dp0"
echo Demarrage de l'outil d'extraction de factures...
start "" /min cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"
".venv\Scripts\python.exe" app.py
echo.
echo Le serveur est arrete.
pause
