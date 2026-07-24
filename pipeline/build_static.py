"""
FinData MX — Generador de dashboard estático
================================================
Lee dashboard/index.html (la versión que hace fetch() de data/macro_maestro.csv
y data/forecast_output.json) e inyecta esos datos inline como constantes JS,
para producir dashboard/index_static.html — una versión 100% autocontenida
que funciona en GitHub Pages (sin servidor, sin fetch a archivos externos).

Uso:
  python pipeline/build_static.py
"""

import json
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("findata")

ROOT      = Path(__file__).parent.parent
DATA_DIR  = ROOT / "data"
DASH_DIR  = ROOT / "dashboard"

FETCH_SNIPPET = """async function loadData() {
  const [maestroRes, forecastRes] = await Promise.all([
    fetch(DATA_URLS.maestro),
    fetch(DATA_URLS.forecast),
  ]);
  if (!maestroRes.ok || !forecastRes.ok) throw new Error('archivos de datos no encontrados');
  const maestroText = await maestroRes.text();
  const forecastJson = await forecastRes.json();
  const { rows } = parseCSV(maestroText);
  const ultimaFecha = rows.length ? rows[rows.length - 1].fecha : null;
  return { maestroRows: rows, forecast: forecastJson, ultimaFecha };
}"""


def build_static():
    src = DASH_DIR / "index.html"
    if not src.exists():
        raise FileNotFoundError(f"No existe {src} — corre esto desde la raíz del repo.")

    maestro_csv    = DATA_DIR / "macro_maestro.csv"
    forecast_json  = DATA_DIR / "forecast_output.json"
    if not maestro_csv.exists() or not forecast_json.exists():
        raise FileNotFoundError(
            "Faltan data/macro_maestro.csv o data/forecast_output.json — "
            "corre pipeline/api_connector.py y pipeline/forecast.py primero."
        )

    maestro_text = maestro_csv.read_text(encoding="utf-8")
    forecast     = json.loads(forecast_json.read_text(encoding="utf-8"))
    ultima_fecha = pd.read_csv(maestro_csv)["fecha"].dropna().iloc[-1]

    html = src.read_text(encoding="utf-8")

    if FETCH_SNIPPET not in html:
        raise RuntimeError(
            "No se encontró el bloque loadData() esperado en dashboard/index.html — "
            "¿cambió la estructura del archivo? Actualiza FETCH_SNIPPET en build_static.py."
        )

    embedded_snippet = f"""async function loadData() {{
  const maestroText = {json.dumps(maestro_text)};
  const forecastJson = {json.dumps(forecast, ensure_ascii=False)};
  const {{ rows }} = parseCSV(maestroText);
  const ultimaFecha = {json.dumps(str(ultima_fecha))};
  return {{ maestroRows: rows, forecast: forecastJson, ultimaFecha }};
}}"""

    html_static = html.replace(FETCH_SNIPPET, embedded_snippet)
    html_static = html_static.replace(
        "<title>FinData MX v2</title>",
        "<title>FinData MX v2 — Estático</title>",
    )

    out = DASH_DIR / "index_static.html"
    out.write_text(html_static, encoding="utf-8")

    log.info("=" * 58)
    log.info("  🇲🇽  FinData MX — Dashboard estático generado")
    log.info(f"  → {out}")
    log.info(f"  Datos embebidos al: {ultima_fecha}")
    log.info(f"  Tamaño: {out.stat().st_size / 1024:.1f} KB")
    log.info("=" * 58)
    return out


if __name__ == "__main__":
    build_static()
