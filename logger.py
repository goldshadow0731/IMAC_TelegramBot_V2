# -*- coding: utf8 -*-
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import sys
import time


def get_logger(name):
    module_name = os.path.splitext(os.path.basename(name))[0]
    log_path = f"{os.path.dirname(os.path.abspath(name))}/log/{module_name}"
    os.makedirs(log_path, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(module)s:%(lineno)d %(funcName)s - %(message)s"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    
    file_handler = TimedRotatingFileHandler(
        filename=f"{log_path}/{module_name}.log",
        when="midnight",
        backupCount=7
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    logging.basicConfig(level=logging.NOTSET, handlers=[console_handler, file_handler])

    return logging.getLogger(module_name)


if __name__ == "__main__":
    logger = get_logger(__file__)
    while True:
        for i in range(10, 60, 10):
            logger.log(i, "Test")
            time.sleep(5)