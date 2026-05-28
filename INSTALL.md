# Instalacion local

Este proyecto es una aplicacion/paquete Python para regenerar datasets CSV a partir de
archivos ya incluidos en `results/`.

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
python -m src.pipeline
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

- `results/webscraping_precios_vino_clean.csv`
- `results/eda_resumen_por_retailer_categoria.csv`
- `results/data_quality_report.csv`

## Variables para BCCR

El pipeline principal no requiere credenciales. Solo el extractor de BCCR necesita estas
variables de entorno:

```powershell
$env:BCCR_EMAIL="tu-correo"
$env:BCCR_TOKEN="tu-token"
```

## Notas

- `data/raw/` y `data/processed/` estan vacios; los datos usados por el pipeline estan en
  `results/`.
- No hay aplicacion Streamlit en el codigo actual, aunque `streamlit` aparece en
  `requirements.txt`.
- No hay pruebas automatizadas implementadas en `tests/`.

## Problema conocido: Python 3.14

Si intentas instalar con Python 3.14, puedes ver un error parecido a:

```text
Preparing metadata (pyproject.toml) did not run successfully
ERROR: Could not find ... Visual Studio ... vswhere.exe
```

Esto ocurre porque `pandas==2.2.3` no encuentra una rueda compatible para esa version de
Python y `pip` intenta compilar pandas localmente. La solucion recomendada es instalar
Python 3.12, borrar el entorno `.venv` creado con Python 3.14 y repetir la instalacion.
