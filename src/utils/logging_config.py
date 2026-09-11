import logging

def get_logger(name: str) -> logging.Logger:
    """Configure basic application logging and return a named logger."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
    )
    return logging.getLogger(name)
