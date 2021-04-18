#!/usr/bin/env python

"""ytdl-tui.py: interactive youtube-dl frontend"""
__version__ = "1.0"
__author__ = "ed <irc.rizon.net>"
__url__ = "https://ocv.me/dev/?ytdl-tui.py"
__credits__ = ["stackoverflow.com"]
__license__ = "MIT"
__copyright__ = 2020


""" HOW TO USE THIS ON WINDOWS:
download python3 from https://www.python.org/
("Downloads" and click the button under "Download for Windows")
-- when installing, make sure to enable the "Add Python to PATH" checkbox!
then download this file (ytdl-tui.py) and doubleclick it, that should be all
"""


import os
import sys
import time
import json
import shutil
import hashlib
import zipfile
import platform
import tempfile
import threading
import urllib.request
import subprocess as sp


# nice globals
URL_SELF = "https://ocv.me/dev/ytdl-tui.py"
# zeranoe blocks direct-linking so you get stolen builds instead
URL_FFMPEG = "https://ocv.me/rehost/ffmpeg-4.2.3-win32-static-lgpl.zip"
TMPDIR = os.path.join(tempfile.gettempdir(), "ytdl-tui-ocv")
PYDIR = os.path.join(TMPDIR, "py")
WINDOWS = platform.system() == "Windows"


# updater state vars
TUI_PATH = os.path.abspath(os.path.realpath(__file__))
with open(TUI_PATH, "rb") as f:
    TUI_HASH = hashlib.md5(f.read()).hexdigest()

TUI_PATH_DESC = os.path.join(TMPDIR, "tui.path")
UPGRADING = TUI_PATH.startswith(TMPDIR)
if UPGRADING:
    try:
        with open(TUI_PATH_DESC, "rb") as f:
            TUI_PATH = f.read().decode("utf-8") or TUI_PATH
    except:
        pass


def eprint(*args, **kwargs):
    kwargs["file"] = sys.stderr
    print(*args, **kwargs)


def update_writeback():
    self_path = os.path.abspath(os.path.realpath(__file__))
    if self_path == TUI_PATH:
        return

    try:
        if not os.path.exists(TUI_PATH):
            return
    except:
        return

    with open(self_path, "rb") as f:
        py = f.read()

    for n in range(25):
        time.sleep(0.2)
        try:
            os.remove(TUI_PATH)
        except:
            if os.path.exists(TUI_PATH):
                continue

        with open(TUI_PATH, "wb") as f:
            f.write(py)

        os.remove(TUI_PATH_DESC)
        break


def ytdl_updatechk():
    env = os.environ.copy()
    env["PYTHONPATH"] = PYDIR
    pkgs = sp.check_output([sys.executable, "-m", "pip", "freeze"], env=env)
    pkgs = pkgs.strip().decode("utf-8").split("\n")

    got = None
    pkg = "youtube-dl"
    for v in pkgs:
        if not v.startswith(pkg + "=="):
            continue

        got = v.split("=")[-1]
        break

    if not got:
        download_ytdl()
        return

    r = urllib.request.urlopen("https://pypi.org/pypi/{}/json".format(pkg))
    txt = r.read()
    obj = json.loads(txt)
    latest = obj["info"]["version"]
    if got == latest:
        eprint("aight, no updates, all good")
        return

    eprint("have {}, upgrading to {}...".format(got, latest))
    download_ytdl()


def download_ytdl():
    sp.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-t",
            PYDIR,
            "-U",
            "youtube-dl",
        ]
    )


def tui_updatechk():
    r = urllib.request.urlopen(URL_SELF)
    py = r.read()
    with open(TUI_PATH, "rb") as f:
        if f.read() == py:
            eprint("aight, no updates, all good")
            return False

    fp = os.path.join(TMPDIR, "upd-{}.py".format(int(time.time())))
    with open(fp, "wb") as f:
        f.write(py)

    if not py.rstrip().endswith(b"\n# ytdl-tui eof"):
        msg = "update check failed; server returned garbage ({} bytes), see {}".format(
            len(py), fp
        )
        eprint(msg)
        sys.exit(1)
        return True

    with open(TUI_PATH_DESC, "wb") as f:
        f.write(TUI_PATH.encode("utf-8"))

    eprint("update found! switching to new version...")
    if WINDOWS:
        sp.Popen(["start", sys.executable, fp], shell=True)
    else:
        os.execl(sys.executable, sys.executable, fp)

    sys.exit(0)


def find_ffmpeg():
    hits = {}
    suf = ".exe" if WINDOWS else ""
    for n in ["ffmpeg", "ffprobe"]:
        for base in ["", TMPDIR + "/"]:
            try:
                attempt = base + "ffmpeg" + suf
                sp.check_call([attempt, "-version"], stdout=sp.DEVNULL)
                hits[n] = attempt
                break
            except:
                continue
    return hits


def assert_ffmpeg():
    hits = find_ffmpeg()
    if len(hits.keys()) == 2:
        return hits

    if not WINDOWS:
        eprint("sorry, need FFmpeg")
        sys.exit(1)

    zp = os.path.join(TMPDIR, "ffmpeg.zip")
    if not os.path.exists(zp):
        eprint("downloading FFmpeg...")
        r = urllib.request.urlopen(URL_FFMPEG)
        with open(zp, "wb") as f:
            while True:
                buf = r.read(4096)
                if not buf:
                    break

                f.write(buf)

    eprint("unpacking FFmpeg...")
    with zipfile.ZipFile(zp, "r") as zf:
        files = zf.namelist()
        found = {}
        for fp in files:
            fn = fp.split("/")[-1]
            if fn not in ["ffmpeg.exe", "ffprobe.exe"]:
                continue

            found[fn] = 1
            tmp = zf.extract(fp, TMPDIR)
            os.rename(tmp, os.path.join(TMPDIR, fn))
            # the zipfile api is horrible

    hits = find_ffmpeg()
    if len(hits.keys()) == 2:
        return hits

    eprint("failed to unpack FFmpeg (bad zip or bad code (who am i kidding))")
    sys.exit(1)


