#!/usr/bin/env python3

"""ytdl-tui.py: interactive youtube-dl frontend"""
__version__ = "1.9"
__author__ = "ed <irc.rizon.net>"
__url__ = "https://github.com/9001/softchat/"
__credits__ = ["stackoverflow.com"]
__license__ = "MIT"
__copyright__ = 2020


""" HOW TO USE THIS ON WINDOWS:
download python3 from https://www.python.org/
("Downloads" and click the button under "Download for Windows")
-- when installing, make sure to enable the "Add Python to PATH" checkbox!
then download this file (ytdl-tui.py) and doubleclick it, that should be all

-----------------------------------------------------------------------

How to use this on android / termux:
  copy-paste this block of text to create a shortcut:

apt update && apt -y full-upgrade &&
termux-setup-storage;
apt -y install curl python ffmpeg &&
cd && mkdir -p .shortcuts &&
curl -LO https://github.com/9001/softchat/raw/hovedstraum/contrib/ytdl-tui.py &&
echo 'cd /storage/emulated/0/Movies/ && python3 ~/ytdl-tui.py' >.shortcuts/ytdl-tui

# stop selecting here :p

-----------------------------------------------------------------------

optional dependencies (download/convert chatlogs to subtitles):
* python3 -m pip install --user chat-downloader softchat

optional steps to avoid captchas, and to download members-only videos:
* install https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/
* write cookies.txt into the folder you're running ytdl-tui in

-----------------------------------------------------------------------

new in this version:
* fix chat download when title does not contains "."

-----------------------------------------------------------------------

HOWTO: download member's only content
* first install the cookies.txt addon: https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/
* save the cookies as "cookies.txt" inside the folder where you download your videos
(as a bonus, this might also get around some download restrictions)

-----------------------------------------------------------------------

HOWTO: download all members-only videos from a channel and nothing else
* take the channel URL, for example https://www.youtube.com/channel/UCyl1z3jo3XHR1riLFKG5UAg
* replace UC with UUMO, for example https://www.youtube.com/channel/UUMLyl1z3jo3XHR1riLFKG5UAg
* give that URL to this script after doing the cookies.txt stuff above

-----------------------------------------------------------------------

how to ensure max audio quality (updated 2020-09-02, not-impl here):
-f 'bestvideo+(251/141)/22/bestvideo+(258/256/140/250/249/139)'
https://gist.github.com/AgentOak/34d47c65b1d28829bb17c24c04a0096f
https://github.com/ytdl-org/youtube-dl/blob/e450f6cb634f17fd4ef59291eafb68b05c141e43/youtube_dl/extractor/youtube.py#L447
https://github.com/ytdl-org/youtube-dl/blob/6c22cee673f59407a63b2916d8f0623a95a8ea20/youtube_dl/extractor/common.py#L1380

-----------------------------------------------------------------------
"""


import re
import os
import sys
import time
import json
import shlex
import shutil
import hashlib
import zipfile
import platform
import tempfile
import threading
import urllib.request
import subprocess as sp


def eprint(*args, **kwargs):
    kwargs["file"] = sys.stderr
    print(*args, **kwargs)


# fmt: off
# youtube-dl fork to use (last assignment wins), format: [ pip, import ]
# also see https://github.com/animelover1984/youtube-dl
YTDL_FORK = [ "youtube-dlc", "youtube_dlc" ]  # https://github.com/blackjack4494/yt-dlc
YTDL_FORK = [ "youtube-dl",  "youtube_dl"  ]  # https://github.com/ytdl-org/youtube-dl  (the OG)
YTDL_FORK = [ "yt-dlp",      "yt_dlp"      ]  # https://github.com/yt-dlp/yt-dlp  (best?)

# latest version
URL_SELF = "https://raw.githubusercontent.com/9001/softchat/hovedstraum/contrib/ytdl-tui.py"

# grab latest win64-gpl-[0-9].zip
URL_FFMPEG = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases"

# fmt: on
# apparently no api that returns both the final filename and the URL orz
created_files = []

# misc
COOKIES = "cookies.txt"
TMPDIR = os.path.join(tempfile.gettempdir(), "ytdl-tui-ocv")
TMPDIR = os.path.abspath(os.path.realpath(TMPDIR))  # thx macos
PYDIR = os.path.join(TMPDIR, "py")
WINDOWS = platform.system() == "Windows"
YTDL_PIP, YTDL_IMP = YTDL_FORK

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
        eprint(f"[*] could not read [{TUI_PATH_DESC}]")
        pass

