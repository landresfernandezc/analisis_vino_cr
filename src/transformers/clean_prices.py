from __future__ import annotations

import re
import pandas as pd


def normalize_text(value: object) -> str | None:
    if pd.isna(value):
        return None
    return re.sub(r'\s+', ' ', str(value).strip().lower())


def clean_price_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['precio_final_crc'] = out['precio_oferta_crc'].fillna(out['precio_lista_crc'])
    out['precio_final_crc'] = pd.to_numeric(out['precio_final_crc'], errors='coerce')
    out['precio_lista_crc'] = pd.to_numeric(out['precio_lista_crc'], errors='coerce')
    out['presentacion_ml'] = pd.to_numeric(out['presentacion_ml'], errors='coerce')
    out['producto_normalizado'] = out['producto'].apply(normalize_text)
    out['retailer_normalizado'] = out['retailer'].apply(normalize_text)
    out = out.dropna(subset=['producto_normalizado', 'precio_final_crc', 'presentacion_ml'])
    out = out[out['precio_final_crc'] > 0]
    out = out.drop_duplicates(['retailer_normalizado', 'producto_normalizado', 'precio_final_crc'])
    out['precio_equivalente_750ml_crc'] = (out['precio_final_crc'] / out['presentacion_ml'] * 750).round(2)
    out['segmento_precio'] = pd.cut(
        out['precio_equivalente_750ml_crc'],
        bins=[0, 5000, 10000, 15000, 999999],
        labels=['económico', 'medio', 'premium', 'super premium']
    )
    return out
