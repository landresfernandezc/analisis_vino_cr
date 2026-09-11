from pathlib import Path
import yaml
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

def load_yaml(path: str | Path) -> dict:
    """Load a YAML file using UTF-8 and return its parsed dictionary."""
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def save_csv(df: pd.DataFrame, relative_path: str) -> Path:
    """Save a dataframe below the project root and return the created path."""
    path = ROOT / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding='utf-8-sig')
    return path
