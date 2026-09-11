# Instalacion local

Este proyecto es una aplicacion/paquete Python para extraer precios por scraping en vivo,
guardar el CSV raw y regenerar datasets limpios en `results/`.

## Requisitos

- Python 3.11 o 3.12 recomendado.
- Python 3.13 puede funcionar con estas dependencias, pero Python 3.14 no es recomendable
  para este proyecto porque varias versiones fijadas en `requirements.txt` pueden no tener
  ruedas compatibles todavia.
- `pip` actualizado.

## Instalacion en Windows PowerShell

Desde la carpeta raiz del proyecto:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m src.pipeline --no-verify-ssl
```

Si no tienes Python 3.12 instalado, instala Python 3.12 desde python.org y vuelve a ejecutar
los comandos. Si tu equipo solo tiene Python 3.13, puedes probar:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m src.pipeline
```

## Instalacion en macOS/Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m src.pipeline
```

## Verificacion

El comando:

```bash
python -m src.pipeline
```

debe terminar con el mensaje `Pipeline finalizado correctamente` y regenerar estos archivos:

- `results/webscraping_precios_vino_raw.csv`
- `results/webscraping_precios_vino_clean.csv`
- `results/eda_resumen_por_retailer_categoria.csv`
- `results/data_quality_report.csv`

Por defecto, `python -m src.pipeline` ejecuta scraping en vivo usando
`src/config/sources.yaml`. Para usar el CSV raw ya existente:

```powershell
python -m src.pipeline --from-existing
```

En algunos entornos Windows puede aparecer un error SSL al consultar los retailers. En ese
caso usa:

```powershell
python -m src.pipeline --no-verify-ssl
```

## Instalacion realizada en este equipo

En este PC el entorno virtual quedo instalado fuera de la carpeta del proyecto para evitar
el limite de rutas largas de Windows:

```powershell
C:\Users\luisa\.venvs\tfm_vino_cr
```

Para ejecutar el pipeline desde la carpeta del proyecto:

```bat
.\run_pipeline.bat
```

O, si prefieres activar el entorno manualmente:

```powershell
C:\Users\luisa\.venvs\tfm_vino_cr\Scripts\Activate.ps1
python -m src.pipeline --no-verify-ssl
```

## Variables para BCCR

El pipeline principal no requiere credenciales. Solo el extractor de BCCR necesita estas
variables de entorno:

```powershell
$env:BCCR_EMAIL="tu-correo"
$env:BCCR_TOKEN="tu-token"
```

## Notas

- `data/raw/` y `data/processed/` estan vacios; los datos generados por el pipeline estan
  en `results/`.
- No hay aplicacion Streamlit en el codigo actual, aunque `streamlit` aparece en
  `requirements.txt`.
- Hay pruebas automatizadas para el parseo de precios en `tests/`.

## Pruebas

```powershell
python -m pytest tests
```

## Problema conocido: Python 3.14

Si intentas instalar con Python 3.14, puedes ver un error parecido a:

```text
Preparing metadata (pyproject.toml) did not run successfully
ERROR: Could not find ... Visual Studio ... vswhere.exe
```

Esto ocurre porque `pandas==2.2.3` no encuentra una rueda compatible para esa version de
Python y `pip` intenta compilar pandas localmente. La solucion recomendada es instalar
Python 3.12, borrar el entorno `.venv` creado con Python 3.14 y repetir la instalacion.
