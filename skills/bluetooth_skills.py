import json
import subprocess

# Enciende/apaga el radio de Bluetooth vía WinRT (Windows.Devices.Radios.Radio).
# No requiere privilegios de administrador — mismo patrón usado por el propio
# panel de Configuración de Windows para el interruptor de Bluetooth.
_RADIO_TOGGLE_PS = '''
If ((Get-Service bthserv).Status -eq 'Stopped') {{ Start-Service bthserv }}
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }})[0]
Function Await($WinRtTask, $ResultType) {{
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}}
[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$bluetooth = $radios | ? {{ $_.Kind -eq 'Bluetooth' }}
if (-not $bluetooth) {{ Write-Output "NO_RADIO"; exit 0 }}
[Windows.Devices.Radios.RadioState,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
Await ($bluetooth.SetStateAsync('{state}')) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
Write-Output "OK"
'''

_NOISE_PATTERN = (
    r"Enumerador|Enumerator|Wireless Bluetooth|Transporte AVRCP|AVRCP Transport|"
    r"^Radio$|Servicio Bluetooth|Bluetooth Service|Bluetooth Device \(RFCOMM|"
    r"Bluetooth Device \(Personal"
)

_LIST_DEVICES_PS = (
    "Get-PnpDevice -Class Bluetooth | "
    "Where-Object {$_.FriendlyName -and $_.FriendlyName -notmatch "
    f"'{_NOISE_PATTERN}'"
    "} | Select-Object FriendlyName, InstanceId, Status | ConvertTo-Json -Compress"
)


def _run_ps(script: str, timeout: int = 20) -> tuple[str, str, int]:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Tiempo de espera agotado.", 1
    except Exception as exc:
        return "", str(exc), 1


def bluetooth_power(state: str) -> str:
    """state: 'on' u 'off' (también acepta 'encender'/'apagar')."""
    want_on = state.strip().lower() in ("on", "encender", "encendido", "activar", "true", "1")
    ps_state = "On" if want_on else "Off"
    out, err, code = _run_ps(_RADIO_TOGGLE_PS.format(state=ps_state))
    if "NO_RADIO" in out:
        return "No encontré un adaptador de Bluetooth en este equipo."
    if code != 0 or "OK" not in out:
        return f"No pude cambiar el estado de Bluetooth: {err or out or 'error desconocido'}."
    return f"Bluetooth {'activado' if want_on else 'desactivado'}."


def _list_paired_devices() -> list[dict]:
    out, err, code = _run_ps(_LIST_DEVICES_PS)
    if code != 0 or not out:
        return []
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        return [d for d in data if d.get("FriendlyName")]
    except (json.JSONDecodeError, TypeError):
        return []


def bluetooth_connect(device: str) -> str:
    if not device or not device.strip():
        return "Especifica el nombre del dispositivo Bluetooth a conectar."

    bluetooth_power("on")

    devices = _list_paired_devices()
    if not devices:
        return ("No encontré dispositivos Bluetooth emparejados en este equipo. "
                "Empareja el dispositivo manualmente desde Configuración > Bluetooth al menos una vez.")

    name_lower = device.strip().lower()
    match = next((d for d in devices if name_lower in d["FriendlyName"].lower()), None)
    if not match:
        disponibles = ", ".join(d["FriendlyName"] for d in devices)
        return (f"No encontré un dispositivo emparejado llamado '{device}'. "
                f"Dispositivos emparejados disponibles: {disponibles}.")

    instance_id = match["InstanceId"].replace("'", "''")
    script = (
        f"Disable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false; "
        f"Start-Sleep -Seconds 2; "
        f"Enable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false"
    )
    out, err, code = _run_ps(script, timeout=15)
    combined = (err or "") + (out or "")
    if code != 0 or "denied" in combined.lower() or "denegado" in combined.lower():
        return (f"Encontré '{match['FriendlyName']}' pero no pude reconectarlo: hace falta ejecutar "
                f"JARVIS como administrador para esta acción. Como alternativa, conéctalo manualmente "
                f"desde Configuración > Bluetooth.")
    return f"'{match['FriendlyName']}' reconectado."