# print('\n'.join([TMPDIR, PYDIR, TUI_PATH]))


def need_ie(url, ex):
    if not WINDOWS or "CERTIFICATE_VERIFY_FAILED" not in repr(ex):
        return False

    try:
        proto, dom = url.split("://", 1)
        proto += "://"
    except:
        proto = "https://"
        dom = url

    dom = dom.split("/")[0]
    msg = "\n\033[1;31m\nerror:\n  could not locate certificate for domain [{}],\n  please open Internet Explorer (not chrome/firefox/other) and\n  access the following URL so Windows loads up the certificate:\n    {}/\n\033[0m"
    eprint(msg.format(dom, proto + dom))

    eprint("\npress enter to exit")
    input()
    sys.exit(1)


def find_dep(fn):
    r = os.path.join(os.path.dirname(os.path.realpath(__file__)), fn)
    if os.path.exists(r):
        return r

    if os.path.exists(fn):
        return fn

    return None


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

        os.chmod(TUI_PATH, 0o755)
        os.remove(TUI_PATH_DESC)
        break


def ytdl_updatechk():
    env = os.environ.copy()
    env["PYTHONPATH"] = PYDIR
    pkgs = sp.check_output([sys.executable, "-m", "pip", "freeze"], env=env)
    pkgs = pkgs.strip().decode("utf-8").split("\n")

    got = None
    pkg = YTDL_PIP
    for v in pkgs:
        if not v.startswith(pkg + "=="):
            continue

        got = v.split("=")[-1]
        break

    if not got:
        download_ytdl()
        return

    r = urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json")
    txt = r.read()
    obj = json.loads(txt)
    latest = obj["info"]["version"]
    if got == latest:
        eprint("aight, no updates, all good")
        return

    eprint(f"have {got}, upgrading to {latest}...")
    download_ytdl()


def download_ytdl():
    # fmt: off
    sp.check_call([
        sys.executable, "-m", "pip",
        "install", "-U",
        "--disable-pip-version-check",
        "-t", PYDIR, YTDL_PIP,
    ])
    # fmt: on


def tui_updatechk():
    r = urllib.request.urlopen(URL_SELF)
    py = r.read()
    with open(TUI_PATH, "rb") as f:
        if f.read() == py:
            eprint("aight, no updates, all good")
            return False

    fp = os.path.join(TMPDIR, f"upd-{time.time():.0f}.py")
    with open(fp, "wb") as f:
        f.write(py)

    if not py.rstrip().endswith(b"\n# ytdl-tui eof"):
        eprint(
            f"update check failed; server returned garbage ({len(py)} bytes), see {fp}"
        )
        sys.exit(1)
        return True

    with open(TUI_PATH_DESC, "wb") as f:
        f.write(TUI_PATH.encode("utf-8"))

    os.chmod(fp, 0o755)

    eprint("update found! switching to new version...")
    if WINDOWS:
        cmd = ["start", sys.executable, fp]
        eprint("[*] cmd: " + repr(cmd))
        sp.Popen(cmd, shell=True)
    else:
        cmd = [sys.executable, fp]
        eprint("[*] cmd: " + repr(cmd))
        os.execl(sys.executable, *cmd)

    sys.exit(0)


def find_ffmpeg():
    hits = {}
    for n in ["ffmpeg", "ffprobe"]:
        for base in [TMPDIR + "/", None]:
            hit = shutil.which(n, path=base)
            if not hit or "ImageMagick" in hit:
                continue

            hits[n] = hit
            break

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
        eprint("downloading FFmpeg release-list...")
        try:
            r = urllib.request.urlopen(URL_FFMPEG)
        except Exception as ex:
            if not need_ie(URL_FFMPEG, ex):
                raise

        zip_url = None
        ptn = re.compile(r".*-win64-gpl-[0-9\.]+\.zip$")
        jt = r.read().decode("utf-8", "replace")
        jo = json.loads(jt)
        for rls in jo:
            for asset in rls["assets"]:
                url = asset["browser_download_url"]
                if ptn.match(url):
                    zip_url = url
                    break

            if zip_url:
                break

        eprint("downloading " + zip_url)
        try:
            r = urllib.request.urlopen(zip_url)
            sz = int(r.getheader("Content-Length"))
        except Exception as ex:
            if not need_ie(zip_url, ex):
                raise

        got = 0
        ctr = 0
        eprint()
        with open(zp, "wb") as f:
            while True:
                buf = r.read(4096)
                got += len(buf)
                ctr += 1
                if ctr % 32 == 0 or not buf:
                    perc = got * 100.0 / sz
                    eprint(
                        f"\033[A {got/1024/1024:.2f} of {sz/1024/1024:.2f} MiB, {perc:5.2f}%"
                    )

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


