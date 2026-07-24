"""
FinData MX — Módulo de Forecast
=================================
Genera proyecciones a 12 meses para los indicadores macroeconómicos clave.

Modelos usados:
  • ARIMA(p,d,q) con selección automática de parámetros (AIC mínimo)
  • ExponentialSmoothing (Holt-Winters) como modelo de comparación
  • Ensemble: promedio ponderado de ambos (menor error histórico = mayor peso)

Variables forecasted:
  • Tasa de fondeo Banxico     (SF61745)
  • Inflación INPC anual       (SP1)
  • Tipo de cambio FIX         (SF17908)
  • Crédito consumo total      (CNBV)
  • Crédito pyme total         (CNBV)
  • Captación bancaria         (CNBV)

Output:
  ../data/forecast_output.json
  ../data/forecast_macro.csv
"""

import json
import warnings
import os
import numpy as np
import pandas as pd
from itertools import product
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.stattools import adfuller

warnings.filterwarnings("ignore")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
HORIZON  = 12  # meses a proyectar

# ── HELPERS ──────────────────────────────────────────────────────────────────

def is_stationary(series: pd.Series, alpha: float = 0.05) -> bool:
    """ADF test — True si la serie es estacionaria."""
    result = adfuller(series.dropna(), autolag="AIC")
    return result[1] < alpha


def best_arima(series: pd.Series, max_p=3, max_q=2, seasonal=False, m=12):
    """
    Grid search sobre (p,d,q) minimizando AIC.
    d se determina automáticamente por prueba de estacionariedad.
    """
    d = 0 if is_stationary(series) else 1

    best_aic = np.inf
    best_order = (1, d, 1)
    best_model = None

    for p, q in product(range(max_p + 1), range(max_q + 1)):
        try:
            if seasonal:
                mod = SARIMAX(series, order=(p, d, q),
                              seasonal_order=(1, 1, 1, m),
                              enforce_stationarity=False,
                              enforce_invertibility=False)
            else:
                mod = SARIMAX(series, order=(p, d, q),
                              enforce_stationarity=False,
                              enforce_invertibility=False)
            res = mod.fit(disp=False)
            if res.aic < best_aic:
                best_aic   = res.aic
                best_order = (p, d, q)
                best_model = res
        except Exception:
            continue

    return best_model, best_order, best_aic


def forecast_series(name: str, series: pd.Series, horizon: int = HORIZON):
    """
    Ajusta ARIMA y ETS, genera forecast ensemble con IC al 80% y 95%.
    Returns dict con arrays de fechas y valores.
    """
    print(f"  → Forecasting '{name}' ({len(series)} obs)...")

    # ── ARIMA ────────────────────────────────────────────────────────────────
    arima_model, order, aic = best_arima(series)
    arima_fc = arima_model.get_forecast(steps=horizon)
    arima_mean = arima_fc.predicted_mean.values
    arima_ci80  = arima_fc.conf_int(alpha=0.20)   # 80% IC
    arima_ci95  = arima_fc.conf_int(alpha=0.05)   # 95% IC

    # ── ETS (Holt-Winters) ──────────────────────────────────────────────────
    try:
        ets = ExponentialSmoothing(
            series,
            trend="add",
            seasonal=None,   # sin estacionalidad mensual (series anualizadas)
            damped_trend=True
        ).fit(optimized=True, remove_bias=True)
        ets_mean = ets.forecast(horizon).values
        # ETS IC aproximado ±1.96 × RMSE in-sample
        ets_rmse = np.sqrt(np.mean((ets.fittedvalues - series) ** 2))
        ets_ci_lo95 = ets_mean - 1.96 * ets_rmse
        ets_ci_hi95 = ets_mean + 1.96 * ets_rmse
        ets_ci_lo80 = ets_mean - 1.28 * ets_rmse
        ets_ci_hi80 = ets_mean + 1.28 * ets_rmse
    except Exception:
        ets_mean    = arima_mean.copy()
        ets_ci_lo95 = arima_ci95.iloc[:, 0].values
        ets_ci_hi95 = arima_ci95.iloc[:, 1].values
        ets_ci_lo80 = arima_ci80.iloc[:, 0].values
        ets_ci_hi80 = arima_ci80.iloc[:, 1].values

    # ── RMSE in-sample (para ponderar ensemble) ──────────────────────────────
    arima_fitted = arima_model.fittedvalues
    arima_rmse   = np.sqrt(np.mean((arima_fitted - series.values) ** 2))
    ets_rmse_val = np.sqrt(np.mean((ets.fittedvalues - series) ** 2)) if 'ets' in dir() else arima_rmse

    # Pesos inversamente proporcionales al RMSE
    total = arima_rmse + ets_rmse_val
    w_arima = 1 - arima_rmse / total
    w_ets   = 1 - ets_rmse_val / total

    # ── Ensemble ─────────────────────────────────────────────────────────────
    ensemble_mean = w_arima * arima_mean + w_ets * ets_mean
    ensemble_lo95 = w_arima * arima_ci95.iloc[:, 0].values + w_ets * ets_ci_lo95
    ensemble_hi95 = w_arima * arima_ci95.iloc[:, 1].values + w_ets * ets_ci_hi95
    ensemble_lo80 = w_arima * arima_ci80.iloc[:, 0].values + w_ets * ets_ci_lo80
    ensemble_hi80 = w_arima * arima_ci80.iloc[:, 1].values + w_ets * ets_ci_hi80

    # ── Fechas futuras ───────────────────────────────────────────────────────
    last_date    = series.index[-1]
    future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1),
                                 periods=horizon, freq="MS")

    print(f"     ARIMA{order} AIC={aic:.1f} | RMSE={arima_rmse:.3f} | "
          f"w_ARIMA={w_arima:.2f} w_ETS={w_ets:.2f}")
    print(f"     Forecast 12m: {ensemble_mean[0]:.3f} → {ensemble_mean[-1]:.3f}")

    return {
        "name":         name,
        "history": {
            "dates":  series.index.strftime("%Y-%m-%d").tolist(),
            "values": np.round(series.values, 4).tolist(),
        },
        "forecast": {
            "dates":      future_dates.strftime("%Y-%m-%d").tolist(),
            "mean":       np.round(ensemble_mean, 4).tolist(),
            "ci95_lo":    np.round(ensemble_lo95, 4).tolist(),
            "ci95_hi":    np.round(ensemble_hi95, 4).tolist(),
            "ci80_lo":    np.round(ensemble_lo80, 4).tolist(),
            "ci80_hi":    np.round(ensemble_hi80, 4).tolist(),
        },
        "meta": {
            "arima_order": list(order),
            "arima_aic":   round(float(aic), 2),
            "arima_rmse":  round(float(arima_rmse), 4),
            "weight_arima": round(float(w_arima), 3),
            "weight_ets":   round(float(w_ets), 3),
            "n_obs":       int(len(series)),
            "horizon":     horizon,
        }
    }


