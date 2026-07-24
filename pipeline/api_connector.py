"""
FinData MX — API Connector (Producción)
=========================================
Conecta a las tres APIs públicas de México.
Cuando el token de Banxico llegue, solo cambia el .env y ya funciona todo.

Setup:
  1. Copia .env.example → .env
  2. Pon tu BANXICO_TOKEN en .env
  3. Registra token INEGI en: https://www.inegi.org.mx/servicios/api_indicadores.html
  4. Corre:  python api_connector.py [--source banxico|inegi|cnbv|all]

El token de Banxico se obtiene en:
  https://www.banxico.org.mx/SieAPIRest/service/v1/token
  (registro gratuito instantáneo, solo necesitas email)
"""

import os
import sys
import time
import logging
import argparse
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # sin python-dotenv: usa variables de entorno del sistema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("findata")

DATA_DIR   = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DATE_FROM  = (datetime.today() - timedelta(days=6 * 365)).strftime("%Y-%m-%d")
DATE_TO    = datetime.today().strftime("%Y-%m-%d")
RATE_DELAY = 0.4   # segundos entre requests (respetar rate limits)


# ══════════════════════════════════════════════════════════════════════════════
# BANXICO SIE API
# Docs:  https://www.banxico.org.mx/SieAPIRest/service/v1/doc/
# Token: https://www.banxico.org.mx/SieAPIRest/service/v1/token
# ══════════════════════════════════════════════════════════════════════════════

BANXICO_BASE = "https://www.banxico.org.mx/SieAPIRest/service/v1"

# NOTA (2026-07): verificado 1x1 contra /SieAPIRest/service/v1/series/{id} —
# comparamos el "titulo" que regresa la API contra lo que decía el comentario
# original. Varios IDs heredados del Sprint 1 apuntaban a series completamente
# distintas (ej. "reservas_int" traía "Gastos Presupuestales del Sector
# Público", no reservas). Los corregidos abajo están verificados; los que no
# pudimos verificar quedan como REEMPLAZA_CON_ID_REAL (mismo patrón que INEGI/
# CNBV) en vez de seguir jalando datos con la etiqueta equivocada.
BANXICO_SERIES = {
    # ── Política monetaria ──────────────────────────────────────────────────
    "tasa_fondeo":       "SF61745",   # ✓ verificado: "Tasa objetivo"
    "tiie_28d":          "SF283",     # ✓ verificado: "TIIE a 28 días" (antes: SF43718, que era tipo de cambio)
    "tiie_91d":          "SF60649",   # ✓ verificado: "TIIE a 91 días" (antes: SF43936, que era Cetes)
    # ── Tipo de cambio ──────────────────────────────────────────────────────
    "tipo_cambio_fix":   "SF17908",   # ✓ verificado: "Tipo de cambio... Fecha de determinación (FIX)"
    "tipo_cambio_48h":   "SF60653",   # ✓ verificado: "Tipo de cambio... Fecha de liquidación"
    # ── Inflación ───────────────────────────────────────────────────────────
    "ipc_indice":        "SP1",       # ✓ verificado: "IPC... Indice General"
    "inflacion_suby":    "REEMPLAZA_CON_ID_REAL",  # ✗ SP74565 da 404 — descontinuada o ID equivocado
    # ── Agregados monetarios ─────────────────────────────────────────────────
    "m1":                "REEMPLAZA_CON_ID_REAL",  # ✗ SF3338 en realidad es "Cetes 91 días" — no M1
    "m4":                "REEMPLAZA_CON_ID_REAL",  # ✗ SF3367 en realidad es "Cetes 364 días" — no M4
    # ── Sector externo ──────────────────────────────────────────────────────
    "reservas_int":      "SF43707",   # ✓ verificado: "Reserva Internacional" (antes: SG1, que era gasto presupuestal)
    "remesas":           "SE27803",   # ✓ verificado: "Remesas Familiares Total"
    # ── Crédito bancario ─────────────────────────────────────────────────────
    "credito_empresas":  "REEMPLAZA_CON_ID_REAL",  # ✗ SF43405 en realidad es deuda pública, no crédito a empresas
    "credito_consumo_bx":"REEMPLAZA_CON_ID_REAL",  # ✗ SF43406 en realidad es deuda pública, no crédito consumo
    "credito_vivienda":  "REEMPLAZA_CON_ID_REAL",  # ✗ SF43407 en realidad es deuda pública, no crédito vivienda
}


