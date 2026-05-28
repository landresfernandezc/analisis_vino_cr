from pathlib import Path
import pandas as pd

from src.transformers.clean_prices import clean_price_columns
from src.analysis.eda import retailer_category_summary, quality_report
from src.utils.io import save_csv, ROOT
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def main():
    raw_path = ROOT / 'results' / 'webscraping_precios_vino_raw.csv'
    raw = pd.read_csv(raw_path)
    clean = clean_price_columns(raw)
    save_csv(clean, 'results/webscraping_precios_vino_clean.csv')
    save_csv(retailer_category_summary(clean), 'results/eda_resumen_por_retailer_categoria.csv')
    raw_tmp = raw.copy()
    raw_tmp['precio_final_crc'] = raw_tmp['precio_oferta_crc'].fillna(raw_tmp['precio_lista_crc'])
    save_csv(quality_report(raw_tmp, clean), 'results/data_quality_report.csv')
    logger.info('Pipeline finalizado correctamente')

if __name__ == '__main__':
    main()
