from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

import pandas as pd

from src.analysis.eda import quality_report, retailer_category_summary
from src.analysis.graphs import generate_graphs
from src.extractors.retail_scraper import RetailSource, RetailWineScraper
from src.transformers.clean_prices import clean_price_columns
from src.utils.io import ROOT, load_yaml, save_csv
from src.utils.logging_config import get_logger
from src.utils.s3_storage import append_clean_dataset_to_s3, build_dataset_uploads, upload_files_to_s3

logger = get_logger(__name__)


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


def run_outputs(raw: pd.DataFrame) -> dict[str, Path]:
    """Create the cleaned dataset and analysis CSV outputs from raw prices."""
    required_columns = {'precio_lista_crc', 'precio_oferta_crc', 'presentacion_ml', 'producto', 'retailer', 'categoria'}
    missing = required_columns.difference(raw.columns)
    if missing:
        raise RuntimeError(f'El dataset raw no tiene las columnas requeridas: {sorted(missing)}')

    clean = clean_price_columns(raw)
    clean_path = save_csv(clean, 'results/webscraping_precios_vino_clean.csv')
    summary_path = save_csv(retailer_category_summary(clean), 'results/eda_resumen_por_retailer_categoria.csv')

    raw_tmp = raw.copy()
    raw_tmp['precio_lista_crc'] = pd.to_numeric(raw_tmp['precio_lista_crc'], errors='coerce')
    raw_tmp['precio_oferta_crc'] = pd.to_numeric(raw_tmp['precio_oferta_crc'], errors='coerce')
    raw_tmp['precio_final_crc'] = raw_tmp['precio_oferta_crc'].fillna(raw_tmp['precio_lista_crc'])
    quality_path = save_csv(quality_report(raw_tmp, clean), 'results/data_quality_report.csv')

    graph_paths = generate_graphs(clean)
    logger.info('Graficos generados: %s', ', '.join(str(path) for path in graph_paths))
    logger.info('Pipeline finalizado correctamente')
    return {
        'clean': clean_path,
        'summary': summary_path,
        'quality': quality_path,
    }


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
    return parser.parse_args()


def main():
    """Coordinate extraction/loading of raw data and generation of outputs."""
    args = parse_args()
    raw_path = ROOT / 'results' / 'webscraping_precios_vino_raw.csv'
    if args.from_existing:
        logger.info('Usando CSV raw existente: %s', raw_path)
        raw = pd.read_csv(raw_path)
    else:
        raw = run_live_scraping(Path(args.config), args.sleep_seconds, not args.no_verify_ssl)

    raw = stamp_extraction_date(raw, args.run_date)
    raw_path = save_csv(raw, 'results/webscraping_precios_vino_raw.csv')
    output_paths = run_outputs(raw)

    if args.upload_s3:
        uploads = build_dataset_uploads(
            raw_path=raw_path,
            clean_path=output_paths['clean'],
            run_date=args.run_date,
            prefix=args.s3_prefix,
        )
        upload_files_to_s3(args.s3_bucket, uploads)
        append_clean_dataset_to_s3(
            bucket=args.s3_bucket,
            clean_path=output_paths['clean'],
            prefix=args.s3_prefix,
        )


if __name__ == '__main__':
    main()
