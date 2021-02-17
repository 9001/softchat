#!/usr/bin/env python3

import os
import sys
import shlex
import logging
from datetime import datetime
from contextlib import contextmanager


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


@contextmanager
def zopen(fn, mode="r", *args, **kwargs):
    import codecs

    objs = None
    if fn.endswith(".gz"):
        import gzip

        objs = [gzip.open(fn, "rb")]

    elif fn.endswith(".bz2"):
        import bz2

        objs = [bz2.open(fn, "rb")]

    elif fn.endswith(".xz"):
        import lzma

        objs = [lzma.open(fn, "rb")]

    elif fn.endswith(".zst"):
        from zstandard import ZstdDecompressor

        try:
            # documentation says KiB but it seems to be bytes
            ctx = ZstdDecompressor(max_window_size=1024 * 1024 * 1024 * 2)
        except:
            # fallback in case that changes
            ctx = ZstdDecompressor(max_window_size=1024 * 1024 * 2)

        f1 = open(fn, "rb", 512 * 1024)
        f2 = ctx.stream_reader(f1)
        objs = [f2, f1]

    else:
        objs = [open(fn, "rb", 512 * 1024)]

    if "b" not in mode:
        enc = kwargs.get("encoding", "utf-8")
        # yield io.TextIOWrapper(io.BufferedReader(f2))
        yield codecs.getreader(enc)(objs[0])
    else:
        yield objs[0]

    for obj in objs:
        obj.close()

    # plain: 0.098 sec; 101,492,906 byte
    #  zstd: 0.122 sec;   4,283,071 byte; zstd -19
    #  zstd: 0.139 sec;   3,821,123 byte; zstd -19 --long=31
    #  gzip: 0.315 sec;  10,836,637 byte; pigz -9
    #    xz: 0.549 sec;   3,676,204 byte; pixz -9tk
    # bzip2: 1.774 sec;   8,229,872 byte; bzip2 -9


def test_zopen(fn):
    import time
    import hashlib

    t0 = time.time()
    hasher = hashlib.sha1()
    with zopen(fn) as f:
        while True:
            buf = f.read(64 * 1024)
            if not buf:
                break
            hasher.update(buf.encode("utf-8"))
    print(f"{hasher.hexdigest()} {time.time() - t0}")
