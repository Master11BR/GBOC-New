"""
GBOC Server - Sistema de Logging Estruturado
Suporta JSON logging para melhor análise em produção
"""
import logging
import json
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from config import LOG_LEVEL, LOG_FORMAT, LOG_FILE, LOG_MAX_SIZE_MB, LOG_BACKUP_COUNT, LOG_DIR

class JSONFormatter(logging.Formatter):
    """Formatador customizado para JSON"""

    def format(self, record):
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        return json.dumps(log_data, ensure_ascii=False)

class TextFormatter(logging.Formatter):
    """Formatador customizado para texto"""

    def format(self, record):
        return (
            f"[{record.levelname}] {record.name} - "
            f"{record.message} - {record.module}:{record.lineno}"
        )

class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler imune a PermissionError no Windows durante rotação de logs."""
    def shouldRollover(self, record):
        try:
            return super().shouldRollover(record)
        except PermissionError:
            return False
        except Exception:
            return False

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            pass
        except Exception:
            pass

    def emit(self, record):
        try:
            super().emit(record)
        except PermissionError:
            pass
        except Exception:
            pass

def setup_logger(name: str) -> logging.Logger:
    """
    Configura um logger com suporte a arquivo e console

    Args:
        name: Nome do logger (geralmente __name__)

    Returns:
        logging.Logger: Logger configurado
    """
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)

    # Remover handlers existentes
    logger.handlers.clear()

    # Escolher formatador
    formatter = (
        JSONFormatter() if LOG_FORMAT == "json" 
        else TextFormatter()
    )

    # Handler para console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler para arquivo com rotação
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(os.path.abspath(LOG_FILE)), exist_ok=True)
        file_handler = SafeRotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_SIZE_MB * 1024 * 1024,
            backupCount=LOG_BACKUP_COUNT,
        )
        file_handler.setLevel(LOG_LEVEL)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        pass

    return logger

def log_with_context(logger: logging.Logger, level: str, message: str, **context):
    """
    Log com contexto adicional estruturado

    Args:
        logger: Logger instance
        level: Nível de log ("info", "warning", "error", "debug")
        message: Mensagem de log
        context: Dados adicionais para incluir no log
    """
    record = logging.LogRecord(
        name=logger.name,
        level=getattr(logging, level.upper()),
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.extra_data = context

    log_method = getattr(logger, level.lower(), logger.info)
    log_method(message)

# Logger global
logger = setup_logger(__name__)
