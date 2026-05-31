from abc import ABC, abstractmethod
import pandas as pd

class BaseExtractor(ABC):
    """Common interface for extraction classes that return pandas data."""

    @abstractmethod
    def extract(self) -> pd.DataFrame:
        """Return extracted data as a dataframe."""
        raise NotImplementedError
