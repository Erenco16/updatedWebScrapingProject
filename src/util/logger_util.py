import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

class CustomLogger:
    def __init__(self, name: str, log_file: str = "app.log", level=logging.INFO):
        # 1. Define paths relative to this file
        self.base_dir = Path(__file__).resolve().parent
        self.log_dir = self.base_dir / "logs"
        self.log_dir.mkdir(exist_ok=True)
        self.log_path = self.log_dir / log_file

        # 2. Create the logger
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        # Prevent duplicate handlers if the logger is already initialized
        if not self.logger.handlers:
            self._setup_handlers()

    def _setup_handlers(self):
        # Formatter: Time - Name - Level - Message
        formatter = logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # File Handler (Rotates at 5MB, keeps 3 backups)
        file_handler = RotatingFileHandler(
            self.log_path, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)

        # Console Handler (Prints to terminal)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)

        # Add handlers to logger
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def get_logger(self):
        return self.logger