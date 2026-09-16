from pathlib import Path
from uuid import uuid4

import pandas as pd

from src import pipeline


def _test_root() -> Path:
    return Path('.test-output') / f'pipeline-{uuid4().hex}'


def test_run_outputs_accumulates_latest_clean_file(monkeypatch):
    root = _test_root()
    output_root = root / 'results'

    def save_csv(dataframe, relative_path):
        path = output_root / relative_path.removeprefix('results/')
        path.parent.mkdir(parents=True, exist_ok=True)
        dataframe.to_csv(path, index=False)
        return path

    monkeypatch.setattr(pipeline, 'ROOT', root)
    monkeypatch.setattr(pipeline, 'save_csv', save_csv)
    monkeypatch.setattr(pipeline, 'generate_graphs', lambda dataframe: [])

    first_run = pd.DataFrame([{
        'fecha_extraccion': '2026-09-15',
        'categoria': 'tinto',
        'precio_lista_crc': 3000,
        'precio_oferta_crc': None,
        'presentacion_ml': 750,
        'producto': 'Vino Uno',
        'retailer': 'Retailer Uno',
    }])
    second_run = first_run.assign(
        fecha_extraccion='2026-09-16',
        producto='Vino Dos',
    )

    pipeline.run_outputs(first_run)
    pipeline.run_outputs(second_run)

    latest = pd.read_csv(output_root / 'latest_webscraping_precios_vino_clean.csv')
    clean = pd.read_csv(output_root / 'webscraping_precios_vino_clean.csv')

    assert len(latest) == 2
    assert len(clean) == 2
    assert set(latest['producto']) == {'vino uno', 'vino dos'}


def test_hydrate_clean_history_from_s3_restores_remote_history(monkeypatch):
    root = _test_root()
    output_root = root / 'results'

    def save_csv(dataframe, relative_path):
        path = output_root / relative_path.removeprefix('results/')
        path.parent.mkdir(parents=True, exist_ok=True)
        dataframe.to_csv(path, index=False)
        return path

    remote_history = pd.DataFrame([{
        'fecha_extraccion': '2026-09-15',
        'categoria': 'tinto',
        'producto': 'vino uno',
        'retailer': 'retailer uno',
        'precio_lista_crc': 3000,
        'precio_oferta_crc': None,
        'precio_final_crc': 3000,
        'presentacion_ml': 750,
        'precio_equivalente_750ml_crc': 3000,
        'tipo_cambio_compra_usd': None,
        'tipo_cambio_venta_usd': None,
    }])

    monkeypatch.setattr(pipeline, 'ROOT', root)
    monkeypatch.setattr(pipeline, 'save_csv', save_csv)
    monkeypatch.setattr(pipeline, 'generate_graphs', lambda dataframe: [])
    monkeypatch.setattr(pipeline, 'read_csv_from_s3', lambda bucket, key: remote_history)

    restored_path = pipeline.hydrate_clean_history_from_s3('bucket-prueba', 'tfm-vino-cr')
    assert restored_path == output_root / 'webscraping_precios_vino_clean.csv'

    today = pd.DataFrame([{
        'fecha_extraccion': '2026-09-16',
        'categoria': 'tinto',
        'precio_lista_crc': 4000,
        'precio_oferta_crc': None,
        'presentacion_ml': 750,
        'producto': 'Vino Dos',
        'retailer': 'Retailer Uno',
    }])
    pipeline.run_outputs(today)

    clean = pd.read_csv(output_root / 'webscraping_precios_vino_clean.csv')
    assert len(clean) == 2
    assert set(clean['fecha_extraccion']) == {'2026-09-15', '2026-09-16'}


def test_sync_local_clean_history_to_s3_uploads_clean_and_latest(monkeypatch):
    root = _test_root()
    output_root = root / 'results'
    output_root.mkdir(parents=True, exist_ok=True)
    local_clean_path = output_root / 'webscraping_precios_vino_clean.csv'
    pd.DataFrame([
        {
            'fecha_extraccion': '2026-09-15',
            'categoria': 'tinto',
            'producto': 'vino uno',
            'retailer': 'retailer uno',
            'precio_lista_crc': 3000,
            'precio_oferta_crc': None,
            'precio_final_crc': 3000,
            'presentacion_ml': 750,
            'precio_equivalente_750ml_crc': 3000,
            'tipo_cambio_compra_usd': None,
            'tipo_cambio_venta_usd': None,
        }
    ]).to_csv(local_clean_path, index=False)

    def save_csv(dataframe, relative_path):
        path = output_root / relative_path.removeprefix('results/')
        path.parent.mkdir(parents=True, exist_ok=True)
        dataframe.to_csv(path, index=False)
        return path

    uploaded = []

    def upload_files_to_s3(bucket, uploads):
        uploaded.extend((bucket, upload.local_path, upload.key) for upload in uploads)
        return [upload.key for upload in uploads]

    monkeypatch.setattr(pipeline, 'ROOT', root)
    monkeypatch.setattr(pipeline, 'save_csv', save_csv)
    monkeypatch.setattr(pipeline, 'upload_files_to_s3', upload_files_to_s3)

    keys = pipeline.sync_local_clean_history_to_s3('bucket-prueba', 'tfm-vino-cr')

    assert keys == [
        'tfm-vino-cr/clean/webscraping_precios_vino_clean.csv',
        'tfm-vino-cr/latest/webscraping_precios_vino_clean.csv',
    ]
    assert len(uploaded) == 2


