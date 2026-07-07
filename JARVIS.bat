@echo off
:: Se auto-eleva a administrador (una sola vez, un solo cuadro de UAC al iniciar)
:: — lo necesita la skill de Bluetooth para reconectar dispositivos.
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Solicitando permisos de administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
if not exist ".env" (
    echo No se encontro el archivo .env
    echo Copia .env.example como .env y completa tus API keys antes de continuar.
    pause
    exit /b 1
)
python main.py
pause