# ── PIPELINE PRINCIPAL ───────────────────────────────────────────────────────

def run_forecast():
    print("=" * 58)
    print("  🇲🇽  FinData MX — Forecast Module")
    print("  Modelos: ARIMA + ETS Ensemble · Horizonte: 12 meses")
    print("=" * 58)

    maestro = pd.read_csv(f"{DATA_DIR}/macro_maestro.csv", parse_dates=["fecha"], index_col="fecha")

    # Variables a forecastear
    targets = {
        "Tasa de Fondeo (%)":        maestro["tasa_fondeo"].dropna(),
        "Inflación INPC (%)":        maestro["inflacion"].dropna(),
        "Tipo de Cambio FIX":        maestro["tipo_cambio_fix"].dropna(),
        "Crédito Consumo (Mmn MXN)": maestro["credito_consumo_mmn"].dropna(),
        "Crédito Pyme (Mmn MXN)":    maestro["credito_pyme_mmn"].dropna(),
        "Captación Bancaria (Mmn)":  maestro["captacion_mmn"].dropna(),
    }

    results = {}
    print()
    for name, series in targets.items():
        results[name] = forecast_series(name, series)
        print()

    # Guardar JSON completo
    out_path = f"{DATA_DIR}/forecast_output.json"
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False)
    print(f"✅  Forecast guardado → {out_path}")

    # Guardar CSV flat (útil para Looker / Excel)
    rows = []
    for name, res in results.items():
        for i, d in enumerate(res["forecast"]["dates"]):
            rows.append({
                "indicador": name,
                "fecha":     d,
                "tipo":      "forecast",
                "valor":     res["forecast"]["mean"][i],
                "ci95_lo":   res["forecast"]["ci95_lo"][i],
                "ci95_hi":   res["forecast"]["ci95_hi"][i],
            })
        for i, d in enumerate(res["history"]["dates"]):
            rows.append({
                "indicador": name,
                "fecha":     d,
                "tipo":      "historico",
                "valor":     res["history"]["values"][i],
                "ci95_lo":   None,
                "ci95_hi":   None,
            })
    pd.DataFrame(rows).to_csv(f"{DATA_DIR}/forecast_macro.csv", index=False)
    print(f"✅  CSV flat guardado  → {DATA_DIR}/forecast_macro.csv")
    print("=" * 58)

    return results


if __name__ == "__main__":
    run_forecast()
