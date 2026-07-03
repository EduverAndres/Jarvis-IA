@echo off
echo ============================================
echo   JARVIS - Instalacion de dependencias
echo ============================================
echo.
python -m pip install -r requirements.txt
echo.
echo Instalando PyAudio (microfono)...
python -m pip install pyaudio
if %errorlevel% neq 0 (
    echo PyAudio fallo con pip. Intentando con pipwin...
    python -m pip install pipwin
    python -m pipwin install pyaudio
)
echo.
if not exist ".env" (
    echo Creando .env a partir de .env.example...
    copy .env.example .env >nul
    echo Completa tus API keys en el archivo .env antes de ejecutar JARVIS.bat
)
echo.
echo ============================================
echo   Instalacion completa. Ejecuta JARVIS.bat
echo ============================================
pause
