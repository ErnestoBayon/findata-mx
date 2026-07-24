"""
FinData MX — Generador de datos demo
=======================================
Genera datos simulados pero realistas cuando no hay token de Banxico
o cuando los resource_id de CNBV no están configurados, para que el
pipeline siempre tenga algo que forecastear.

Produce los mismos archivos que las fuentes reales:
  data/banxico_macro.csv   (mismas columnas que api_connector.fetch_all_banxico)
  data/cnbv_banking.csv    (mismas columnas que api_connector.fetch_all_cnbv)

Uso:
  python pipeline/generate_demo_data.py
"""

import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

MESES   = 72   # 6 años de historia mensual
SEMILLA = 42

# ── Series Banxico ───────────────────────────────────────────────────────────
# Mismo set que BANXICO_SERIES en api_connector.py, excluyendo las marcadas
# REEMPLAZA_CON_ID_REAL (para que demo y real tengan el mismo esquema de columnas).
SERIES_DEMO = {
    "tasa_fondeo":        {"inicio": 11.25, "vol": 0.15, "min": 3.0,  "max": 12.0},
    "tiie_28d":           {"inicio": 11.50, "vol": 0.15, "min": 3.0,  "max": 12.5},
    "tiie_91d":           {"inicio": 11.55, "vol": 0.15, "min": 3.0,  "max": 12.5},
    "tipo_cambio_fix":    {"inicio": 17.10, "vol": 0.35, "min": 15.0, "max": 21.0},
    "tipo_cambio_48h":    {"inicio": 17.05, "vol": 0.35, "min": 15.0, "max": 21.0},
    "ipc_indice":         {"inicio": 118.5, "vol": 0.60, "min": 95.0, "max": 135.0},
    "reservas_int":       {"inicio": 198000,"vol": 900,  "min": 170000,"max": 230000},
    "remesas":            {"inicio": 5200,  "vol": 350,  "min": 3500, "max": 6500},
}

# ── Series bancarias (equivalente demo de CNBV) ─────────────────────────────
BANKING_DEMO = {
    "credito_consumo_mmn": {"inicio": 1650, "vol": 20, "min": 1300, "max": 2100},
    "credito_pyme_mmn":    {"inicio": 980,  "vol": 15, "min": 700,  "max": 1300},
    "captacion_mmn":       {"inicio": 8200, "vol": 90, "min": 6500, "max": 9800},
}

# ── Trabajadores asegurados IMSS (equivalente demo de imss_connector) ───────
IMSS_DEMO = {
    "trabajadores_imss": {"inicio": 22_000_000, "vol": 60_000, "min": 20_000_000, "max": 24_000_000},
}


def caminata_aleatoria(inicio: float, vol: float, minimo: float, maximo: float,
                        n: int, rng: np.random.Generator) -> np.ndarray:
    """Genera una caminata aleatoria acotada entre minimo y maximo."""
    valores = [inicio]
    for _ in range(n - 1):
        siguiente = valores[-1] + rng.normal(0, vol)
        siguiente = float(np.clip(siguiente, minimo, maximo))
        valores.append(siguiente)
    return np.array(valores)


def _fechas() -> pd.DatetimeIndex:
    return pd.date_range(end=pd.Timestamp.today().normalize(), periods=MESES, freq="ME")


def generar_demo_banxico(rng: np.random.Generator = None) -> pd.DataFrame:
    """Genera data/banxico_macro.csv con la misma forma que la fuente real."""
    rng    = rng or np.random.default_rng(SEMILLA)
    fechas = _fechas()

    data = {"fecha": fechas}
    for nombre, cfg in SERIES_DEMO.items():
        data[nombre] = caminata_aleatoria(
            cfg["inicio"], cfg["vol"], cfg["min"], cfg["max"], MESES, rng
        ).round(4)

    df  = pd.DataFrame(data)
    out = DATA_DIR / "banxico_macro.csv"
    df.to_csv(out, index=False)
    print(f"  → [demo] Banxico: {out} — {len(SERIES_DEMO)} series, "
          f"{fechas[0].date()} → {fechas[-1].date()}")
    return df


def generar_demo_banking(rng: np.random.Generator = None) -> pd.DataFrame:
    """Genera data/cnbv_banking.csv con la misma forma que la fuente real."""
    rng    = rng or np.random.default_rng(SEMILLA + 1)
    fechas = _fechas()

    data = {"fecha": fechas}
    for nombre, cfg in BANKING_DEMO.items():
        data[nombre] = caminata_aleatoria(
            cfg["inicio"], cfg["vol"], cfg["min"], cfg["max"], MESES, rng
        ).round(4)

    df  = pd.DataFrame(data)
    out = DATA_DIR / "cnbv_banking.csv"
    df.to_csv(out, index=False)
    print(f"  → [demo] CNBV: {out} — {len(BANKING_DEMO)} series, "
          f"{fechas[0].date()} → {fechas[-1].date()}")
    return df


def generar_demo_imss(rng: np.random.Generator = None) -> pd.DataFrame:
    """Genera data/imss_trabajadores.csv con la misma forma que imss_connector."""
    rng    = rng or np.random.default_rng(SEMILLA + 2)
    fechas = _fechas()

    data = {"fecha": fechas}
    for nombre, cfg in IMSS_DEMO.items():
        data[nombre] = caminata_aleatoria(
            cfg["inicio"], cfg["vol"], cfg["min"], cfg["max"], MESES, rng
        ).round(0)

    df  = pd.DataFrame(data)
    out = DATA_DIR / "imss_trabajadores.csv"
    df.to_csv(out, index=False)
    print(f"  → [demo] IMSS: {out} — {len(IMSS_DEMO)} series, "
          f"{fechas[0].date()} → {fechas[-1].date()}")
    return df


def generar_demo() -> None:
    """Genera todos los archivos demo (Banxico + CNBV + IMSS)."""
    print("=" * 58)
    print("  🇲🇽  FinData MX — Datos demo generados")
    print("=" * 58)
    generar_demo_banxico()
    generar_demo_banking()
    generar_demo_imss()


if __name__ == "__main__":
    generar_demo()