def test_merge_clean_csv_folder_appends_imports_to_local_clean(monkeypatch):
    root = _test_root()
    output_root = root / 'results'
    import_root = root / 'data' / 'manual_clean_imports'
    output_root.mkdir(parents=True, exist_ok=True)
    import_root.mkdir(parents=True, exist_ok=True)
    local_clean_path = output_root / 'webscraping_precios_vino_clean.csv'

    base_row = {
        'fecha_extraccion': '2026-09-15',
        'categoria': 'tinto',
        'producto': 'vino uno',
        'retailer': 'retailer uno',
        'precio_lista_crc': 3000,
        'precio_oferta_crc': None,
        'precio_final_crc': 3000,
        'presentacion_ml': 750,
        'precio_equivalente_750ml_crc': 3000,
        'tipo_cambio_compra_usd': None,
        'tipo_cambio_venta_usd': None,
    }
    pd.DataFrame([base_row]).to_csv(local_clean_path, index=False)
    pd.DataFrame([
        base_row | {'fecha_extraccion': '2026-09-16', 'producto': 'vino dos'},
        base_row | {'fecha_extraccion': '2026-09-16', 'producto': 'vino dos'},
    ]).to_csv(import_root / 'clean_2026_09_16.csv', index=False)

    def save_csv(dataframe, relative_path):
        path = output_root / relative_path.removeprefix('results/')
        path.parent.mkdir(parents=True, exist_ok=True)
        dataframe.to_csv(path, index=False)
        return path

    monkeypatch.setattr(pipeline, 'ROOT', root)
    monkeypatch.setattr(pipeline, 'save_csv', save_csv)

    paths = pipeline.merge_clean_csv_folder(import_root)

    assert paths['clean'] == output_root / 'webscraping_precios_vino_clean.csv'
    clean = pd.read_csv(paths['clean'])
    latest = pd.read_csv(paths['latest'])
    assert len(clean) == 2
    assert len(latest) == 2
    assert set(clean['fecha_extraccion']) == {'2026-09-15', '2026-09-16'}


def test_dedupe_clean_history_matches_product_case_variants_and_keeps_complete_row():
    rows = pd.DataFrame([
        {
            'fecha_extraccion': '2026-09-16',
            'categoria': 'Vino blanco',
            'precio_lista_crc': 4730.0,
            'precio_oferta_crc': None,
            'descuento_pct': 0,
            'presentacion_ml': 750.0,
            'precio_final_crc': None,
            'producto': 'Vino Sta Rita 3 Med Bco Sauvig 750 Ml',
            'retailer': 'Masxmenos Costa Rica',
            'precio_equivalente_750ml_crc': None,
            'segmento_precio': None,
            'tipo_cambio_compra_usd': None,
            'tipo_cambio_venta_usd': None,
        },
        {
            'fecha_extraccion': '2026-09-16',
            'categoria': 'Vino blanco',
            'precio_lista_crc': 4730.0,
            'precio_oferta_crc': None,
            'descuento_pct': 0,
            'presentacion_ml': 750.0,
            'precio_final_crc': 4730.0,
            'producto': 'vino sta rita 3 med bco sauvig 750 ml',
            'retailer': 'masxmenos costa rica',
            'precio_equivalente_750ml_crc': 4730.0,
            'segmento_precio': 'economico',
            'tipo_cambio_compra_usd': 444.46,
            'tipo_cambio_venta_usd': 449.49,
        },
    ])

    deduped = pipeline.dedupe_clean_history(pipeline.prepare_clean_history(rows))

    assert len(deduped) == 1
    assert deduped.iloc[0]['producto'] == 'vino sta rita 3 med bco sauvig 750 ml'
    assert deduped.iloc[0]['precio_final_crc'] == 4730.0
