# J·A·R·V·I·S

Asistente de IA personal de escritorio para Windows, con interfaz 3D, voz natural, memoria persistente y un sistema de *skills* extensible (archivos, proyectos, sistema, web, Bluetooth). Backend de IA intercambiable entre varios proveedores gratuitos (Groq, Cerebras, OpenRouter, Mistral).

---

## Características

### Interfaz 3D moderna
- Orbe 3D real (Three.js) con iluminación, glow y partículas — no es un dibujo 2D, es una escena renderizada con materiales y luces reales.
- Cuatro estados visuales distintos: **en línea** (respirando suavemente), **pensando** (orbes orbitando), **escuchando** (barras de onda), **hablando** (barras radiales reactivas al volumen real de la voz sintetizada).
- Interfaz completa en estilo *glassmorphism* (paneles translúcidos, sombras en capas, bordes iluminados) construida con pywebview (HTML/CSS/JS embebido, sin depender de Tkinter).
- Tarjeta de estadísticas en vivo (CPU / RAM) superpuesta al orbe.

### IA multi-proveedor y personalizable
- Backend de IA intercambiable en caliente (sin reiniciar la app) entre **Groq**, **Cerebras**, **OpenRouter** y **Mistral** — los cuatro hablan el mismo protocolo compatible con OpenAI.
- Panel de configuración (botón ⚙ en el header) para elegir proveedor y modelo, con botón para traer en vivo la lista real de modelos disponibles de cada proveedor (los catálogos gratuitos cambian con frecuencia).
- API keys gestionadas en un archivo `.env` local (nunca en el código fuente).

### Voz
- Texto a voz con **Edge-TTS** (voces neuronales de Microsoft), voz por defecto en español colombiano (`es-CO-GonzaloNeural`).
- Reconocimiento de voz (Google Speech Recognition vía `SpeechRecognition` + `pyaudio`).
- **Barge-in**: si hablas mientras JARVIS está respondiendo, se detiene y te escucha de inmediato.
- Modo "Siempre escuchar": conversación continua sin tener que presionar el botón de micrófono cada vez.
- Animación de la burbuja al hablar sincronizada con el volumen real de la voz generada (no es un patrón aleatorio).

### Memoria
- Historial de conversación persistente (`data/memory.json`), con respaldo automático antes de cada escritura.
- Hechos aprendidos a largo plazo (la IA los guarda con `RECORDAR: <hecho>` cuando detecta información nueva relevante) y perfil de usuario.

### Sistema de *skills*
Todo lo que JARVIS puede ejecutar además de conversar:

| Categoría | Funciones |
|---|---|
| **Archivos** | crear/leer/escribir/eliminar/mover/renombrar archivos y carpetas, listar contenido, abrir el explorador o un archivo |
| **Proyectos** | generar un proyecto Python básico, un CRUD completo (Flask + SQLite + HTML), o un sitio web estático (HTML/CSS/JS) |
| **Sistema** | ejecutar comandos de consola (con lista de patrones peligrosos bloqueados), abrir aplicaciones comunes, hora/fecha, estado de CPU/RAM |
| **Web** | clima actual, búsqueda general, definiciones (Wikipedia), noticias |
| **Bluetooth** | encender/apagar el adaptador, conectar un dispositivo ya emparejado por nombre de voz |

Las acciones destructivas (como eliminar un archivo) piden confirmación explícita antes de ejecutarse.

---

## Requisitos

