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

Resumen rapido:

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

## Buenas practicas usadas

- Separacion de responsabilidades: extractores, transformadores, analisis y utilidades.
- Configuracion externa en YAML.
- Logging basico.
- Resultados reproducibles en CSV.
- Diccionario de variables y reporte de calidad.
- Respeto a buenas practicas eticas de scraping: baja frecuencia, identificacion de
  agente, revision de terminos y robots.txt.
