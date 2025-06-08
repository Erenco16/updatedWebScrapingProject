import logging
import os

# Ensure output directory exists
LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src/output"))
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "scraper.log")

# Configure logger
logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger("hafele_scraper")


def log_info(message: str):
    logger.info(message)


def log_warning(message: str):
    logger.warning(message)


def log_error(message: str):
    logger.error(message)


def log_exception(message: str):
    logger.exception(message)  # Logs full stack trace
