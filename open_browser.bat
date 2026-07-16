@echo off
rem Attend que le serveur local reponde, puis ouvre le navigateur. Evite
rem d'ouvrir la page avant que uvicorn ait fini de charger (import des
rem librairies, qui peut prendre plus de quelques secondes selon la machine).
for /l %%i in (1,1,30) do (
    curl -s -o nul --connect-timeout 1 --max-time 2 http://127.0.0.1:8000/health
    if not errorlevel 1 (
        start "" http://127.0.0.1:8000
        exit /b 0
    )
    timeout /t 1 /nobreak >nul
)
rem Au bout de 30s, ouvre quand meme au cas ou /health ait un souci ponctuel.
start "" http://127.0.0.1:8000
