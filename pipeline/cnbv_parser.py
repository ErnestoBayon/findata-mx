"""
FinData MX — Parser del Boletín Estadístico de la CNBV
=========================================================
Descarga el boletín mensual de Banca Múltiple (Excel) y extrae cartera
de crédito y captación. Si la URL del mes actual no existe (el boletín
sale con retraso) intenta el mes anterior; si tampoco hay archivo,
cae a datos demo — el pipeline nunca se detiene por esto.

⚠️ VERIFICACIÓN PENDIENTE: al momento de escribir esto, la ruta pública
documentada (www.cnbv.gob.mx/.../Boletines/Boletin{MM}{YYYY}.xlsx) devuelve
404 (el sitio corre sobre SharePoint y parece haber cambiado de estructura).
El boletín real vive en el "Portafolio de Información" de la CNBV
(portafolioinfo.cnbv.gob.mx), normalmente como PDF, no Excel. Este script
deja la lógica de descarga/parseo lista para cuando se confirme la URL
correcta — mientras tanto, el fallback a demo garantiza que el pipeline
no se rompa.

Uso:
  python pipeline/cnbv_parser.py
"""

import logging
from datetime import date
from pathlib import Path

import requests
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("findata")

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

BOLETIN_URL_TEMPLATE = (
    "https://www.cnbv.gob.mx/SECTORES-SUPERVISADOS/BANCA-MULTIPLE/"
    "Boletines/Boletin{mes:02d}{anio}.xlsx"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}


def _mes_anterior(anio: int, mes: int) -> tuple:
    mes -= 1
    if mes == 0:
        mes = 12
        anio -= 1
    return anio, mes


def descargar_boletin(anio: int, mes: int, timeout: int = 30) -> bytes | None:
    """Intenta descargar el boletín de un mes dado. Regresa None si no existe."""
    url = BOLETIN_URL_TEMPLATE.format(mes=mes, anio=anio)
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200 and "spreadsheet" in r.headers.get("Content-Type", ""):
            log.info(f"  ✓ Boletín descargado: {url}")
            return r.content
        log.warning(f"  ⚠ Boletín no disponible ({r.status_code}): {url}")
        return None
    except Exception as e:
        log.error(f"  ✗ Error descargando boletín {url}: {e}")
        return None


def descargar_boletin_mas_reciente() -> tuple:
    """Intenta el mes actual y, si falla, el mes anterior. Regresa (contenido, anio, mes) o (None, None, None)."""
    hoy = date.today()
    anio, mes = hoy.year, hoy.month

    contenido = descargar_boletin(anio, mes)
    if contenido:
        return contenido, anio, mes

    anio_prev, mes_prev = _mes_anterior(anio, mes)
    contenido = descargar_boletin(anio_prev, mes_prev)
    if contenido:
        return contenido, anio_prev, mes_prev

    return None, None, None


def parsear_boletin(contenido: bytes) -> pd.DataFrame:
    """
    Parsea las hojas 'Cartera de crédito' y 'Captación' del boletín CNBV
    y regresa un DataFrame consolidado por institución.
    """
    import io
    xls = pd.ExcelFile(io.BytesIO(contenido), engine="openpyxl")

    cartera = pd.read_excel(xls, sheet_name="Cartera de crédito")
    cartera = cartera.rename(columns={
        "institución": "institucion", "consumo": "credito_consumo",
        "pyme": "credito_pyme", "vivienda": "credito_vivienda",
    })

    captacion = pd.read_excel(xls, sheet_name="Captación")
    captacion = captacion.rename(columns={
        "institución": "institucion", "vista": "captacion_vista",
        "plazo": "captacion_plazo", "total": "captacion_total",
    })

    return cartera.merge(captacion, on="institucion", how="outer")


def build_cnbv_banking_csv() -> pd.DataFrame:
    """
    Descarga y parsea el boletín más reciente. Si algo falla en cualquier
    paso, cae a generate_demo_data.generar_demo_banking() automáticamente.
    """
    log.info("=" * 58)
    log.info("  🇲🇽  FinData MX — CNBV Boletín Parser")
    log.info("=" * 58)

    contenido, anio, mes = descargar_boletin_mas_reciente()

    if contenido is not None:
        try:
            df  = parsear_boletin(contenido)
            out = DATA_DIR / "cnbv_banking.csv"
            df.to_csv(out, index=False)
            log.info(f"  → Guardado: {out} ({anio}-{mes:02d}) {df.shape}")
            return df
        except Exception as e:
            log.error(f"  ✗ Error parseando boletín: {e}")

    log.warning("  ⚠ No se pudo obtener el boletín real — usando datos demo")
    import generate_demo_data
    return generate_demo_data.generar_demo_banking()


if __name__ == "__main__":
    build_cnbv_banking_csv()
