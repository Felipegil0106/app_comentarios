@echo off
chcp 65001 >nul
title Extractor de Comentarios
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] La aplicacion todavia no esta instalada.
    echo Haz doble clic primero en  instalar.bat
    echo.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m src.main

if errorlevel 1 (
    echo.
    echo La aplicacion se cerro con un error. El detalle esta arriba.
    pause
)
