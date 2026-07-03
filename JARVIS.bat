@echo off
cd /d "%~dp0"
if not exist ".env" (
    echo No se encontro el archivo .env
    echo Copia .env.example como .env y completa tus API keys antes de continuar.
    pause
    exit /b 1
)
python main.py
pause
