@echo off
chcp 65001 >nul
title Instalador - Extractor de Comentarios
cd /d "%~dp0"

echo ============================================================
echo   INSTALADOR - Extractor de Comentarios de Redes Sociales
echo ============================================================
echo.
echo Esto solo hay que hacerlo UNA VEZ. Puede tardar 3-8 minutos.
echo.

REM ---------- 1. Comprobar que Python esta instalado ----------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python en este equipo.
    echo.
    echo   1. Descargalo de https://www.python.org/downloads/
    echo   2. Durante la instalacion MARCA la casilla "Add Python to PATH"
    echo   3. Vuelve a ejecutar este archivo.
    echo.
    pause
    exit /b 1
)
echo [1/4] Python encontrado:
python --version
echo.

REM ---------- 2. Crear el entorno aislado ----------
if not exist ".venv\Scripts\python.exe" (
    echo [2/4] Creando el entorno de la aplicacion...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno.
        pause
        exit /b 1
    )
) else (
    echo [2/4] El entorno ya existia. Se reutiliza.
)
echo.

REM ---------- 3. Instalar las librerias ----------
echo [3/4] Instalando librerias (esto es lo que mas tarda)...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de librerias.
    pause
    exit /b 1
)
echo.

REM ---------- 4. Descargar el navegador que usa la app ----------
echo [4/4] Descargando el navegador Chromium (unos 150 MB)...
python -m playwright install chromium
if errorlevel 1 (
    echo [ERROR] No se pudo descargar el navegador.
    echo Comprueba tu conexion a internet y vuelve a intentarlo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   INSTALACION TERMINADA
echo   Ahora haz doble clic en  iniciar.bat  para abrir la app.
echo ============================================================
echo.
pause
