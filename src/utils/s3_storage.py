from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pandas as pd

from src.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class S3Upload:
    """Local file and destination key for one S3 upload."""

    local_path: Path
    key: str


def _join_s3_key(*parts: str) -> str:
    """Join S3 key parts without introducing duplicate slashes."""
    return '/'.join(part.strip('/') for part in parts if part and part.strip('/'))


def build_dataset_uploads(
    raw_path: Path,
    clean_path: Path,
    run_date: str,
    prefix: str = '',
) -> list[S3Upload]:
    """Create the historical S3 keys for the daily raw and clean datasets."""
    return [
        S3Upload(
            local_path=raw_path,
            key=_join_s3_key(prefix, f'raw/fecha={run_date}', raw_path.name),
        ),
        S3Upload(
            local_path=clean_path,
            key=_join_s3_key(prefix, f'clean/fecha={run_date}', clean_path.name),
        ),
    ]


def build_latest_clean_key(prefix: str = '') -> str:
    """Return the S3 key for the accumulated clean dataset consumed by Streamlit."""
    return _join_s3_key(prefix, 'latest', 'webscraping_precios_vino_clean.csv')


def upload_files_to_s3(bucket: str, uploads: list[S3Upload]) -> list[str]:
    """Upload files to S3 and return the destination keys."""
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError('boto3 no esta instalado. Ejecuta pip install -r requirements.txt') from exc

    if not bucket:
        raise RuntimeError('Debes configurar AWS_S3_BUCKET o pasar --s3-bucket.')

    client = boto3.client('s3')
    uploaded_keys = []
    for upload in uploads:
        if not upload.local_path.exists():
            raise FileNotFoundError(f'No existe el archivo para subir a S3: {upload.local_path}')
        client.upload_file(
            str(upload.local_path),
            bucket,
            upload.key,
            ExtraArgs={'ContentType': 'text/csv; charset=utf-8'},
        )
        logger.info('Archivo subido a s3://%s/%s', bucket, upload.key)
        uploaded_keys.append(upload.key)
    return uploaded_keys


def append_clean_dataset_to_s3(bucket: str, clean_path: Path, prefix: str = '') -> str:
    """Append today's clean records to the accumulated clean CSV in S3."""
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError as exc:
        raise RuntimeError('boto3 no esta instalado. Ejecuta pip install -r requirements.txt') from exc

    if not bucket:
        raise RuntimeError('Debes configurar AWS_S3_BUCKET o pasar --s3-bucket.')
    if not clean_path.exists():
        raise FileNotFoundError(f'No existe el clean diario para acumular en S3: {clean_path}')

    key = build_latest_clean_key(prefix)
    client = boto3.client('s3')
    today_clean = pd.read_csv(clean_path)

    try:
        response = client.get_object(Bucket=bucket, Key=key)
        existing_clean = pd.read_csv(BytesIO(response['Body'].read()))
        accumulated = pd.concat([existing_clean, today_clean], ignore_index=True)
    except ClientError as exc:
        error_code = exc.response.get('Error', {}).get('Code')
        if error_code not in {'NoSuchKey', '404'}:
            raise
        accumulated = today_clean

    dedupe_columns = [
        column for column in [
            'fecha_extraccion',
            'retailer_normalizado',
            'producto_normalizado',
            'categoria',
            'url_fuente',
            'precio_final_crc',
        ]
        if column in accumulated.columns
    ]
    if dedupe_columns:
        accumulated = accumulated.drop_duplicates(subset=dedupe_columns, keep='last')

    csv_bytes = accumulated.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=csv_bytes,
        ContentType='text/csv; charset=utf-8',
    )
    logger.info('Dataset clean acumulado actualizado en s3://%s/%s | filas=%s', bucket, key, len(accumulated))
    return key
