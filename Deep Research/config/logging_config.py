"""
Centralized logging configuration for the application.
"""
import logging
import sys
from typing import Optional

def setup_logging(level: int = logging.INFO, log_file: Optional[str] = None) -> None:
    """Configure application-wide logging."""
    
    # Clear any existing handlers
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # File handler (if specified)
    handlers = [console_handler]
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    
    # Configure root logger
    logging.basicConfig(
        level=level,
        handlers=handlers,
        force=True
    )
    
    # Suppress noisy Azure SDK logs
    azure_loggers = [
        'azure', 'azure.core', 'azure.identity', 
        'azure.ai.projects', 'azure.ai.agents',
        'urllib3', 'msal'
    ]
    for logger_name in azure_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    
    # Our application logs at INFO level
    logging.getLogger(__name__.split('.')[0]).setLevel(logging.INFO)
    
    logging.info("Logging configured successfully")

# Convenience function for quick debug logging
def log_debug(module: str, message: str, data: dict = None) -> None:
    """Helper for consistent debug logging."""
    logger = logging.getLogger(module)
    if data:
        logger.debug(f"{message} - {data}")
    else:
        logger.debug(message)