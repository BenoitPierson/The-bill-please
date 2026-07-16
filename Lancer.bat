@echo off
cd /d "%~dp0"

rem Le venv a ete cree a partir de l'Anaconda du dossier utilisateur ; sans ses
rem dossiers de DLL (OpenSSL, etc.) dans le PATH, Python plante au demarrage
rem avec "DLL load failed while importing _ssl" quand ce script est lance
rem directement depuis l'explorateur (hors invite Anaconda).
set "PATH=%USERPROFILE%\anaconda3;%USERPROFILE%\anaconda3\Library\mingw-w64\bin;%USERPROFILE%\anaconda3\Library\usr\bin;%USERPROFILE%\anaconda3\Library\bin;%USERPROFILE%\anaconda3\Scripts;%USERPROFILE%\anaconda3\condabin;%PATH%"

rem Si une ancienne instance de l'outil (processus Python) occupe encore le
rem port 8000, on la ferme, sinon le serveur plante avec "error 10048".
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    tasklist /fi "pid eq %%p" | findstr /i "python.exe" >nul && taskkill /f /pid %%p >nul 2>&1
)

echo Demarrage de l'outil d'extraction de factures...
start "" /min cmd /c "%~dp0open_browser.bat"
".venv\Scripts\python.exe" app.py
echo.
echo Le serveur est arrete.
pause
