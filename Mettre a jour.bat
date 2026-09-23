@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Mise a jour de l'outil d'extraction de factures

echo ============================================================
echo   Recuperation de la derniere version
echo ============================================================
echo.

rem Git en ligne de commande, sinon celui livre avec GitHub Desktop.
set "GITEXE="
git --version >nul 2>&1 && set "GITEXE=git"
if not defined GITEXE (
    for /d %%D in ("%LOCALAPPDATA%\GitHubDesktop\app-*") do (
        if exist "%%D\resources\app\git\cmd\git.exe" set "GITEXE=%%D\resources\app\git\cmd\git.exe"
    )
)
if not defined GITEXE (
    echo [ECHEC] Git est introuvable sur cet ordinateur.
    echo Utilise GitHub Desktop : bouton "Fetch origin" puis "Pull origin".
    echo.
    pause
    exit /b 1
)

"%GITEXE%" pull --ff-only
if errorlevel 1 (
    echo.
    echo [ECHEC] La mise a jour n'a pas abouti.
    echo Envoie une copie d'ecran de cette fenetre a l'auteur de l'outil.
    pause
    exit /b 1
)

rem Une nouvelle version peut avoir besoin d'une librairie supplementaire.
if exist ".venv\Scripts\python.exe" (
    echo.
    echo Verification des librairies...
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)

echo.
echo ============================================================
echo   A jour. Double-clique sur "Lancer.bat" pour demarrer.
echo ============================================================
echo.
pause