def check_call(*args, **kwargs):
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([TMPDIR, env["PATH"]])
    kwargs["env"] = env
    sp.check_call(*args, **kwargs)


def fix_cookies():
    # chat-downloader needs expiration on cookies
    try:
        with open(COOKIES, "r") as f:
            cookies = f.read()
    except:
        eprint("\033[1;31mcould not read cookiejar\033[0m")
        return

    # eprint("\n\ncookies-pre:\n" + cookies + "\n\n")

    fixed = []
    ptn = re.compile("^" + (r"([^\t]+)\t" * 6) + "(.*)")
    for ln in cookies.split("\n"):
        m = ptn.match(ln)
        if not m or ln.startswith("#"):
            fixed.append(ln)
            continue

        vals = list(m.groups())
        if not int(vals[4]):
            vals[4] = int(time.time()) + 60 * 60 * 24 * 7

        fixed.append("\t".join([str(x) for x in vals]))

    cookies = "\n".join(fixed)
    with open(COOKIES, "w") as f:
        f.write(cookies)

    # eprint("\n\ncookies-post:\n" + cookies + "\n\n")


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
        # "writeautomaticsub": True,
        "allsubtitles": True,
        "writedescription": True,
        "writeinfojson": True,
        "cookiefile": COOKIES,
        "throttledratelimit": 128 * 1024,
        "ignoreerrors": True,
    }

    if "twitter.com" in url:
        opts["outtmpl"] = "tw-%(id)s-%(uploader_id)s - %(uploader)s.%(ext)s"

    # import pudb; pu.db

    try:
        youtube_dl = __import__(YTDL_IMP)
    except Exception as ex:
        eprint(f"will download {YTDL_PIP} because:\n  {ex!r}\n")
        download_ytdl()
        try:
            youtube_dl = __import__(YTDL_IMP)
        except Exception as ex:
            eprint(f"\n\n   failed to load {YTDL_PIP} :(\n   pls screenshot this\n")
            eprint(repr(ex))
            eprint(sys.executable)
            eprint(sys.path)
            eprint(TMPDIR)
            files = os.listdir(sys.path[0])
            eprint(files)
            eprint()
            raise

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

    if ok or cmd in [None, "f"]:
        hooks = []
        if cmd in ["a", "ao"]:
            hooks.append(oggify_cb)

        hooks.append(final_cb)
        opts["progress_hooks"] = hooks

        links = list(x for x in url.split(" ") if x)
        eprint(f"\ndownloading {len(links)} links...")

        cwd = os.path.abspath(os.getcwd())
        for url in links:
            if not url.strip():
                continue

            os.chdir(cwd)
            try:
                if cmd == "f":
                    opt2 = opts.copy()
                    opt2["listformats"] = True
                    with youtube_dl.YoutubeDL(opt2) as ydl:
                        inf = ydl.extract_info(url)

                    eprint("\nenter list of formats to download, separate with space:")
                    eprint("fmts> ", end="")

                    opts["format"] = input().replace(" ", "+")

                opts.pop("download_archive", None)
                dn = url.split("/channel/")
                if len(dn) == 1:
                    dn = url.split("playlist?list=")

                if len(dn) == 2:
                    dn = dn[1]
                    for ch in ["/", "?", "&"]:
                        dn = dn.split(ch)[0]

                    if not os.path.isdir(dn):
                        os.mkdir(dn)

                    os.chdir(dn)

                    fp = f"../{COOKIES}"
                    if os.path.exists(fp):
                        shutil.copy2(fp, COOKIES)

                    lfn = "downloaded.ids"
                    opts["download_archive"] = lfn

                    m = f"\ndownloading entire channel with progress tracking to {dn}/{lfn}\n"
                    eprint(m)

                with youtube_dl.YoutubeDL(opts) as ydl:
                    inf = ydl.extract_info(url, download=True)
                    vids = inf.get("entries", [inf])
                    # eprint(json.dumps(vids, sort_keys=True, indent=4))

            except Exception as ex:
                if not need_ie(url, ex):
                    raise

            fix_cookies()
            grab_chats(vids)

        fix_cookies()
        return

    raise Exception("\n\n  no comprende\n")


