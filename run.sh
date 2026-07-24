#!/bin/bash
# FinData MX — Pipeline completo
# Descarga datos (o genera demo si no hay token) y corre el forecast.
set -e

cd "$(dirname "$0")"

python pipeline/api_connector.py
python pipeline/forecast.py

echo ""
echo "✅ Pipeline terminado. Abre dashboard/index.html en tu navegador."
