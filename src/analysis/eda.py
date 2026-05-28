from __future__ import annotations

import pandas as pd


def retailer_category_summary(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(['retailer', 'categoria'])
        .agg(
            productos=('producto', 'count'),
            precio_promedio_750ml_crc=('precio_equivalente_750ml_crc', 'mean'),
            precio_min_750ml_crc=('precio_equivalente_750ml_crc', 'min'),
            precio_max_750ml_crc=('precio_equivalente_750ml_crc', 'max'),
        )
        .round(2)
        .reset_index()
    )


def quality_report(raw: pd.DataFrame, clean: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        'metrica': [
            'filas_raw', 'filas_clean', 'faltantes_precio_final_raw',
            'retailers', 'categorias', 'precio_min_750ml',
            'precio_promedio_750ml', 'precio_mediana_750ml', 'precio_max_750ml'
        ],
        'valor': [
            len(raw), len(clean), raw['precio_final_crc'].isna().sum() if 'precio_final_crc' in raw else None,
            clean['retailer'].nunique(), clean['categoria'].nunique(),
            clean['precio_equivalente_750ml_crc'].min(),
            round(clean['precio_equivalente_750ml_crc'].mean(), 2),
            round(clean['precio_equivalente_750ml_crc'].median(), 2),
            clean['precio_equivalente_750ml_crc'].max(),
        ]
    })
