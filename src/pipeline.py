from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

import pandas as pd

from src.analysis.eda import quality_report, retailer_category_summary
from src.analysis.graphs import generate_graphs
from src.extractors.bccr_api import (
    BCCRApiExtractor,
    BCCRIndicator,
    BCCRPublicExchangeRateExtractor,
    GoMetaExchangeRateExtractor,
)
from src.extractors.retail_scraper import RetailSource, RetailWineScraper
from src.transformers.clean_prices import CLEAN_OUTPUT_COLUMNS, clean_price_columns, normalize_text
from src.utils.io import ROOT, load_yaml, save_csv
from src.utils.logging_config import get_logger
from src.utils.s3_storage import (
    S3Upload,
    append_csv_dataset_to_s3,
    append_exchange_rate_dataset_to_s3,
    build_clean_history_key,
    build_dataset_uploads,
    build_latest_clean_key,
    read_csv_from_s3,
    upload_files_to_s3,
)

logger = get_logger(__name__)
CLEAN_DEDUPE_COLUMNS = ['fecha_extraccion', 'retailer', 'categoria', 'producto']
DEFAULT_CLEAN_IMPORT_DIR = ROOT / 'data' / 'manual_clean_imports'


def build_retail_sources(config_path: Path) -> list[RetailSource]:
    """Read the YAML configuration and convert enabled categories into sources."""
    config = load_yaml(config_path)
    sources = []
    for retailer_config in config.get('scraping_sources', []):
        if not retailer_config.get('enabled', True):
            continue
        retailer = retailer_config['retailer']
        for category in retailer_config.get('categories', []):
            sources.append(
                RetailSource(
                    retailer=retailer,
                    category=category['name'],
                    url=category['url'],
                )
            )
    return sources


def run_live_scraping(config_path: Path, sleep_seconds: float, verify_ssl: bool) -> pd.DataFrame:
    """Execute the web scraper and return the raw extraction result."""
    sources = build_retail_sources(config_path)
    if not sources:
        raise RuntimeError(f'No hay fuentes de scraping habilitadas en {config_path}')

    logger.info('Ejecutando scraping en vivo para %s fuentes', len(sources))
    raw = RetailWineScraper(sources=sources, sleep_seconds=sleep_seconds, verify_ssl=verify_ssl).extract()
    if raw.empty:
        raise RuntimeError('El scraping en vivo no devolvio filas. Revisa fuentes, selectores o bloqueo de los sitios.')
    return raw


def stamp_extraction_date(raw: pd.DataFrame, run_date: str) -> pd.DataFrame:
    """Set the extraction date used by the daily raw and clean datasets."""
    stamped = raw.copy()
    stamped['fecha_extraccion'] = pd.to_datetime(run_date).date().isoformat()
    return stamped


def _run_date_for_bccr(run_date: str) -> str:
    """Convert the ISO pipeline date to the BCCR dd/mm/YYYY format."""
    return pd.to_datetime(run_date).strftime('%d/%m/%Y')


def normalize_bccr_exchange_rate(raw: pd.DataFrame, run_date: str) -> pd.DataFrame:
    """Normalize BCCR exchange-rate rows into a compact daily dataset."""
    out = raw.copy()
    column_map = {
        'DES_FECHA': 'fecha',
        'Fecha': 'fecha',
        'NUM_VALOR': 'valor_crc',
        'Valor': 'valor_crc',
    }
    out = out.rename(columns={column: column_map[column] for column in column_map if column in out.columns})
    if 'fecha' not in out.columns:
        out['fecha'] = run_date
    if 'valor_crc' not in out.columns:
        numeric_columns = out.select_dtypes(include='number').columns.difference(['codigo_indicador'])
        if numeric_columns.empty:
            raise RuntimeError('La respuesta BCCR no contiene una columna numerica de valor.')
        out['valor_crc'] = out[numeric_columns[0]]

    out['fecha'] = pd.to_datetime(out['fecha'], errors='coerce').dt.date.astype(str)
    out['fecha_extraccion'] = pd.to_datetime(run_date).date().isoformat()
    out['valor_crc'] = pd.to_numeric(out['valor_crc'], errors='coerce')
    columns = ['fecha', 'fecha_extraccion', 'indicador', 'codigo_indicador', 'valor_crc', 'fuente', 'url_fuente', 'updated']
    return out[[column for column in columns if column in out.columns]].dropna(subset=['valor_crc'])


