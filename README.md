# FinData MX

Dashboard financiero mexicano con datos reales de APIs públicas gratuitas
(Banxico SIE, INEGI BIE, CNBV) y forecast automático (ARIMA + ETS Ensemble,
12 meses, IC 80%/95%).

## Estructura

```
findata-mx/
  pipeline/
    api_connector.py       # descarga Banxico (real) + INEGI + DataMéxico + CNBV + merge maestro
    imss_connector.py       # intento real de trabajadores asegurados IMSS (bloqueado por WAF) + fallback demo
    cnbv_parser.py          # parser del boletín Excel mensual de CNBV (URL real aún no confirmada) + fallback demo
    forecast.py             # modelos ARIMA+ETS sobre data/macro_maestro.csv
    generate_demo_data.py   # datos simulados — fallback si una fuente real falla
    build_static.py         # genera dashboard/index_static.html (para GitHub Pages)
    n8n_workflow.json        # workflow importable para automatizar la actualización mensual
  data/                     # CSVs/JSON/PNG generados (no versionados, excepto .gitkeep)
  dashboard/
    index.html               # dashboard (fetch a data/*.csv y *.json — necesita servidor local)
    index_static.html        # generado por build_static.py — datos embebidos, para GitHub Pages
  .env.example
  requirements.txt
  run.sh
```

## Instalación

```bash
git clone <tu-repo>
cd findata-mx
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edita `.env` y agrega tus tokens:

```
BANXICO_TOKEN=tu_token_real
INEGI_TOKEN=tu_token_real
```

Si no tienes alguno de los dos, esa fuente cae automáticamente a datos demo
(o se salta, en el caso de INEGI) — el pipeline nunca se detiene por esto.

## Primer run

```bash
python pipeline/api_connector.py
python pipeline/forecast.py
```

Esto descarga los datos (con fallback a demo si algo falla), corre el
forecast, y deja todo en `data/`. También puedes usar `./run.sh` para
encadenar ambos pasos.

Después abre `dashboard/index.html` — **necesita un servidor local**
porque hace `fetch()` de los CSVs/JSON (los navegadores bloquean `fetch`
sobre `file://`):

```bash
python -m http.server 8000
# abre http://localhost:8000/dashboard/
```

## Dashboard estático (sin servidor)

```bash
python pipeline/build_static.py
```

Genera `dashboard/index_static.html` con los datos embebidos inline —
se puede abrir directamente con doble-click, sin servidor.

## Estado de cada fuente de datos

| Fuente | Estado | Nota |
|---|---|---|
| Banxico SIE | ✅ Real (8 series) | `tasa_fondeo`, `tiie_28d` (SF283), `tiie_91d` (SF60649), `tipo_cambio_fix`, `tipo_cambio_48h`, `ipc_indice`, `reservas_int` (SF43707), `remesas` — cada ID verificado 1x1 contra `/SieAPIRest/service/v1/series/{id}` (campo `titulo`), no asumido |
| Banxico — m1, m4, crédito empresas/consumo/vivienda, inflación subyacente | ⏸️ Pendiente | los IDs heredados del setup original apuntaban a series **equivocadas** (ej. "reservas" traía gasto público, "m1" traía Cetes 91d) — se removieron en vez de dejar datos mal etiquetados; quedan marcados `REEMPLAZA_CON_ID_REAL` en `BANXICO_SERIES`. No inventar IDs nuevos sin verificar contra el catálogo real |
| INEGI BIE (IGAE, empleo) | ⏸️ Pendiente | token funciona; los IDs de indicador no se encontraron válidos — requiere el Constructor de Consultas de INEGI (manual, no tiene API de búsqueda) |
| DataMéxico | ⏸️ Pendiente | `api.datamexico.org` no resuelve (dominio migrado a economia.gob.mx/datamexico); falta confirmar el endpoint real — ver comentario en `DATAMEXICO_BASE` |
| IMSS (trabajadores asegurados) | ⏸️ Bloqueado | `datos.imss.gob.mx` está protegido por un WAF (Incapsula, 403 con challenge JS) — no se intentó evadir; sin vía de acceso legítima confirmada todavía |
| CNBV (boletín Excel) | ⏸️ Pendiente | la URL documentada devuelve 404; el boletín real parece vivir en `portafolioinfo.cnbv.gob.mx` como PDF, no Excel — ver comentarios en `cnbv_parser.py` |
| CNBV (datos abiertos / CKAN) | ⏸️ Pendiente | `resource_id` son placeholders — hay que sacarlos del portal `datos.cnbv.gob.mx` |

Todas las fuentes marcadas ⏸️ tienen fallback automático a datos demo
(`generate_demo_data.py`) — el pipeline y el dashboard siempre funcionan,
aunque no todas las fuentes reales estén conectadas todavía.

## Contexto para quien retome esto (ej. otro agente)

- El dashboard (`dashboard/index.html`) tuvo un bug de resize-loop de Chart.js
  (canvases sin contenedor de altura fija crecían sin límite en cada frame).
  Ya está arreglado: cada `<canvas>` vive dentro de un `.chart-container` con
  altura fija en px. Verificado con Playwright — las alturas de canvas quedan
  constantes en el tiempo. Si vuelves a ver charts rotos/gigantes, revisa que
  ese wrapper siga ahí antes de tocar la config de Chart.js.
- Las secciones "Sistema bancario" y "Market share" del dashboard usan datos
  ilustrativos fijos (no vienen del pipeline) — se conectarán cuando el
  parser real de CNBV esté disponible.
- No hay historial de git previo a este commit — el repo se inicializó limpio
  dentro de `FINDATAMX/` (antes vivía como subcarpeta suelta del `$HOME` del
  usuario, sin repo propio). `.env` con tokens reales nunca se trackeó.

## Setup de n8n (automatización mensual)

1. Levanta n8n (`npx n8n` o Docker).
2. En n8n: **Workflows → Import from File** → selecciona `pipeline/n8n_workflow.json`.
3. Configura las variables de entorno del workflow: `BANXICO_TOKEN`,
   `WEBHOOK_CONFIRMACION_URL`, `SLACK_WEBHOOK_URL`.
4. El nodo "HTTP DataMéxico" tiene una URL placeholder — actualízala cuando
   se confirme el endpoint real (ver tabla de arriba).
5. Monta la carpeta del repo como volumen en `/data` dentro del contenedor
   de n8n para que el nodo Code pueda escribir los CSVs donde `forecast.py`
   los espera.
6. Activa el workflow — corre automáticamente el día 1 de cada mes a las 8am
   hora Ciudad de México.

## Deploy en GitHub Pages

1. Corre el pipeline completo y genera el estático:
   ```bash
   python pipeline/api_connector.py
   python pipeline/forecast.py
   python pipeline/build_static.py
   ```
2. Commit y push de `dashboard/index_static.html` (sí se versiona — es el
   que se va a servir).
3. En GitHub: **Settings → Pages → Source** → selecciona la rama y la
   carpeta `/dashboard`.
4. En **Settings → Pages**, bajo "Custom domain" déjalo vacío para usar el
   dominio `github.io` por default, o configura el tuyo.
5. Renombra `index_static.html` a `index.html` antes de subir si quieres
   que sea la página de entrada por default de Pages (o usa un redirect).
6. El dashboard queda disponible en `https://<usuario>.github.io/<repo>/`.

Para refrescar los datos publicados: vuelve a correr los 3 comandos del
paso 1 y haz push del nuevo `index_static.html` — o automatiza esto con
un GitHub Action en cron (o con el workflow de n8n de arriba, apuntando
el commit final a tu repo vía la API de GitHub).
