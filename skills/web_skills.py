import requests
from datetime import datetime

_HEADERS = {"User-Agent": "JARVIS-Assistant/1.0"}
_TIMEOUT = 8

# Códigos WMO → descripción en español
_WMO = {
    0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado", 3: "Nublado",
    45: "Neblina", 48: "Neblina con escarcha",
    51: "Llovizna ligera", 53: "Llovizna moderada", 55: "Llovizna intensa",
    61: "Lluvia ligera", 63: "Lluvia moderada", 65: "Lluvia intensa",
    71: "Nevada ligera", 73: "Nevada moderada", 75: "Nevada intensa",
    80: "Chubascos ligeros", 81: "Chubascos moderados", 82: "Chubascos intensos",
    95: "Tormenta eléctrica", 96: "Tormenta con granizo", 99: "Tormenta fuerte con granizo",
}


def _ahora() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")


# ── Geocodificación (ciudad → lat/lon) ────────────────────────────────────

def _geocode(city: str):
    """Devuelve (lat, lon, nombre, país) o None."""
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "es"},
            headers=_HEADERS, timeout=_TIMEOUT
        )
        results = r.json().get("results", [])
        if not results:
            return None
        g = results[0]
        return g["latitude"], g["longitude"], g.get("name", city), g.get("country", "")
    except Exception:
        return None


# ── Fuente 1: Open-Meteo (modelo ECMWF) ──────────────────────────────────

def _src_openmeteo(lat: float, lon: float) -> dict | None:
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":  lat,
                "longitude": lon,
                "current":   ("temperature_2m,relative_humidity_2m,apparent_temperature,"
                              "precipitation,weather_code,wind_speed_10m,uv_index"),
                "daily":     "temperature_2m_max,temperature_2m_min,precipitation_sum,uv_index_max",
                "timezone":  "auto",
                "forecast_days": 1,
            },
            headers=_HEADERS, timeout=_TIMEOUT
        )
        data = r.json()
        return data if "current" in data else None
    except Exception:
        return None


# ── Fuente 2: wttr.in ─────────────────────────────────────────────────────

def _src_wttr(city: str) -> dict | None:
    try:
        r = requests.get(
            f"https://wttr.in/{city}?format=j1",
            headers=_HEADERS, timeout=_TIMEOUT
        )
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# ── Agregación multi-fuente ───────────────────────────────────────────────

def get_weather(city: str) -> str:
    if not city or not city.strip():
        return "Especifica una ciudad para consultar el clima."
    city    = city.strip()
    now_str = _ahora()

    # Obtener las dos fuentes en paralelo (secuencial pero rápido)
    geo       = _geocode(city)
    om        = _src_openmeteo(geo[0], geo[1]) if geo else None
    wttr      = _src_wttr(city)

    if not om and not wttr:
        return f"[{now_str}] No pude obtener el clima de '{city}'. Verifica el nombre."

    # ── Extraer valores de cada fuente ────────────────────────────────────
    temps, feels, hums, winds = [], [], [], []
    desc = None
    max_t = min_t = precip = uv = None
    loc   = city

    # Open-Meteo
    if om:
        c    = om["current"]
        t_om = c.get("temperature_2m")
        f_om = c.get("apparent_temperature")
        h_om = c.get("relative_humidity_2m")
        w_om = c.get("wind_speed_10m")
        code = c.get("weather_code", 0)
        uv   = c.get("uv_index")

        if t_om is not None: temps.append(t_om)
        if f_om is not None: feels.append(f_om)
        if h_om is not None: hums.append(h_om)
        if w_om is not None: winds.append(w_om)

        desc = _WMO.get(code, f"Código {code}")

        d     = om.get("daily", {})
        max_t = (d.get("temperature_2m_max") or [None])[0]
        min_t = (d.get("temperature_2m_min") or [None])[0]
        precip = (d.get("precipitation_sum") or [None])[0]

        if geo:
            loc = f"{geo[2]}, {geo[3]}" if geo[3] else geo[2]

    # wttr.in
    if wttr and "current_condition" in wttr:
        wc   = wttr["current_condition"][0]
        t_wt = float(wc.get("temp_C", 0))
        f_wt = float(wc.get("FeelsLikeC", 0))
        h_wt = float(wc.get("humidity", 0))
        w_wt = float(wc.get("windspeedKmph", 0))

        temps.append(t_wt); feels.append(f_wt)
        hums.append(h_wt);  winds.append(w_wt)

        if desc is None:
            lang_es = wc.get("lang_es", [])
            desc = lang_es[0]["value"] if lang_es else wc["weatherDesc"][0]["value"]

        if "nearest_area" in wttr and loc == city:
            a   = wttr["nearest_area"][0]
            loc = (f"{a.get('areaName',[{'value':city}])[0]['value']}, "
                   f"{a.get('country',[{'value':''}])[0]['value']}")

        if max_t is None and "weather" in wttr:
            day   = wttr["weather"][0]
            max_t = day.get("maxtempC")
            min_t = day.get("mintempC")

    # ── Promedios ─────────────────────────────────────────────────────────
    avg_t = round(sum(temps)  / len(temps),  1) if temps  else "?"
    avg_f = round(sum(feels)  / len(feels),  1) if feels  else "?"
    avg_h = round(sum(hums)   / len(hums))       if hums   else "?"
    avg_w = round(sum(winds)  / len(winds),  1) if winds  else "?"

    fuentes = []
    if om:   fuentes.append("Open-Meteo/ECMWF")
    if wttr: fuentes.append("wttr.in")
    n_src = len(fuentes)

    # ── Formato final ─────────────────────────────────────────────────────
    lineas = [
        f"🌍  {loc}",
        f"📅  {now_str}  |  {n_src} fuente{'s' if n_src>1 else ''}: {', '.join(fuentes)}",
        "",
        f"🌡️   Temperatura: {avg_t}°C  (sensación {avg_f}°C)",
        f"☁️   {desc}",
    ]
    if max_t is not None and min_t is not None:
        lineas.append(f"📈  Máx {max_t}°C  —  Mín {min_t}°C")
    lineas.append(f"💧  Humedad: {avg_h}%   |   💨 Viento: {avg_w} km/h")
    if uv is not None:
        lineas.append(f"☀️   Índice UV: {uv}")
    if precip is not None:
        lineas.append(f"🌧️   Precipitación hoy: {precip} mm")
    if n_src > 1:
        lineas.append(f"\n📊  Datos promediados de {n_src} fuentes meteorológicas.")
    return "\n".join(lineas)


