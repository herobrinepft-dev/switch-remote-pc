@echo off
setlocal
cd /d "%~dp0"
title PC Remote

rem --- 1. Trouver Python (le lanceur "py" est prefere : le "python" du Microsoft Store est un faux) ---
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto :nopython

rem --- 2. Environnement virtuel (cree une seule fois) ---
if not exist ".venv\Scripts\python.exe" (
    echo Creation de l'environnement Python ^(une seule fois^)...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)

rem --- 3. Dependances (reinstallees seulement si requirements.txt a change) ---
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
    echo Installation des dependances ^(premier lancement, patiente un peu^)...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :fail
    copy /y requirements.txt ".venv\requirements.installed" >nul
)

rem --- 4. Lancement (les options passent telles quelles : start.bat --width 1920 --fps 60) ---
echo.
".venv\Scripts\python.exe" server.py %*
echo.
echo Le serveur s'est arrete.
pause
exit /b 0

:nopython
echo.
echo [ERREUR] Python 3 est introuvable.
echo Installe-le depuis https://www.python.org/downloads/ et coche "Add python.exe to PATH".
pause
exit /b 1

:fail
echo.
echo [ERREUR] Une etape a echoue. Lis le message ci-dessus.
pause
exit /b 1
