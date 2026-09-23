@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Installation de l'outil d'extraction de factures

echo ============================================================
echo   Installation de l'outil d'extraction de factures
echo ============================================================
echo.
echo Cette etape est a faire une seule fois. Elle telecharge les
echo librairies necessaires (environ 150 Mo) et peut durer
echo plusieurs minutes. Laisse cette fenetre ouverte.
echo.

rem --- 1. Trouver un Python utilisable -------------------------------------
rem "where python" ne suffit pas : Windows fournit un faux python.exe qui
rem ouvre le Microsoft Store. Chaque candidat est donc teste en l'executant.
set "PYEXE="
for %%C in ("py -3" "python" "%USERPROFILE%\anaconda3\python.exe" "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe") do (
    if not defined PYEXE (
        %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
        if !errorlevel! equ 0 set "PYEXE=%%~C"
    )
)

if not defined PYEXE (
    echo [ECHEC] Python n'est pas installe sur cet ordinateur.
    echo.
    echo   1. Ouvre https://www.python.org/downloads/windows/
    echo   2. Telecharge la derniere version "Windows installer (64-bit)"
    echo   3. IMPORTANT : coche "Add python.exe to PATH" sur le premier ecran
    echo   4. Termine l'installation, puis relance ce fichier Installer.bat
    echo.
    pause
    exit /b 1
)
echo Python trouve : %PYEXE%
echo.

rem --- 2. Creer l'environnement dedie ---------------------------------------
if exist ".venv\Scripts\python.exe" (
    echo Environnement deja present, il sera mis a jour.
) else (
    echo Creation de l'environnement dedie...
    %PYEXE% -m venv .venv
    if errorlevel 1 (
        echo [ECHEC] Impossible de creer l'environnement. Voir le message ci-dessus.
        pause
        exit /b 1
    )
)

rem --- 3. Installer les librairies ------------------------------------------
echo Telechargement des librairies, merci de patienter...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ECHEC] L'installation des librairies a echoue.
    echo Verifie ta connexion internet puis relance ce fichier.
    pause
    exit /b 1
)
echo Librairies installees.
echo.

rem --- 4. Fichier de configuration ------------------------------------------
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo Fichier de configuration cree : .env
    echo.
    echo DERNIERE ETAPE : colle ta cle Anthropic dans le fichier qui va
    echo s'ouvrir, a la place de "sk-ant-...", puis enregistre (Ctrl+S)
    echo et ferme le bloc-notes.
    echo.
    pause
    notepad ".env"
) else (
    echo Fichier de configuration deja present : .env
)

echo.
echo ============================================================
echo   Installation terminee.
echo   Double-clique maintenant sur "Lancer.bat" pour demarrer.
echo ============================================================
echo.
pause