- **Windows 10/11** (usa APIs específicas de Windows: WebView2, WinRT para Bluetooth)
- **Python 3.10+**
- **[Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)** — viene preinstalado en Windows 11; en Windows 10 puede requerir instalarlo aparte
- Micrófono y parlantes (opcional, solo para las funciones de voz)
- Al menos una API key gratuita de un proveedor de IA compatible con OpenAI (ver [Proveedores de IA](#proveedores-de-ia-gratuitos))

---

## Instalación (en una laptop nueva)

1. **Clonar el repositorio**
   ```bash
   git clone https://github.com/EduverAndres/Jarvis-IA.git
   cd Jarvis-IA
   ```

2. **(Opcional pero recomendado) crear un entorno virtual**
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Instalar dependencias**
   ```bash
   pip install -r requirements.txt
   ```
   Si `pyaudio` falla al instalar (común en Windows), instálalo con:
   ```bash
   pip install pipwin
   pipwin install pyaudio
   ```
   O simplemente ejecuta `setup.bat`, que hace todo lo anterior automáticamente.

4. **Configurar las API keys**
   ```bash
   copy .env.example .env
   ```
   Abre `.env` con cualquier editor de texto y completa al menos `GROQ_API_KEY` (ver la siguiente sección para obtenerla gratis).

5. **Ejecutar**
   ```bash
   python main.py
   ```
   O haz doble clic en `JARVIS.bat`.

---

## Proveedores de IA gratuitos

Jarvis funciona con cualquiera de estos — solo necesitas al menos uno configurado en `.env` (`GROQ_API_KEY` viene activado por defecto):

| Proveedor | Dónde conseguir la key | Notas |
|---|---|---|
| **Groq** (recomendado, más rápido) | [console.groq.com](https://console.groq.com/keys) | Tier gratis generoso, sin tarjeta |
| **Cerebras** | [cloud.cerebras.ai](https://cloud.cerebras.ai/) | Mayor throughput bruto, contexto limitado en tier gratis |
| **OpenRouter** | [openrouter.ai/keys](https://openrouter.ai/keys) | Catálogo de modelos ":free" variable — usa el botón "Actualizar modelos" en la app |
| **Mistral** | [console.mistral.ai](https://console.mistral.ai/) | Buen soporte en español, tier de pruebas |

Puedes cambiar de proveedor/modelo en cualquier momento desde el botón ⚙ de la interfaz, sin reiniciar la app.

---

## Estructura del proyecto

```
Jarvis-IA/
├── main.py                  Punto de entrada
├── requirements.txt
├── .env.example              Plantilla de configuración (copiar a .env)
├── JARVIS.bat / setup.bat     Lanzadores para Windows
│
├── config/
│   ├── settings.py            Configuración general, carga el .env
│   └── providers.py            Catálogo de proveedores de IA
│
├── core/
│   ├── ai.py                   Llamadas al modelo de lenguaje (streaming)
│   ├── app_config.py           Proveedor/modelo activo, persistido
│   ├── memory.py                Historial y hechos aprendidos
│   ├── voice.py                  TTS/STT, barge-in, envolvente de audio
│   └── skill_runner.py           Parseo y ejecución de directivas SKILL:
│
├── skills/
│   ├── file_skills.py, project_skills.py,
│   ├── system_skills.py, web_skills.py, bluetooth_skills.py
│
├── ui/
│   ├── window.py                Ventana pywebview + puente Python↔JS
│   └── web/                      Frontend: index.html, css/, js/ (incl. orbe 3D), vendor/three.min.js
│
└── data/
    ├── memory.json                Historial y hechos (no versionado)
    └── app_config.json             Proveedor/modelo activo (no versionado)
```

---

## Notas y limitaciones conocidas

- El emparejamiento de un dispositivo Bluetooth **nuevo** (nunca conectado antes) no se puede automatizar por completo en Windows — siempre pide confirmar un PIN manualmente la primera vez. Jarvis solo reconecta dispositivos que **ya** están emparejados.
- Los catálogos de modelos gratuitos de los proveedores de IA cambian con frecuencia (especialmente OpenRouter); usa el botón "Actualizar modelos" del panel de configuración si un modelo deja de funcionar.
- `data/memory.json` y `data/app_config.json` no se suben al repositorio (contienen tu historial personal y configuración local) — se crean automáticamente la primera vez que ejecutas la app.
