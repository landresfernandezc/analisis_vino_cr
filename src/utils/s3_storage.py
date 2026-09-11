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
    latest_path: Path,
    run_date: str,
    prefix: str = '',
) -> list[S3Upload]:
    """Create S3 uploads for raw history, accumulated clean, and latest clean."""
    return [
        S3Upload(
            local_path=raw_path,
            key=_join_s3_key(prefix, f'raw/fecha={run_date}', raw_path.name),
        ),
        S3Upload(
            local_path=clean_path,
            key=_join_s3_key(prefix, 'clean', clean_path.name),
        ),
        S3Upload(
            local_path=latest_path,
            key=build_latest_clean_key(prefix),
        ),
    ]


def build_latest_clean_key(prefix: str = '') -> str:
    """Return the S3 key for the latest clean dataset consumed by Streamlit."""
    return _join_s3_key(prefix, 'latest', 'webscraping_precios_vino_clean.csv')


def build_latest_exchange_rate_key(prefix: str = '') -> str:
    """Return the S3 key for the accumulated exchange-rate dataset."""
    return _join_s3_key(prefix, 'latest', 'tipo_cambio_bccr.csv')


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


def append_csv_dataset_to_s3(
    bucket: str,
    csv_path: Path,
    key: str,
    dedupe_columns: list[str],
) -> str:
    """Append a local CSV to an accumulated CSV in S3."""
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError as exc:
        raise RuntimeError('boto3 no esta instalado. Ejecuta pip install -r requirements.txt') from exc

    if not bucket:
        raise RuntimeError('Debes configurar AWS_S3_BUCKET o pasar --s3-bucket.')
    if not csv_path.exists():
        raise FileNotFoundError(f'No existe el CSV para acumular en S3: {csv_path}')

    client = boto3.client('s3')
    today_df = pd.read_csv(csv_path)

    try:
        response = client.get_object(Bucket=bucket, Key=key)
        existing_df = pd.read_csv(BytesIO(response['Body'].read()))
        accumulated = pd.concat([existing_df, today_df], ignore_index=True)
    except ClientError as exc:
        error_code = exc.response.get('Error', {}).get('Code')
        if error_code not in {'NoSuchKey', '404'}:
            raise
        accumulated = today_df

    existing_dedupe_columns = [column for column in dedupe_columns if column in accumulated.columns]
    if existing_dedupe_columns:
        accumulated = accumulated.drop_duplicates(subset=existing_dedupe_columns, keep='last')

    csv_bytes = accumulated.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=csv_bytes,
        ContentType='text/csv; charset=utf-8',
    )
    logger.info('Dataset acumulado actualizado en s3://%s/%s | filas=%s', bucket, key, len(accumulated))
    return key


def append_exchange_rate_dataset_to_s3(bucket: str, exchange_path: Path, prefix: str = '') -> str:
    """Append today's exchange-rate rows to the accumulated exchange-rate CSV in S3."""
    return append_csv_dataset_to_s3(
        bucket=bucket,
        csv_path=exchange_path,
        key=build_latest_exchange_rate_key(prefix),
        dedupe_columns=['fecha', 'codigo_indicador'],
    )