# ── Búsqueda web multi-estrategia ─────────────────────────────────────────

def web_search(query: str, max_results: int = 5) -> str:
    if not query or not query.strip():
        return "Especifica qué quieres buscar."
    query   = query.strip()
    now_str = _ahora()
    try:
        from ddgs import DDGS
        resultados = []
        vistos     = set()

        with DDGS() as ddgs:
            # Estrategia 1: búsqueda de texto general
            for r in ddgs.text(query, max_results=max_results):
                url = r.get("href", "")
                if url not in vistos:
                    vistos.add(url)
                    resultados.append(("web", r))

            # Estrategia 2: noticias (añade contexto reciente)
            for r in ddgs.news(query, max_results=3):
                url = r.get("url", "")
                if url not in vistos:
                    vistos.add(url)
                    resultados.append(("noticia", r))

        if not resultados:
            return f"[{now_str}] No encontré resultados para '{query}'."

        lineas = [f"🔍  '{query}'  —  {now_str}", f"    {len(resultados)} resultado(s)\n"]
        for tipo, r in resultados[:max_results + 2]:
            if tipo == "web":
                titulo = r.get("title", "Sin título")
                cuerpo = r.get("body", "")
                cuerpo = cuerpo[:200] + "..." if len(cuerpo) > 200 else cuerpo
                lineas.append(f"• {titulo}\n  {cuerpo}")
            else:
                titulo = r.get("title", "")
                fecha  = r.get("date", "")[:10]
                fuente = r.get("source", "")
                lineas.append(f"📰 [{fecha}] {titulo}  — {fuente}")

        return "\n".join(lineas)
    except ImportError:
        return "Falta el paquete: pip install ddgs"
    except Exception as e:
        return f"Error en la búsqueda: {e}"


# ── Wikipedia ─────────────────────────────────────────────────────────────

def get_wikipedia(topic: str) -> str:
    if not topic or not topic.strip():
        return "Especifica un tema para buscar en Wikipedia."
    now_str = _ahora()
    slug    = topic.strip().replace(" ", "_")
    for lang in ("es", "en"):
        try:
            r = requests.get(
                f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{slug}",
                headers=_HEADERS, timeout=_TIMEOUT
            )
            if r.status_code == 200:
                data    = r.json()
                titulo  = data.get("title", topic)
                extract = data.get("extract", "")
                if extract:
                    if len(extract) > 500:
                        extract = extract[:500] + "..."
                    return f"📖  {titulo}  [{now_str}]\n{extract}"
        except Exception:
            continue
    return f"[{now_str}] No encontré información sobre '{topic}' en Wikipedia."


# ── Noticias ─────────────────────────────────────────────────────────────

def get_news(topic: str = "", max_results: int = 6) -> str:
    now_str = _ahora()
    try:
        from ddgs import DDGS
        query = topic.strip() if topic and topic.strip() else "noticias"
        vistos, lineas_n = set(), []

        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=max_results):
                uid = r.get("url", r.get("title", ""))
                if uid in vistos:
                    continue
                vistos.add(uid)
                titulo = r.get("title", "")
                fecha  = r.get("date", "")[:10]
                fuente = r.get("source", "")
                lineas_n.append(f"• [{fecha}] {titulo}  — {fuente}")

        if not lineas_n:
            return f"[{now_str}] No encontré noticias sobre '{topic}'."

        header = f"📰  Noticias{' sobre ' + topic if topic else ''}  —  {now_str}\n"
        return header + "\n".join(lineas_n)
    except ImportError:
        return "Falta el paquete: pip install ddgs"
    except Exception as e:
        return f"Error al buscar noticias: {e}"