def run_exchange_rate_output(run_date: str, enabled: bool, verify_ssl: bool) -> Path | None:
    """Fetch BCCR USD buy/sell exchange rates and save the daily CSV."""
    if not enabled:
        logger.info('Extraccion de tipo de cambio omitida por configuracion')
        return None

    indicators = [
        BCCRIndicator(name='tipo_cambio_compra_usd', code=317),
        BCCRIndicator(name='tipo_cambio_venta_usd', code=318),
    ]
    errors = []
    exchange = pd.DataFrame()
    extractors = [
        ('bccr_public_json', BCCRPublicExchangeRateExtractor(indicators=indicators, verify_ssl=verify_ssl)),
        ('gometa_tdc', GoMetaExchangeRateExtractor(verify_ssl=verify_ssl)),
    ]
    if os.getenv('BCCR_EMAIL') and os.getenv('BCCR_TOKEN'):
        bccr_date = _run_date_for_bccr(run_date)
        extractors.append((
            'bccr_legacy_webservice',
            BCCRApiExtractor(indicators=indicators, start_date=bccr_date, end_date=bccr_date),
        ))

    for source_name, extractor in extractors:
        try:
            exchange = normalize_bccr_exchange_rate(extractor.extract(), run_date)
            if not exchange.empty:
                logger.info('Tipo de cambio obtenido desde %s', source_name)
                break
        except Exception as exc:
            errors.append(f'{source_name}: {exc}')
            logger.warning('No se pudo obtener tipo de cambio desde %s: %s', source_name, exc)

    if exchange.empty:
        logger.warning('No se obtuvo tipo de cambio para %s. Errores: %s', run_date, ' | '.join(errors))
        return None
    path = save_csv(exchange, 'results/tipo_cambio_bccr.csv')
    logger.info('Tipo de cambio BCCR guardado: %s', path)
    return path


def add_exchange_rate_columns(clean: pd.DataFrame, exchange_path: Path | None) -> pd.DataFrame:
    """Add buy/sell exchange rates as columns to every cleaned wine-price row."""
    out = clean.copy()
    out['tipo_cambio_compra_usd'] = pd.NA
    out['tipo_cambio_venta_usd'] = pd.NA
    if not exchange_path or not exchange_path.exists():
        return out

    exchange = pd.read_csv(exchange_path)
    for indicator, column in {
        'tipo_cambio_compra_usd': 'tipo_cambio_compra_usd',
        'tipo_cambio_venta_usd': 'tipo_cambio_venta_usd',
    }.items():
        values = exchange.loc[exchange['indicador'] == indicator, 'valor_crc']
        if not values.empty:
            out[column] = float(values.iloc[-1])
    return out


def prepare_clean_history(df: pd.DataFrame) -> pd.DataFrame:
    """Align an existing clean CSV with the current public output schema."""
    out = df.copy()
    if 'producto_normalizado' in out.columns:
        out['producto'] = out['producto_normalizado']
    if 'retailer_normalizado' in out.columns:
        out['retailer'] = out['retailer_normalizado']
    if 'producto' in out.columns:
        out['producto'] = out['producto'].apply(normalize_text)
    if 'retailer' in out.columns:
        out['retailer'] = out['retailer'].apply(normalize_text)
    for column in ['precio_lista_crc', 'precio_oferta_crc', 'precio_final_crc', 'presentacion_ml']:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors='coerce')
    if {'precio_lista_crc', 'precio_oferta_crc'}.issubset(out.columns):
        out['precio_final_crc'] = out.get('precio_final_crc', pd.Series(index=out.index, dtype='float64'))
        out['precio_final_crc'] = out['precio_final_crc'].fillna(out['precio_oferta_crc']).fillna(out['precio_lista_crc'])
    if {'precio_final_crc', 'presentacion_ml'}.issubset(out.columns):
        equivalent = (out['precio_final_crc'] / out['presentacion_ml'] * 750).round(2)
        out['precio_equivalente_750ml_crc'] = out.get(
            'precio_equivalente_750ml_crc',
            pd.Series(index=out.index, dtype='float64'),
        )
        out['precio_equivalente_750ml_crc'] = out['precio_equivalente_750ml_crc'].fillna(equivalent)
    return out.reindex(columns=CLEAN_OUTPUT_COLUMNS)


