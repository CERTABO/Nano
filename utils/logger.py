import logging
import logging.handlers
import os
from types import SimpleNamespace

import appdirs

# TODO:Where should this be?
try:
    import cfg
except ImportError:
    cfg = SimpleNamespace()
    cfg.DEBUG = False
    cfg.DEBUG_LED = False
    cfg.DEBUG_READING = False
    cfg.APPLICATION = "UNKNOWN"
    cfg.VERSION = "10.04.2020"
    cfg.args = SimpleNamespace()
    cfg.args.usbport = None
    cfg.args.port_not_strict = True

CERTABO_DATA_PATH = appdirs.user_data_dir("GUI", "Certabo")


def set_logger():
    # We set the base logger to lowest denominator (DEBUG)
    log = logging.getLogger(cfg.APPLICATION)
    log.setLevel("DEBUG")

    detailed_format = "%(asctime)s: %(module)s: %(message)s"
    short_format = "%(message)s"

    # Set logstream
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(
        logging.Formatter(detailed_format if cfg.DEBUG else short_format)
    )
    stream_handler.setLevel(logging.DEBUG if cfg.DEBUG else logging.INFO)

    # Set logfile
    file_handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(CERTABO_DATA_PATH, f"certabo_{cfg.APPLICATION}.log"),
        backupCount=12,
    )
    file_handler.suffix = "%Y-%m-%d-%H"
    file_handler.setFormatter(logging.Formatter(detailed_format))
    file_handler.setLevel(logging.DEBUG)

    # Remove default stream_handler
    log.addHandler(stream_handler)
    log.addHandler(file_handler)

    log.debug("#" * 75)
    log.debug("#" * 75)
    log.info(f"{cfg.APPLICATION.capitalize()} Certabo application launched")
    log.info(f"Version: {cfg.VERSION}")
    log.debug(f"Arguments: {cfg.args}")


def get_logger():
    return logging.getLogger(cfg.APPLICATION)


def create_folder_if_needed(path):
    os.makedirs(path, exist_ok=True)


create_folder_if_needed(CERTABO_DATA_PATH)
