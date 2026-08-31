@echo off
chcp 65001 >nul
title Navegador para iniciar sesion
cd /d "%~dp0"

REM ---------------------------------------------------------------------
REM  Abre un Chrome NORMAL (sin automatizacion) usando una carpeta de
REM  perfil aparte, dentro de esta misma carpeta del proyecto.
REM
REM  Para que sirve: algunas redes (X sobre todo) limitan los intentos de
REM  acceso desde el navegador que controla la aplicacion. Aqui inicias
REM  sesion como en cualquier navegador, y luego la aplicacion reutiliza
REM  esta misma carpeta: la sesion ya esta dentro y no hay ningun intento
REM  de acceso que limitar.
REM
REM  Tu contraseña se escribe en esta ventana de Chrome, como siempre.
REM  Ni la aplicacion ni nadie mas la ve.
REM ---------------------------------------------------------------------

set "PERFIL=%~dp0perfil_navegador"

echo ============================================================
echo   NAVEGADOR PARA INICIAR SESION
echo ============================================================
echo.
echo  Carpeta de perfil:
echo    %PERFIL%
echo.
echo  1. Se abrira Chrome. Inicia sesion en la red que necesites
echo     (X, TikTok, Instagram o Facebook) como lo harias siempre.
echo  2. Cuando termines, CIERRA esa ventana de Chrome del todo.
echo  3. En la aplicacion, pega esta carpeta en:
echo     Opciones avanzadas ^> "Carpeta de perfil del navegador"
echo.

set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME%" (
    echo [ERROR] No se encontro Google Chrome en este equipo.
    echo Instalalo desde https://www.google.com/chrome/ y vuelve a intentarlo.
    echo.
    pause
    exit /b 1
)

start "" "%CHROME%" --user-data-dir="%PERFIL%" --no-first-run --no-default-browser-check https://x.com/login

echo  Chrome abierto. Cuando termines de iniciar sesion, cierralo.
echo.
pause
