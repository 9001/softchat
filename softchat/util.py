#!/usr/bin/env python3

import os
import sys
import shlex
import logging
import subprocess as sp
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


def find_fontforge():
    """fontforge comes with a full python env on windows (nice), try to find it"""
    search_dirs = []
    for k in ["ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"]:
        v = os.environ.get(k)
        if v and v not in search_dirs:
            search_dirs.append(v)

    for sdir in search_dirs:
        ffpy = os.path.join(sdir, "FontForgeBuilds/bin/ffpython.exe")
        if os.path.exists(ffpy):
            return ffpy

    # actually they do on macos as well
    ffpy = "/Applications/FontForge.app/Contents/MacOS/FFPython"
    if os.path.exists(ffpy):
        return ffpy

    return None


HAVE_FONTFORGE = True
try:
    import fontforge
except:
    HAVE_FONTFORGE = find_fontforge()


def load_fugashi(write_cfg=False):
    try:
        # help python find libmecab.dll, adjust this to fit your env if necessary
        dll_path = None
        for base in sys.path:
            x = os.path.join(base, "fugashi")
            if os.path.exists(os.path.join(x, "cli.py")) and not dll_path:
                dll_path = x
            x2 = os.path.join(x, "../../../lib/site-packages/fugashi")
            if os.path.exists(x2):
                dll_path = x2
                break

        if not dll_path:
            raise Exception("could not find fugashi installation path")

        if WINDOWS:
            os.add_dll_directory(dll_path)

        from fugashi import Tagger

        dicrc = os.path.join(dll_path, "dicrc")
        if write_cfg:
            with open(dicrc, "wb") as f:
                f.write(
                    "\n".join(
                        [
                            r"node-format-yomi = %f[9] ",
                            r"unk-format-yomi = %m",
                            r"eos-format-yomi  = \n",
                            "",
                        ]
                    ).encode("utf-8")
                )

        wakati = Tagger("-Owakati")
        yomi = Tagger("-Oyomi -r " + dicrc.replace("\\", "\\\\"))

        # import MeCab
        # wakati = MeCab.Tagger('-Owakati')
        info("found fugashi")
        return wakati, yomi
    except:
        import traceback

        warn("could not load fugashi:\n" + traceback.format_exc() + "-" * 72 + "\n")


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


def hms(s):
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return "{:d}:{:02d}:{:05.2f}".format(int(h), int(m), s)


def tt(s):
    s = int(s)

    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h > 0:
        return "{:d}:{:02d}:{:02d}".format(h, m, s)
    return "{:d}:{:02d}".format(m, s)


def get_ff_dur(fn):
    # ffprobe -hide_banner -v error -select_streams v:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 foo.mkv
    #   webm: n/a
    #   mkv: n/a
    #   mp4: numSec
    # ffprobe -hide_banner -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 foo.mkv
    #   webm: numSec
    #   mkv: numSec
    #   mp4: numSec (0.06 sec larger)

    # Try to grab the duration for the video stream, if available, otherwise fall back to format duration (webm)

    if fn.lower().endswith("mkv"):
        ret = sp.check_output(
            [
                "ffprobe",
                "-hide_banner",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream_tags=duration",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                fn,
            ]
        )
        r = ret.decode("utf-8").strip().split("\n")

        if len(r) == 2 and ":" in r[0]:
            h, m, s = [float(x) for x in r[0].split(":")]
            return 60 * (60 * h + m) + s
        else:
            return float(r[-1])
    elif fn.lower().endswith("mp4"):
        ret = sp.check_output(
            [
                "ffprobe",
                "-hide_banner",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                fn,
            ]
        )
        return float(ret.split(b"\n", 1)[0])
    elif fn.lower().endswith("webm"):
        ret = sp.check_output(
            [
                "ffprobe",
                "-hide_banner",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                fn,
            ]
        )
        return float(ret)
    else:
        raise Exception(f"Unknown video format {fn}")