def act(cmd, url):
    try:
        ffloc = None
        ff = find_ffmpeg()
        if ff["ffmpeg"].startswith(TMPDIR):
            ffloc = TMPDIR
    except:
        pass

    opts = {
        "ffmpeg_location": ffloc,
        "prefer_ffmpeg": True,
        "writesubtitles": True,
        "allsubtitles": True,
        "writedescription": True,
        "writeinfojson": True,
    }

    if "twitter.com" in url:
        opts["outtmpl"] = "tw-%(id)s-%(uploader_id)s - %(uploader)s.%(ext)s"

    try:
        import youtube_dl
    except Exception as ex:
        # eprint(repr(ex))
        download_ytdl()
        try:
            import youtube_dl
        except Exception as ex:
            eprint("\n\n  failed to load youtube-dl :(\n  pls screenshot this\n")
            eprint(repr(ex))
            eprint(sys.path)
            eprint(TMPDIR)
            files = os.listdir(sys.path[0])
            eprint(files)
            eprint("the end")
            sys.exit(1)

    ok = False
    if cmd and cmd.startswith("a"):
        try:
            opts["format"] = {
                "a": "bestaudio",
                "ao": "bestaudio[ext=webm]",
                "a4": "bestaudio[ext=m4a]",
                "a3": "bestaudio[ext=mp3]",
            }[cmd]
            ok = True
        except:
            raise Exception("\n\n  that's an invalid audio format fam\n")

    if ok or not cmd:
        if cmd in ["a", "ao"]:
            opts["progress_hooks"] = [oggify_cb]

        with youtube_dl.YoutubeDL(opts) as ydl:
            ydl.download(list(x for x in url.split(" ") if x))

        return

    if cmd == "f":
        opt2 = opts.copy()
        opt2["listformats"] = True
        with youtube_dl.YoutubeDL(opt2) as ydl:
            ydl.download(url)
            # md = ydl.extract_info(url, download=False)
            # fmts = md.get('formats', [md])
        eprint("\nenter list of formats to download, separate with space:")
        eprint("fmts> ", end="")

        opts["format"] = input().replace(" ", "+")
        with youtube_dl.YoutubeDL(opts) as ydl:
            ydl.download(url)

        return

    raise Exception("\n\n  no comprende\n")


def oggify_cb(d):
    # eprint(d)
    if d["status"] != "finished":
        return

    ff = find_ffmpeg()

    fn1 = d["filename"]
    if not fn1.endswith(".webm"):
        eprint("tui: filename should have been webm but isnt??")
        return

    fn2 = fn1.rsplit(".", 1)[0] + ".ogg"

    # fmt: off
    cmd = [
        ff["ffmpeg"],
        "-hide_banner",
        "-nostdin",
        "-i", fn1,
        "-map", "0:a:0",
        "-c", "copy",
        "-f", "ogg",
        fn2
    ]
    # fmt: on
    try:
        sp.check_call(cmd)
        os.unlink(fn1)
        eprint("ogged")
    except:
        eprint("\n\n  tui: conversion to ogg failed!  use the webm\n")


def main():
    if sys.version_info[0] == 2:
        eprint("\n\npy2 kinshi, download python3\n")
        sys.exit(1)

    # expensive but dont wanna take any chances, updater probably hella buggy
    if not UPGRADING:
        owner = None
        try:
            with open(os.path.join(TMPDIR, "owner"), "rb") as f:
                owner = f.read().decode("utf-8")
        except:
            pass

        if owner != TUI_HASH:
            try:
                shutil.rmtree(TMPDIR)
                eprint("cleaned up old tempfiles")
            except:
                pass

    threading.Thread(target=update_writeback, daemon=True).start()
    os.makedirs(PYDIR, exist_ok=True)
    sys.path.insert(0, PYDIR)
    assert_ffmpeg()
    with open(os.path.join(TMPDIR, "owner"), "wb") as f:
        f.write(TUI_HASH.encode("utf-8"))

    argv = sys.argv[1:]
    while True:
        eprint(
            """
ready!
list of commands and what they do:
  <link>      download media at <link>
  a <link>    download audio-only from <link>
  ao <link>   download opus audio from <link>
                (also: a4=mp4, a3=mp3)
  f <link>    show format selector for <link>
  u           update-check youtube-dl
  uu          update-check this script
"""
        )
        if WINDOWS:
            m = "rightclick to paste a link, one or more actually (separate with space), then press enter to download\n"
            eprint(m)

        eprint("YTDL> ", end="")
        if argv:
            ln = " ".join(argv)
            argv = None
        else:
            ln = input().strip()

        if ln == "uu":
            if tui_updatechk():
                return
            continue

        if ln == "u":
            ytdl_updatechk()
            continue

        kv = ln.split(" ", 1)
        if len(kv) == 1 or len(kv[0]) > 4:
            act(None, ln)
        else:
            act(*kv)

        eprint("\npress enter to exit")
        input()
        return


if __name__ == "__main__":
    try:
        main()
    except (SystemExit, KeyboardInterrupt):
        pass
    except:
        import traceback

        traceback.print_exc()
        eprint("\npress enter to exit")
        input()

# ytdl-tui eof
