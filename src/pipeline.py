from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.analysis.eda import quality_report, retailer_category_summary
from src.analysis.graphs import generate_graphs
from src.extractors.retail_scraper import RetailSource, RetailWineScraper
from src.transformers.clean_prices import clean_price_columns
from src.utils.io import ROOT, load_yaml, save_csv
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def build_retail_sources(config_path: Path) -> list[RetailSource]:
    """Read the YAML configuration and convert enabled categories into sources.

    Each enabled category becomes one RetailSource, which keeps the scraper
    independent from the shape of the configuration file.
    """
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
    """Execute the web scraper and persist the raw extraction result.

    Raises RuntimeError when there are no enabled sources or when the scraper
    returns an empty dataset, because later cleaning steps require raw rows.
    """
    sources = build_retail_sources(config_path)
    if not sources:
        raise RuntimeError(f'No hay fuentes de scraping habilitadas en {config_path}')

    logger.info('Ejecutando scraping en vivo para %s fuentes', len(sources))
    raw = RetailWineScraper(sources=sources, sleep_seconds=sleep_seconds, verify_ssl=verify_ssl).extract()
    if raw.empty:
        raise RuntimeError('El scraping en vivo no devolvio filas. Revisa fuentes, selectores o bloqueo de los sitios.')

    save_csv(raw, 'results/webscraping_precios_vino_raw.csv')
    return raw


def run_outputs(raw: pd.DataFrame) -> None:
    """Create the cleaned dataset and analysis CSV outputs from raw prices."""
    required_columns = {'precio_lista_crc', 'precio_oferta_crc', 'presentacion_ml', 'producto', 'retailer', 'categoria'}
    missing = required_columns.difference(raw.columns)
    if missing:
        raise RuntimeError(f'El dataset raw no tiene las columnas requeridas: {sorted(missing)}')

    # Normalize and filter the raw extraction before any analytical summaries.
    clean = clean_price_columns(raw)
    save_csv(clean, 'results/webscraping_precios_vino_clean.csv')
    save_csv(retailer_category_summary(clean), 'results/eda_resumen_por_retailer_categoria.csv')

    # Build a temporary raw view with comparable numeric price fields so the
    # quality report can measure loss between extraction and cleaning.
    raw_tmp = raw.copy()
    raw_tmp['precio_lista_crc'] = pd.to_numeric(raw_tmp['precio_lista_crc'], errors='coerce')
    raw_tmp['precio_oferta_crc'] = pd.to_numeric(raw_tmp['precio_oferta_crc'], errors='coerce')
    raw_tmp['precio_final_crc'] = raw_tmp['precio_oferta_crc'].fillna(raw_tmp['precio_lista_crc'])
    save_csv(quality_report(raw_tmp, clean), 'results/data_quality_report.csv')

    # Generate visual outputs only after the cleaned datasets are available.
    graph_paths = generate_graphs(clean)
    logger.info('Graficos generados: %s', ', '.join(str(path) for path in graph_paths))
    logger.info('Pipeline finalizado correctamente')


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
    run_outputs(raw)


if __name__ == '__main__':
    main()