def final_cb(d):
    if d["status"] == "finished":
        created_files.append(d["filename"])


def get_fname(fns, id):
    fn = [x for x in fns if f"-{id}." in x or f" [{id}]." in x]
    if not fn:
        return f"untitled-{id}.mkv"

    fn = fn[0]
    while id in fn.rsplit(".", 1)[0]:
        fn = fn.rsplit(".", 1)[0]
        if "." not in fn:
            break

    vfiles = []
    for fx in fns:
        if fn not in fx:
            continue

        sz = os.path.getsize(fx)
        vfiles.append([sz, fx])

    return list(sorted(vfiles))[-1][1]


def grab_chats(vids):
    fns = os.listdir(".")
    items = []
    for vid in vids:
        if not vid:
            continue  # privated, deleted

        if vid["extractor"] not in ["youtube", "twitch"]:
            continue

        v_id = vid["id"]
        fn = get_fname(fns, v_id)
        items.append([vid["webpage_url"], v_id, fn])

    ##
    ## chats for channel-archive

    ids = []
    try:
        with open("downloaded.ids", "rb") as f:
            ids = f.read().decode("utf-8").split("\n")
            ids = [x.split(" ")[1].strip() for x in ids if x.startswith("youtube ")]
    except:
        pass

    for id in ids:
        fn = get_fname(fns, id)
        if os.path.exists(fn + ".json"):
            continue

        items.append([f"https://www.youtube.com/watch?v={id}", id, fn])

    ## end channel-archive
    ##

    i2 = []
    for x in items:
        if x not in i2:
            i2.append(x)

    items = i2
    if not items:
        return

    try:
        import chat_downloader
    except:
        eprint("could not find chat downloader, will not grab chats")
        return

    for url, v_id, fn in items:
        while v_id in fn.rsplit(".", 1)[0]:
            fn = fn.rsplit(".", 1)[0]
            if "." not in fn:
                break

        # fmt: off
        fn += ".json"
        cmd = [
            sys.executable, "-m", "chat_downloader",
            "--chat_type", "live",
            "--message_groups", "all",
            "--sort_keys",
            "--indent", "2",
            "-o", fn,
        ]
        # fmt: on

        if os.path.exists(COOKIES):
            cmd.extend(["-c", COOKIES])

        cmd.append(url)

        if WINDOWS:
            scmd = " ".join(f'"{x}"' for x in cmd)
        else:
            scmd = " ".join(shlex.quote(x) for x in cmd)

        eprint(f"\nchat-dl: {scmd}")
        if os.path.exists(fn):
            eprint("chat json already exists, will not download")
            return

        try:
            check_call(cmd)
            if not os.path.exists(fn):
                # may exit 0 even if it failed
                raise Exception()

            eprint("chat download okke")
            chatconv(fn)
        except:
            eprint(f"chat download fug: {scmd}")


def chatconv(fn):
    try:
        import softchat
    except:
        eprint("could not find chat converter, will not create softsubs")
        return

    # fmt: off
    cmd = [
        sys.executable, "-m", "softchat",
        "-m2",
        "--no_del",
        "--emote_font",
        "--emote_cache", "emotes",
        "--emote_sz", "1.6",
        "--emote_install",
        "--no_errdep_emotes",
        fn,
    ]
    # fmt: on

    if WINDOWS:
        scmd = " ".join(f'"{x}"' for x in cmd)
    else:
        scmd = " ".join(shlex.quote(x) for x in cmd)

    eprint(f"\nchat-conv: {scmd}")

    try:
        check_call(cmd)
        eprint("chat convert okke")
    except:
        eprint(f"chat convert fug: {scmd}")


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
    os.system("")
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
            f"""
ready!
list of commands and what they do:
  <link>      download media at <link>
  a <link>    download audio-only from <link>
  ao <link>   download opus audio from <link>
                (also: a4=mp4, a3=mp3)
  f <link>    show format selector for <link>
  u           update-check {YTDL_PIP}
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

        traceback.print_exc()  # =stderr
        eprint("\npress enter to exit")
        input()


# ytdl-tui eof