def dedupe_clean_history(df: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicate product snapshots from the accumulated clean dataset."""
    out = df.copy()
    normalized_key_columns = []
    for column in CLEAN_DEDUPE_COLUMNS:
        if column not in out.columns:
            continue
        key_column = f'__dedupe_{column}'
        normalized_key_columns.append(key_column)
        if column in {'retailer', 'categoria', 'producto'}:
            out[key_column] = out[column].apply(normalize_text)
        else:
            out[key_column] = out[column]
    dedupe_columns = normalized_key_columns
    if not dedupe_columns:
        return out
    out['__dedupe_completeness'] = out[CLEAN_OUTPUT_COLUMNS].notna().sum(axis=1)
    out = out.sort_values('__dedupe_completeness')
    out = out.drop_duplicates(subset=dedupe_columns, keep='last')
    return out.drop(columns=normalized_key_columns + ['__dedupe_completeness'])


def run_outputs(raw: pd.DataFrame, exchange_path: Path | None = None) -> dict[str, Path]:
    """Create the cleaned dataset and analysis CSV outputs from raw prices."""
    required_columns = {'precio_lista_crc', 'precio_oferta_crc', 'presentacion_ml', 'producto', 'retailer', 'categoria'}
    missing = required_columns.difference(raw.columns)
    if missing:
        raise RuntimeError(f'El dataset raw no tiene las columnas requeridas: {sorted(missing)}')

    clean = clean_price_columns(raw)
    clean = add_exchange_rate_columns(clean, exchange_path)
    clean = prepare_clean_history(clean)
    clean_path = ROOT / 'results' / 'webscraping_precios_vino_clean.csv'
    if clean_path.exists():
        previous = prepare_clean_history(pd.read_csv(clean_path))
        accumulated = pd.concat([previous, clean], ignore_index=True)
    else:
        accumulated = clean
    accumulated = dedupe_clean_history(accumulated)
    clean_path = save_csv(accumulated, 'results/webscraping_precios_vino_clean.csv')
    latest_path = save_csv(accumulated, 'results/latest_webscraping_precios_vino_clean.csv')
    summary_path = save_csv(retailer_category_summary(accumulated), 'results/eda_resumen_por_retailer_categoria.csv')

    raw_tmp = raw.copy()
    raw_tmp['precio_lista_crc'] = pd.to_numeric(raw_tmp['precio_lista_crc'], errors='coerce')
    raw_tmp['precio_oferta_crc'] = pd.to_numeric(raw_tmp['precio_oferta_crc'], errors='coerce')
    raw_tmp['precio_final_crc'] = raw_tmp['precio_oferta_crc'].fillna(raw_tmp['precio_lista_crc'])
    quality_path = save_csv(quality_report(raw_tmp, accumulated), 'results/data_quality_report.csv')

    graph_paths = generate_graphs(accumulated)
    logger.info('Graficos generados: %s', ', '.join(str(path) for path in graph_paths))
    logger.info('Pipeline finalizado correctamente')
    return {
        'clean': clean_path,
        'latest': latest_path,
        'summary': summary_path,
        'quality': quality_path,
    }


def hydrate_clean_history_from_s3(bucket: str, prefix: str = '') -> Path | None:
    """Download the accumulated clean history so stateless daily runs can append to it."""
    if not bucket:
        return None

    for key in [build_clean_history_key(prefix), build_latest_clean_key(prefix)]:
        history = read_csv_from_s3(bucket, key)
        if history is None or history.empty:
            continue
        history = prepare_clean_history(history)
        local_path = ROOT / 'results' / 'webscraping_precios_vino_clean.csv'
        if local_path.exists():
            local_history = prepare_clean_history(pd.read_csv(local_path))
            history = pd.concat([history, local_history], ignore_index=True)
        history = dedupe_clean_history(history)
        path = save_csv(history, 'results/webscraping_precios_vino_clean.csv')
        logger.info('Historico limpio descargado desde s3://%s/%s | filas=%s', bucket, key, len(history))
        return path
    return None


def sync_local_clean_history_to_s3(bucket: str, prefix: str = '') -> list[str]:
    """Overwrite S3 clean/latest datasets with the local accumulated clean CSV."""
    clean_path = ROOT / 'results' / 'webscraping_precios_vino_clean.csv'
    if not clean_path.exists():
        raise FileNotFoundError(f'No existe el historico limpio local: {clean_path}')

    clean = dedupe_clean_history(prepare_clean_history(pd.read_csv(clean_path)))
    clean_path = save_csv(clean, 'results/webscraping_precios_vino_clean.csv')
    latest_path = save_csv(clean, 'results/latest_webscraping_precios_vino_clean.csv')
    uploads = [
        S3Upload(local_path=clean_path, key=build_clean_history_key(prefix)),
        S3Upload(local_path=latest_path, key=build_latest_clean_key(prefix)),
    ]
    keys = upload_files_to_s3(bucket, uploads)
    logger.info('Historico limpio local sincronizado a S3 | filas=%s', len(clean))
    return keys


def dedupe_local_clean_history() -> dict[str, Path]:
    """Deduplicate and rewrite the local clean/latest accumulated datasets."""
    clean_path = ROOT / 'results' / 'webscraping_precios_vino_clean.csv'
    if not clean_path.exists():
        raise FileNotFoundError(f'No existe el historico limpio local: {clean_path}')

    clean = dedupe_clean_history(prepare_clean_history(pd.read_csv(clean_path)))
    clean_path = save_csv(clean, 'results/webscraping_precios_vino_clean.csv')
    latest_path = save_csv(clean, 'results/latest_webscraping_precios_vino_clean.csv')
    logger.info('Historico limpio local deduplicado | filas=%s', len(clean))
    return {'clean': clean_path, 'latest': latest_path}


def merge_clean_csv_folder(import_dir: Path = DEFAULT_CLEAN_IMPORT_DIR) -> dict[str, Path]:
    """Merge all CSV files in a folder into the local accumulated clean dataset."""
    clean_path = ROOT / 'results' / 'webscraping_precios_vino_clean.csv'
    csv_paths = sorted(path for path in import_dir.glob('*.csv') if path.is_file())
    if not csv_paths:
        raise FileNotFoundError(f'No encontre CSV para unir en: {import_dir}')

    frames = []
    if clean_path.exists():
        frames.append(prepare_clean_history(pd.read_csv(clean_path)))
    frames.extend(prepare_clean_history(pd.read_csv(path)) for path in csv_paths)

    merged = dedupe_clean_history(pd.concat(frames, ignore_index=True))
    clean_path = save_csv(merged, 'results/webscraping_precios_vino_clean.csv')
    latest_path = save_csv(merged, 'results/latest_webscraping_precios_vino_clean.csv')
    logger.info(
        'CSV locales unidos desde %s | archivos=%s | filas=%s',
        import_dir,
        len(csv_paths),
        len(merged),
    )
    return {'clean': clean_path, 'latest': latest_path}


def parse_args() -> argparse.Namespace:
    """Parse command-line options for running the pipeline script."""
    parser = argparse.ArgumentParser(description='Pipeline de obtencion y limpieza de precios de vino en Costa Rica.')
    parser.add_argument(
        '--from-existing',
        action='store_true',
        help='Usa results/webscraping_precios_vino_raw.csv en vez de ejecutar scraping en vivo.',
    )
    parser.add_argument(
        '--config',
        default=str(ROOT / 'src' / 'config' / 'sources.yaml'),
        help='Ruta al YAML con fuentes de scraping.',
    )
    parser.add_argument(
        '--sleep-seconds',
        type=float,
        default=2.0,
        help='Pausa entre solicitudes para scraping responsable.',
    )
    parser.add_argument(
        '--no-verify-ssl',
        action='store_true',
        help='Desactiva la validacion SSL si el equipo no puede validar certificados de los sitios.',
    )
    parser.add_argument(
        '--upload-s3',
        action='store_true',
        help='Sube el raw historico y clean historico a AWS S3, y actualiza el clean acumulado latest.',
    )
    parser.add_argument(
        '--sync-local-clean-s3',
        action='store_true',
        help='Sube el clean local acumulado a S3 clean/ y latest/ sin ejecutar scraping.',
    )
    parser.add_argument(
        '--merge-clean-folder',
        default='',
        help='Une todos los CSV de una carpeta al clean local acumulado sin ejecutar scraping.',
    )
    parser.add_argument(
        '--dedupe-local-clean',
        action='store_true',
        help='Deduplica el clean local acumulado y regenera latest sin ejecutar scraping.',
    )
    parser.add_argument(
        '--s3-bucket',
        default=os.getenv('AWS_S3_BUCKET', ''),
        help='Bucket S3 destino. Tambien puede configurarse con AWS_S3_BUCKET.',
    )
    parser.add_argument(
        '--s3-prefix',
        default=os.getenv('AWS_S3_PREFIX', ''),
        help='Prefijo opcional dentro del bucket, por ejemplo tfm-vino-cr.',
    )
    parser.add_argument(
        '--run-date',
        default=os.getenv('PIPELINE_RUN_DATE', date.today().isoformat()),
        help='Fecha usada para los registros diarios y las particiones S3 fecha=YYYY-MM-DD.',
    )
    parser.add_argument(
        '--skip-exchange-rate',
        action='store_true',
        help='Omite la consulta diaria del tipo de cambio BCCR.',
    )
    return parser.parse_args()


def main():
    """Coordinate extraction/loading of raw data and generation of outputs."""
    args = parse_args()
    if args.dedupe_local_clean:
        dedupe_local_clean_history()
        return

    if args.merge_clean_folder:
        merge_clean_csv_folder(Path(args.merge_clean_folder))
        return

    if args.sync_local_clean_s3:
        sync_local_clean_history_to_s3(args.s3_bucket, args.s3_prefix)
        return

    raw_path = ROOT / 'results' / 'webscraping_precios_vino_raw.csv'
    if args.from_existing:
        logger.info('Usando CSV raw existente: %s', raw_path)
        raw = pd.read_csv(raw_path)
    else:
        raw = run_live_scraping(Path(args.config), args.sleep_seconds, not args.no_verify_ssl)

    raw = stamp_extraction_date(raw, args.run_date)
    raw_path = save_csv(raw, 'results/webscraping_precios_vino_raw.csv')
    exchange_path = run_exchange_rate_output(
        args.run_date,
        enabled=not args.skip_exchange_rate,
        verify_ssl=not args.no_verify_ssl,
    )
    if args.upload_s3:
        hydrate_clean_history_from_s3(args.s3_bucket, args.s3_prefix)
    output_paths = run_outputs(raw, exchange_path=exchange_path)

    if args.upload_s3:
        uploads = build_dataset_uploads(
            raw_path=raw_path,
            clean_path=output_paths['clean'],
            latest_path=output_paths['latest'],
            run_date=args.run_date,
            prefix=args.s3_prefix,
        )
        if exchange_path:
            uploads.append(
                S3Upload(
                    local_path=exchange_path,
                    key='/'.join(
                        part.strip('/')
                        for part in [
                            args.s3_prefix,
                            f'exchange_rate/fecha={args.run_date}',
                            exchange_path.name,
                        ]
                        if part.strip('/')
                    ),
                )
            )
        upload_files_to_s3(
            args.s3_bucket,
            [
                upload
                for upload in uploads
                if upload.local_path == raw_path or '/exchange_rate/' in f'/{upload.key}/'
            ],
        )
        clean_upload, latest_upload = uploads[1:3]
        append_csv_dataset_to_s3(
            bucket=args.s3_bucket,
            csv_path=clean_upload.local_path,
            key=clean_upload.key,
            dedupe_columns=CLEAN_DEDUPE_COLUMNS,
        )
        append_csv_dataset_to_s3(
            bucket=args.s3_bucket,
            csv_path=latest_upload.local_path,
            key=latest_upload.key,
            dedupe_columns=CLEAN_DEDUPE_COLUMNS,
        )
        if exchange_path:
            append_exchange_rate_dataset_to_s3(
                bucket=args.s3_bucket,
                exchange_path=exchange_path,
                prefix=args.s3_prefix,
            )


if __name__ == '__main__':
    main()