def fetch_banxico_series(series_id: str, name: str, token: str) -> pd.DataFrame:
    """Descarga una serie del SIE de Banxico entre DATE_FROM y DATE_TO."""
    url     = f"{BANXICO_BASE}/series/{series_id}/datos/{DATE_FROM}/{DATE_TO}"
    headers = {"Bmx-Token": token}

    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        data   = r.json()
        series = data["bmx"]["series"][0]

        if "datos" not in series:
            log.warning(f"Sin datos: {name} ({series_id})")
            return pd.DataFrame(columns=["fecha", name])

        df = pd.DataFrame(series["datos"])
        df.columns = ["fecha", name]
        df["fecha"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y")
        df[name]    = pd.to_numeric(df[name].str.replace(",", ""), errors="coerce")
        df          = df.dropna().sort_values("fecha").reset_index(drop=True)

        log.info(f"  ✓ Banxico [{series_id}] {name}: {len(df)} registros "
                 f"({df['fecha'].iloc[0].date()} → {df['fecha'].iloc[-1].date()})")
        return df

    except requests.HTTPError as e:
        if e.response.status_code == 401:
            log.error(f"Token inválido o expirado. Revisa BANXICO_TOKEN en .env")
        else:
            log.error(f"HTTP {e.response.status_code} en {name}: {e}")
        return pd.DataFrame(columns=["fecha", name])
    except Exception as e:
        log.error(f"  ✗ Error en {name} ({series_id}): {e}")
        return pd.DataFrame(columns=["fecha", name])


def fetch_all_banxico(token: str) -> pd.DataFrame:
    """Descarga todas las series de Banxico y genera CSV mensual."""
    log.info("\n📡 Banxico SIE API — descargando series...")
    dfs = []

    for name, series_id in BANXICO_SERIES.items():
        if "REEMPLAZA" in series_id:
            log.warning(f"  ⚠ {name}: ID pendiente de verificar contra el catálogo real de Banxico — saltando")
            continue

        df = fetch_banxico_series(series_id, name, token)
        if not df.empty:
            df = df.set_index("fecha").resample("ME").last()
            dfs.append(df)
        time.sleep(RATE_DELAY)

    if not dfs:
        log.error("No se descargó ninguna serie de Banxico.")
        return pd.DataFrame()

    result = pd.concat(dfs, axis=1).reset_index()
    out    = DATA_DIR / "banxico_macro.csv"
    result.to_csv(out, index=False)
    log.info(f"  → Guardado: {out} {result.shape}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# INEGI BISE API
# Docs:  https://www.inegi.org.mx/servicios/api_indicadores.html
# Token: https://www.inegi.org.mx/app/desarrolladores/generatoken/Usuarios/...
#        (requiere registro con CURP — solo para ciudadanos/residentes MX)
# ══════════════════════════════════════════════════════════════════════════════

INEGI_BASE = "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR"

INEGI_INDICADORES = {
    "igae_indice":          "493911",
    "igae_var_anual":       "493912",
    "consumo_privado":      "628194",
    "tasa_desocupacion":    "444319",
    "trabajadores_imss":    "216064",
    "prod_industrial":      "311142",
    "ventas_minoristas":    "702893",
}

INEGI_AREA_GEOGRAFICA = "00"   # nacional
INEGI_FUENTE           = "BIE"


def fetch_inegi_indicador(indicador_id: str, name: str, token: str) -> pd.DataFrame:
    """Descarga un indicador del BIE de INEGI (serie histórica completa)."""
    url = (f"{INEGI_BASE}/{indicador_id}/es/{INEGI_AREA_GEOGRAFICA}/false/"
           f"{INEGI_FUENTE}/2.0/{token}?type=json")

    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
        obs  = data["Series"][0]["OBSERVATIONS"]

        df = pd.DataFrame(obs)[["TIME_PERIOD", "OBS_VALUE"]]
        df.columns = ["fecha", name]
        df["fecha"] = pd.to_datetime(df["fecha"])
        df[name]    = pd.to_numeric(df[name], errors="coerce")
        df          = df.dropna().sort_values("fecha").reset_index(drop=True)

        log.info(f"  ✓ INEGI [{indicador_id}] {name}: {len(df)} registros")
        return df

    except Exception as e:
        log.error(f"  ✗ Error INEGI {name} ({indicador_id}): {e}")
        return pd.DataFrame(columns=["fecha", name])


def fetch_all_inegi(token: str) -> pd.DataFrame:
    """Descarga todos los indicadores INEGI."""
    log.info("\n📡 INEGI BISE API — descargando indicadores...")
    dfs = []

    for name, ind_id in INEGI_INDICADORES.items():
        if "REEMPLAZA" in ind_id:
            log.warning(f"  ⚠ {name}: ID pendiente — búscalo en el Constructor de "
                        "Consultas de INEGI y reemplázalo en INEGI_INDICADORES")
            continue

        df = fetch_inegi_indicador(ind_id, name, token)
        if not df.empty:
            df = df.set_index("fecha")
            dfs.append(df)
        time.sleep(RATE_DELAY)

    if not dfs:
        log.error("No se descargó ningún indicador de INEGI.")
        return pd.DataFrame()

    result = pd.concat(dfs, axis=1).reset_index()
    out    = DATA_DIR / "inegi_macro.csv"
    result.to_csv(out, index=False)
    log.info(f"  → Guardado: {out} {result.shape}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# DATAMÉXICO (Secretaría de Economía) — sin token, alternativa a INEGI BIE
#
# ⚠️ VERIFICACIÓN PENDIENTE: "api.datamexico.org" (el dominio documentado
# públicamente para esta API) no resuelve por DNS al momento de escribir esto
# — el sitio datamexico.org migró a economia.gob.mx/datamexico y no encontramos
# el endpoint real de la nueva API en el HTML público. Deja este bloque como
# placeholder: intenta la llamada real y, si falla, se salta limpiamente sin
# tronar el pipeline. Para activarlo: abre DevTools → pestaña Network en
# economia.gob.mx/datamexico, busca la llamada que trae los datos de IGAE, y
# reemplaza DATAMEXICO_BASE con la URL real.
# ══════════════════════════════════════════════════════════════════════════════

DATAMEXICO_BASE = "REEMPLAZA_CON_URL_REAL"   # antes: https://api.datamexico.org/tesseract/data.jsonrecords

DATAMEXICO_CUBOS = {
    "igae":              {"cube": "inegi_igae", "drilldowns": "Month", "measures": "Value"},
    "trabajadores_imss": {"cube": "imss_month_occupation_subgroup", "drilldowns": "Month", "measures": "Workers"},
    "desocupacion":      {"cube": "inegi_enoe", "drilldowns": "Quarter", "measures": "Unemployment Rate"},
}


def fetch_datamexico_cubo(name: str, params: dict) -> pd.DataFrame:
    """Descarga un cubo de la API de DataMéxico (sin token)."""
    try:
        r = requests.get(DATAMEXICO_BASE, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        df   = pd.DataFrame(data.get("data", data))
        log.info(f"  ✓ DataMéxico [{name}]: {len(df)} registros")
        return df
    except Exception as e:
        log.error(f"  ✗ Error DataMéxico {name}: {e}")
        return pd.DataFrame()


def fetch_all_datamexico() -> pd.DataFrame:
    """Descarga todos los cubos de DataMéxico. Fallback limpio si la API no responde."""
    log.info("\n📡 DataMéxico API — descargando cubos (IGAE, IMSS, ENOE)...")

    if "REEMPLAZA" in DATAMEXICO_BASE:
        log.warning("  ⚠ DataMéxico: URL base pendiente de verificar — saltando "
                     "(ver comentario en DATAMEXICO_BASE)")
        return pd.DataFrame()

    dfs = []
    for name, params in DATAMEXICO_CUBOS.items():
        df = fetch_datamexico_cubo(name, params)
        if not df.empty:
            dfs.append(df)
        time.sleep(RATE_DELAY)

    if not dfs:
        log.warning("  ⚠ DataMéxico sin datos — se usará fallback demo")
        return pd.DataFrame()

    result = pd.concat(dfs, axis=1)
    out    = DATA_DIR / "datamexico_macro.csv"
    result.to_csv(out, index=False)
    log.info(f"  → Guardado: {out} {result.shape}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# CNBV DATOS ABIERTOS (sin token requerido)
# Portal: https://datos.cnbv.gob.mx
# CKAN API: https://datos.cnbv.gob.mx/api/3/action/
#
# Para encontrar resource_ids:
#   1. Ve a datos.cnbv.gob.mx
#   2. Busca el dataset que te interesa
#   3. Click en "Explorar" → la URL contiene el resource_id
#
# IDs verificados (pueden cambiar — revisalos en el portal):
# ══════════════════════════════════════════════════════════════════════════════

CNBV_BASE = "https://datos.cnbv.gob.mx/api/3/action/datastore_search"

# NOTA: sustituye estos IDs con los reales del portal datos.cnbv.gob.mx
# Los puedes encontrar en la URL de cada dataset al explorar los datos
CNBV_DATASETS = {
    "banca_multiple_cartera": {
        # Boletín Estadístico Banca Múltiple — Cartera de crédito
        "resource_id": "REEMPLAZA_CON_ID_REAL",
        "description": "Cartera de crédito por institución y tipo — BEMM"
    },
    "banca_multiple_captacion": {
        # Captación tradicional
        "resource_id": "REEMPLAZA_CON_ID_REAL",
        "description": "Captación bancaria por instrumento"
    },
    "sofom_enr_cartera": {
        # SOFOMs ENR — cartera
        "resource_id": "REEMPLAZA_CON_ID_REAL",
        "description": "Cartera de crédito SOFOMs Entidades No Reguladas"
    },
}

# ── ALTERNATIVA: descarga directa de archivos Excel del boletín CNBV ─────────
# La CNBV publica los boletines mensuales en:
# https://www.cnbv.gob.mx/SECTORES-SUPERVISADOS/BANCA-MULTIPLE/Paginas/...
# Pueden descargarse y parsearse con openpyxl:
CNBV_BOLETIN_URL = (
    "https://www.cnbv.gob.mx/SECTORES-SUPERVISADOS/BANCA-MULTIPLE/Boletines/"
    "Boletin{mes:02d}{anio}.xlsx"
)


def fetch_cnbv_dataset(name: str, config: dict, limit: int = 5000) -> pd.DataFrame:
    """Descarga un dataset de la API CKAN de CNBV."""
    params = {"resource_id": config["resource_id"], "limit": limit}

    try:
        r = requests.get(CNBV_BASE, params=params, timeout=30)
        r.raise_for_status()
        data    = r.json()
        records = data["result"]["records"]
        df      = pd.DataFrame(records)
        log.info(f"  ✓ CNBV [{name}]: {len(df)} registros")
        return df
    except Exception as e:
        log.error(f"  ✗ Error CNBV {name}: {e}")
        return pd.DataFrame()


def fetch_all_cnbv() -> pd.DataFrame:
    """
    Descarga los datasets de CNBV y consolida en data/cnbv_banking.csv.
    Si ningún resource_id está configurado (o la descarga falla), regresa
    un DataFrame vacío — el caller decide si usar el fallback demo.
    """
    log.info("\n📡 CNBV Datos Abiertos — descargando datasets...")
    dfs = []

    for name, config in CNBV_DATASETS.items():
        if "REEMPLAZA" in config["resource_id"]:
            log.warning(f"  ⚠ {name}: resource_id pendiente — "
                        "reemplaza con el ID real en datos.cnbv.gob.mx")
            continue

        df = fetch_cnbv_dataset(name, config)
        if not df.empty:
            dfs.append(df)
        time.sleep(RATE_DELAY)

    if not dfs:
        log.warning("  ⚠ CNBV sin resource_id configurados o sin datos — se usará fallback demo")
        return pd.DataFrame()

    result = pd.concat(dfs, axis=1)
    out    = DATA_DIR / "cnbv_banking.csv"
    result.to_csv(out, index=False)
    log.info(f"  → Guardado: {out} {result.shape}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# MERGE MAESTRO
# ══════════════════════════════════════════════════════════════════════════════

def build_maestro():
    """
    Une banxico_macro.csv + cnbv_banking.csv (reales o demo, ya en disco)
    en data/macro_maestro.csv — el único archivo que lee forecast.py.
    También deriva 'inflacion' (% anual) a partir de 'ipc_indice'.
    """
    paths = {
        "banxico":    DATA_DIR / "banxico_macro.csv",
        "inegi":      DATA_DIR / "inegi_macro.csv",
        "datamexico": DATA_DIR / "datamexico_macro.csv",
        "imss":       DATA_DIR / "imss_trabajadores.csv",
        "cnbv":       DATA_DIR / "cnbv_banking.csv",
    }

    frames = {}
    for key, path in paths.items():
        if path.exists():
            df = pd.read_csv(path, parse_dates=["fecha"])
            frames[key] = df.set_index("fecha").resample("MS").last()
            log.info(f"  Cargado {key}: {frames[key].shape}")

    if not frames:
        log.error("Sin datos para merge maestro. Corre api_connector.py primero.")
        return None

    maestro = pd.concat(list(frames.values()), axis=1).sort_index()
    maestro = maestro[maestro.index >= pd.Timestamp(DATE_FROM)]  # descarta series históricas (ej. censos) fuera del rango de interés

    if "ipc_indice" in maestro.columns:
        maestro["inflacion"] = maestro["ipc_indice"].pct_change(periods=12, fill_method=None) * 100

    maestro = maestro.reset_index()

    out = DATA_DIR / "macro_maestro.csv"
    maestro.to_csv(out, index=False)
    log.info(f"\n✅ Maestro guardado: {out} {maestro.shape}")
    return maestro


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def _token_valido(token: str) -> bool:
    return bool(token) and "TU_" not in token


def _resumen_maestro(maestro: pd.DataFrame) -> None:
    """Imprime cuántas series, rango de fechas y último valor de cada una."""
    if maestro is None or maestro.empty:
        log.warning("Sin datos en el maestro para resumir.")
        return

    cols = [c for c in maestro.columns if c != "fecha"]
    log.info("\n📊 Resumen — macro_maestro.csv")
    log.info(f"  Series: {len(cols)}")
    log.info(f"  Rango de fechas: {maestro['fecha'].min().date()} → {maestro['fecha'].max().date()}")
    for c in cols:
        ultimo = maestro[c].dropna()
        valor  = round(ultimo.iloc[-1], 4) if not ultimo.empty else "sin datos"
        log.info(f"    • {c}: {valor}")


def main():
    parser = argparse.ArgumentParser(description="FinData MX — API Connector")
    parser.add_argument(
        "--source", choices=["banxico", "inegi", "datamexico", "imss", "cnbv", "all"],
        default="all", help="Fuente a descargar (default: all)"
    )
    args = parser.parse_args()

    banxico_token = os.getenv("BANXICO_TOKEN", "")
    inegi_token   = os.getenv("INEGI_TOKEN", "")

    log.info("=" * 58)
    log.info("  🇲🇽  FinData MX — API Connector (producción)")
    log.info(f"  Periodo: {DATE_FROM} → {DATE_TO}")
    log.info(f"  Banxico token: {'✓ configurado' if _token_valido(banxico_token) else '✗ PENDIENTE (.env) — se usará demo'}")
    log.info(f"  INEGI token:   {'✓ configurado' if _token_valido(inegi_token) else '✗ PENDIENTE (.env)'}")
    log.info("=" * 58)

    src = args.source

    if src in ("banxico", "all"):
        banxico_df = pd.DataFrame()
        if _token_valido(banxico_token):
            banxico_df = fetch_all_banxico(banxico_token)
        else:
            log.warning("Banxico token no configurado — usando datos demo")

        if banxico_df.empty:
            import generate_demo_data
            generate_demo_data.generar_demo_banxico()

    if src in ("inegi", "all"):
        if _token_valido(inegi_token):
            fetch_all_inegi(inegi_token)
        else:
            log.warning("INEGI token no configurado — saltando. Agrega INEGI_TOKEN al .env")

    if src in ("datamexico", "all"):
        fetch_all_datamexico()

    if src in ("imss", "all"):
        import imss_connector
        imss_connector.build_imss_csv()

    if src in ("cnbv", "all"):
        cnbv_df = fetch_all_cnbv()
        if cnbv_df.empty:
            import generate_demo_data
            generate_demo_data.generar_demo_banking()

    if src == "all":
        maestro = build_maestro()
        _resumen_maestro(maestro)

    log.info("\n✅ Connector finalizado.")


if __name__ == "__main__":
    main()
