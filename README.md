# TFM Vino Costa Rica 2025 - Obtencion de datos

Proyecto base robusto para la asignatura 5: obtencion, preparacion y documentacion
de datos para el TFM **Analisis de mercado y factibilidad comercial del vino en
Costa Rica 2025**.

## Entregables incluidos

- `reports/TFM_Obtencion_Datos_Vino_CR.pdf`: documento PDF real, sin codigo.
- `results/`: datasets CSV generados para entrega.
- `src/`: arquitectura modular en Python para extraccion, limpieza y EDA.
- `notebooks/`: notebook reproducible.
- `docs/`: documentacion tecnica y diccionario de datos.

## Fuentes consideradas

- Web scraping: Walmart CR, Masxmenos CR, PriceSmart CR.
- APIs/open data: BCCR, PROCOMER/COMEX, INEC, ICT.

## Instalacion local

Consulta `INSTALL.md` para instrucciones completas en Windows, macOS y Linux.

## Ejecucion en este PC

La instalacion ya quedo preparada en este equipo con un entorno virtual en:

```text
C:\Users\luisa\.venvs\tfm_vino_cr
```

Desde la carpeta del proyecto ejecuta:

```bat
.\run_pipeline.bat
```

Ese comando ejecuta scraping en vivo, guarda el raw actualizado y regenera los CSV de
limpieza, EDA y calidad.

## Ejecucion manual

Por defecto, el pipeline hace scraping en vivo desde las fuentes definidas en
`src/config/sources.yaml`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.pipeline
```

En Windows PowerShell, la activacion del entorno es:

```powershell
.\.venv\Scripts\Activate.ps1
```

Si necesitas regenerar los archivos usando el CSV raw ya existente, sin scraping en vivo:

```bash
python -m src.pipeline --from-existing
```

En este PC se usa `--no-verify-ssl` dentro de `run_pipeline.bat` porque Python no pudo
validar el certificado local de algunos sitios al hacer scraping.

## CSV generados

El pipeline en vivo genera o actualiza:

- `results/webscraping_precios_vino_raw.csv`: datos extraidos por scraping en vivo.
- `results/webscraping_precios_vino_clean.csv`: datos limpios y normalizados.
- `results/eda_resumen_por_retailer_categoria.csv`: resumen por retailer y categoria.
- `results/data_quality_report.csv`: metricas de calidad del dataset.

Nota actual: Walmart CR y Masxmenos CR devuelven filas con el scraper HTML actual.
PriceSmart CR devuelve 0 filas, probablemente porque su catalogo depende de JavaScript
o bloqueo del HTML estatico.

## Pruebas

```bash
python -m pytest tests
```

Las pruebas actuales validan el parseo de precios en formato costarricense, por ejemplo
`2.330` como `2330 CRC`.

## Buenas practicas usadas

- Separacion de responsabilidades: extractores, transformadores, analisis y utilidades.
- Configuracion externa en YAML.
- Logging basico.
- Resultados reproducibles en CSV.
- Diccionario de variables y reporte de calidad.
- Respeto a buenas practicas eticas de scraping: baja frecuencia, identificacion de
  agente, revision de terminos y robots.txt.
