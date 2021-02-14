#!/usr/bin/env python3

import os
import sys
import shlex
import logging
from datetime import datetime


LINUX = sys.platform.startswith("linux")
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


logger = logging.getLogger(__name__)
debug = logger.debug
info = logger.info
warn = logger.warning
error = logger.error


class LoggerFmt(logging.Formatter):
    def format(self, record):
        if record.levelno == logging.DEBUG:
            ansi = "\033[01;30m"
        elif record.levelno == logging.INFO:
            ansi = "\033[0;32m"
        elif record.levelno == logging.WARN:
            ansi = "\033[0;33m"
        else:
            ansi = "\033[01;31m"

        ts = datetime.utcfromtimestamp(record.created)
        ts = ts.strftime("%H:%M:%S.%f")[:-3]

        msg = record.msg
        if record.args:
            msg = msg % record.args

        return f"\033[0;36m{ts}{ansi} {msg}\033[0m"


def init_logger(debug):
    if WINDOWS:
        os.system("")

    lv = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=lv,
        format="\033[36m%(asctime)s.%(msecs)03d\033[0m %(message)s",
        datefmt="%H%M%S",
    )
    lh = logging.StreamHandler(sys.stderr)
    lh.setFormatter(LoggerFmt())
    logging.root.handlers = []
    logger.handlers = [lh]
    logger.setLevel(lv)


def shell_esc(cmd):
    if WINDOWS:
        return " ".join(f'"{x}"' for x in cmd)
    else:
        return " ".join(shlex.quote(x) for x in cmd)
