"""
FinData MX — Conector de trabajadores asegurados IMSS
=========================================================
Descarga el dataset de "Asegurados" del portal de datos abiertos del IMSS
y extrae el total nacional de trabajadores asegurados por mes.

⚠️ LIMITACIÓN CONOCIDA: datos.imss.gob.mx está detrás de un WAF (Incapsula)
que bloquea requests automatizados con un challenge de JavaScript — devuelve
403 sin importar el User-Agent. No intentamos evadirlo (no es el propósito de
este proyecto). Verificamos también si el dataset está espejado en el portal
nacional (datos.gob.mx, que sí es accesible vía su API CKAN) — no lo está.
Mientras no haya una vía de acceso legítima (API key del IMSS, descarga
manual, u otro espejo), este conector cae a datos demo automáticamente.

Los CSVs reales del IMSS son grandes (millones de filas por mes, un registro
por asegurado). Si en algún momento se resuelve el acceso, procesa con
pd.read_csv(..., chunksize=...) y agrega por mes (groupby + count/sum) en
vez de cargar todo en memoria.

Uso:
  python pipeline/imss_connector.py
"""

import logging
from pathlib import Path

import requests
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("findata")

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

IMSS_GROUP_URL = "http://datos.imss.gob.mx/group/asegurados"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

CHUNK_SIZE = 200_000  # filas por chunk al procesar el CSV real (evita cargar todo a memoria)


def descubrir_recurso_mas_reciente() -> str | None:
    """
    Busca en el grupo 'asegurados' del portal IMSS el recurso CSV más
    reciente. Regresa None si el portal bloquea el acceso (WAF) o no
    encuentra nada.
    """
    try:
        r = requests.get(IMSS_GROUP_URL, headers=HEADERS, timeout=20)
        if r.status_code != 200 or "Incapsula" in r.text:
            log.warning(f"  ⚠ datos.imss.gob.mx bloqueó el acceso automatizado "
                        f"(status {r.status_code}, WAF/Incapsula) — sin vía legítima de descarga")
            return None
        # TODO: si el WAF se abre en el futuro, parsear el HTML de la página
        # de grupo (o su API CKAN si existe) para encontrar el resource_id
        # del CSV más reciente y regresar su URL de descarga directa.
        log.warning("  ⚠ Acceso al portal OK pero el parser de recursos no está implementado todavía")
        return None
    except Exception as e:
        log.error(f"  ✗ Error accediendo a {IMSS_GROUP_URL}: {e}")
        return None


def procesar_csv_asegurados(url_csv: str) -> pd.DataFrame:
    """
    Descarga y agrega por mes el CSV de asegurados (potencialmente millones
    de filas) usando chunks, para no saturar memoria.
    """
    total_por_mes = {}
    with requests.get(url_csv, headers=HEADERS, timeout=60, stream=True) as r:
        r.raise_for_status()
        for chunk in pd.read_csv(r.raw, chunksize=CHUNK_SIZE):
            # Nombres de columna reales por confirmar cuando el portal esté accesible.
            # Se asume una columna de periodo (ej. 'periodo' o 'fecha_alta') y
            # un conteo de asegurados por registro.
            if "periodo" in chunk.columns:
                conteo = chunk.groupby("periodo").size()
                for periodo, n in conteo.items():
                    total_por_mes[periodo] = total_por_mes.get(periodo, 0) + n

    df = pd.DataFrame(list(total_por_mes.items()), columns=["fecha", "trabajadores_imss"])
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df.sort_values("fecha").reset_index(drop=True)


def build_imss_csv() -> pd.DataFrame:
    """
    Intenta descargar y procesar el dataset real del IMSS. Si el WAF bloquea
    el acceso (caso actual) o cualquier paso falla, cae a datos demo.
    """
    log.info("=" * 58)
    log.info("  🇲🇽  FinData MX — IMSS Conector de Asegurados")
    log.info("=" * 58)

    url_csv = descubrir_recurso_mas_reciente()

    if url_csv:
        try:
            df  = procesar_csv_asegurados(url_csv)
            out = DATA_DIR / "imss_trabajadores.csv"
            df.to_csv(out, index=False)
            log.info(f"  → Guardado: {out} {df.shape}")
            return df
        except Exception as e:
            log.error(f"  ✗ Error procesando CSV de IMSS: {e}")

    log.warning("  ⚠ Sin acceso al dataset real de IMSS — usando datos demo")
    import generate_demo_data
    return generate_demo_data.generar_demo_imss()


if __name__ == "__main__":
    build_imss_csv()
