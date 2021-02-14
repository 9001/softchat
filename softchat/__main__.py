#!/usr/bin/env python3

about = {
    "name": "softchat",
    "version": "0.22",
    "date": "2021-02-14",
    "description": "convert twitch/youtube chat into softsubs",
    "author": "ed",
    "license": "MIT",
    "url": "https://github.com/9001/softchat",
}

import re
import os
import sys
import time
import json
import zlib
import random
import requests
import pprint
import hashlib
import shutil
import logging
import argparse
import tempfile
import colorsys
import subprocess as sp
from datetime import datetime
from PIL import ImageFont, ImageDraw, Image


try:
    from nototools import merge_fonts

    HAVE_NOTO_MERGE = True
except ImportError:
    HAVE_NOTO_MERGE = False


debug = logging.debug
info = logging.info
warn = logging.warning
error = logging.error


LINUX = sys.platform.startswith("linux")
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


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
        return f"\033[0;36m{ts}{ansi} {record.msg}\033[0m"


if __name__ == "__main__":
    if WINDOWS:
        os.system("")

    logging.basicConfig(
        level=logging.INFO,  # INFO DEBUG
        format="\033[36m%(asctime)s.%(msecs)03d\033[0m %(message)s",
        datefmt="%H%M%S",
    )
    lh = logging.StreamHandler(sys.stderr)
    lh.setFormatter(LoggerFmt())
    logging.root.handlers = [lh]


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
    HAVE_TOKENIZER = True
    info("found fugashi")
except:
    HAVE_TOKENIZER = False
    import traceback

    warn("could not load fugashi:\n" + traceback.format_exc() + "-" * 72 + "\n")

HAVE_FONTS = False
try:
    import fontforge

    magick = ["magick", "convert"]
    if shutil.which(magick[0]) is None:
        magick = ["convert"]

    if shutil.which(magick[0]) is not None:
        HAVE_FONTS = True
except:
    pass


class TextStuff(object):
    def __init__(self, sz, fontdir):
        self.sz = sz

        if fontdir:
            fontdir = fontdir.rstrip(os.sep)
            if fontdir.endswith("noto-hinted"):
                fontdir = fontdir.rsplit(os.sep, 1)[0]

        src = os.path.join("noto-hinted", "NotoSansCJKjp-Regular.otf")
        ok, self.otf_src = self.resolve_path(src, fontdir)
        if not ok:
            err = "could not locate fonts after trying these locations:"
            raise Exception("\n  ".join([err] + self.otf_src))

        dst = os.path.join("noto-hinted", "SquishedNotoSansCJKjp-Regular.otf")
        ok, self.otf_mod = self.resolve_path(dst, fontdir, self.otf_src)
        if ok:
            info(f"found font: {self.otf_mod}")
        else:
            self.conv_otf()

        # mpv=870 pil=960 mul=0.9 (due to fontsquish?)
        self.font = ImageFont.truetype(self.otf_mod, size=int(sz * 0.9 + 0.9))
        self.im = Image.new("RGB", (3840, 2160), "white")
        self.imd = ImageDraw.Draw(self.im)
        self.pipe_width = self.font.getsize("|")[0]
        self.font_ofs = self.font.getmetrics()[1]
        self.cache = {}
        self.vsize = self.caching_vsize

    def resolve_path(self, path, suggested, refpath=None):
        # wow really didn't think this through
        home = os.path.expanduser("~")
        basedirs = [
            os.path.dirname(os.path.realpath(__file__)),
            os.getcwd(),
            home,
            os.path.join(home, "fonts"),
            os.path.join(home, ".fonts"),
            os.path.join(home, "Downloads"),
            tempfile.gettempdir(),
        ]

        if suggested:
            basedirs = [suggested] + basedirs

        ret = [os.path.join(x, path) for x in basedirs]

        if refpath:
            # prefer same directory as the other file
            for x in ret:
                if x.rsplit(os.sep, 1)[0] == refpath.rsplit(os.sep, 1)[0]:
                    ret = [x] + [y for y in ret if y != x]
                    break

        for fp in ret:
            try:
                if os.path.exists(fp):
                    return True, fp
            except:
                pass

        return False, ret

    def conv_otf(self):
        from fontTools.ttLib import TTFont, newTable

        info("creating squished font, pls wait")
        mul = 1.1
        font = TTFont(self.otf_src)
        baseAsc = font["OS/2"].sTypoAscender
        baseDesc = font["OS/2"].sTypoDescender
        font["hhea"].ascent = round(baseAsc * mul)
        font["hhea"].descent = round(baseDesc * mul)
        font["OS/2"].usWinAscent = round(baseAsc * mul)
        font["OS/2"].usWinDescent = round(baseDesc * mul) * -1

        xfn = "softchat.xml"
        font.saveXML(xfn, tables=["name"])
        with open(xfn, "r", encoding="utf-8") as f:
            xml = f.read()

        xml = xml.replace("Noto Sans", "Squished Noto Sans")
        xml = xml.replace("NotoSans", "SquishedNotoSans")
        with open(xfn, "w", encoding="utf-8") as f:
            f.write(xml)

        font["name"] = newTable("name")
        font.importXML(xfn)
        os.unlink(xfn)

        try:
            del font["post"].mapping["Delta#1"]
        except:
            pass

        for fp in self.otf_mod:
            try:
                fdir = fp.rsplit(os.sep, 1)[0]
                os.makedirs(fdir, exist_ok=True)
                with open(fp, "wb") as f:
                    f.write(b"h")

                os.unlink(fp)
                break
            except:
                fp = None

        if not fp:
            err = "could not write modified font to any of the following locations:"
            raise Exception("\n  ".join([err] + self.otf_mod))

        self.otf_mod = fp
        info(f"writing {self.otf_mod}")
        font.save(self.otf_mod)

    def vsize_impl(self, text):
        w, h = self.imd.textsize("|" + text.replace("\n", "\n|"), self.font)
        return w - self.pipe_width, h

    def caching_vsize(self, text):
        if len(text) > 24:
            return self.vsize_impl(text)

        # faster than try/catch and get(text,None)
        if text in self.cache:
            return self.cache[text]

        ret = self.vsize_impl(text)
        self.cache[text] = ret
        return ret

    def unrag(self, text, width):
        """
        copied from  http://xxyxyz.org/line-breaking/
        license clarified per email:
          BSD or MIT since the EU doesn't recognize Public Domain

        only change so far is replacing len(w) with vsize(w+"_")[0]
        """
        words = text.split()
        count = len(words)
        offsets = [0]
        for w in words:
            offsets.append(offsets[-1] + self.vsize(w + "_")[0])

        minima = [0] + [10 ** 20] * count
        breaks = [0] * (count + 1)
        for i in range(count):
            j = i + 1
            while j <= count:
                w = offsets[j] - offsets[i] + j - i - 1
                if w > width:
                    break
                cost = minima[i] + (width - w) ** 2
                if cost < minima[j]:
                    minima[j] = cost
                    breaks[j] = i
                j += 1

        lines = []
        j = count
        while j > 0:
            i = breaks[j]
            lines.append(" ".join(words[i:j]))
            j = i
        lines.reverse()
        return lines


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


def assan(x):
    # there is no standardization on escaping ["{", "}", "\\"]:
    #   the commented one is for aegisub,
    #   the enabled one is for mpv

    # aegsiub:
    # return x.replace("{", "<").replace("}", ">").replace('\\', '\\{}')

    # mpv:
    ret = ""
    for c, nc in zip(x, x[1:] + "\n"):
        if c == "{":
            ret += "\\{"
        elif c == "}":
            ret += "\\}"
        elif c == "\\" and nc in ["N", "n", "h"]:
            ret += "\\\\"
        else:
            ret += c

    # mpv:
    #   there is no way to encode a literal \ before a markup {
    #   so the lines must end with a whitespace
    return ret + " "


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
                "warning",
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
                "warning",
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
                "warning",
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


def convert_old(m):
    o = {
        "action_type": "add_chat_item",
        "author": {"id": m["author_id"]},
        "message": m["message"],
        # This should be enough to uniquely identify them
        # As long as dumps from the new API are processed before legacy json files the proper IDs will be used.
        "message_id": f"{m['author_id']}{m['timestamp']}",
        "timestamp": m["timestamp"],
    }

    if m.get("author", None) is not None:
        o["author"]["name"] = m["author"]

    if m.get("amount", None) is not None:
        o["amount"] = m["amount"]
        o["body_background_colour"] = m["body_color"]["hex"]

    if m.get("time_text", None) is not None:
        o["time_text"] = m["time_text"]
        o["time_in_seconds"] = m["video_offset_time_msec"] / 1000.0

    if "badges" in m:
        o["author"]["badges"] = [{"title": b} for b in m["badges"].split(", ")]

    return o


def cache_emotes(emotes, emote_dir):
    for e in emotes.values():
        source_fname = os.path.join(emote_dir, e["id"].replace("/", "_"))
        fname = source_fname + ".svg"
        e["filename"] = fname
        if not os.path.exists(fname):
            info(f"Caching {e['name']}")
            url = None
            for img in e["images"]:
                # Might be better off asking for 1000x1000 instead of source,
                # may give slightly better results
                if img["id"] == "source":
                    url = img["url"]

            if url is None:
                error(f"Could not find source URL for {e['name']}")
                sys.exit(1)

            r = requests.get(url)
            # Save the originals in case youtube stops providing them for whatever reason.
            # These can also be used to manually replace the svgs if the automatically
            # generated one is of low quality.
            with open(source_fname, "wb") as f:
                f.write(r.content)

            cmd = magick[:]
            cmd.extend(
                [
                    source_fname,
                    "-fill",
                    "white",
                    "-flatten",
                    "-filter",
                    "Jinc",
                    "-resize",
                    "1000x",
                    "-colorspace",
                    "gray",
                    "-contrast-stretch",
                    # Determined experimentally to be a good middle-ground.
                    # Higher values catch more detail but values that are too
                    # high produce noisy, ugly output.
                    # There is no singly best option for all emotes.
                    "3%",
                    fname,
                ]
            )

            completed = sp.run(cmd)
            r.close()

            if completed.returncode != 0:
                error(f"Failed to convert {e['name']}")
                sys.exit(1)


def generate_font(emotes, font_fn, font_name):
    shortcuts = dict()
    # Start of one of the private use areas.
    # The other two don't work with embedded subtitle files for some reason.
    point = 0xE000
    font = fontforge.font()
    font.familyname = font_name

    for e in emotes.values():
        g = font.createChar(point)
        g.importOutlines(e["filename"])
        # Lie about their width as a hacky way to give them some breathing room.
        # Could do better, maybe will, but good enough for now.
        g.width = 1100

        for s in e["shortcuts"]:
            if s in shortcuts:
                warn("Found duplicate emote shortcut " + s)
            shortcuts[s] = chr(point)
        point += 1

    font.correctDirection()
    font.generate(font_fn)
    return shortcuts


class Okay(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    pass


def main():
    t0_main = time.time()

    random.seed(b"nope")

    vips = [
        "UCkIccKaHDGA8lYVmUerLhag",
        "UCI1KCp4Wa3dGfcmxgik1mCw",
    ]

    ap = argparse.ArgumentParser(
        formatter_class=Okay,
        description="convert modified chat_replay_downloader.py json into box-confined or danmaku-style softsubs",
        epilog="notes:\n  The first JSON_FILE should be the VOD download,\n  followed by any live-captures (to supplement\n  the messages which are lost in the VOD chat)",
    )

    # fmt: off
    ap.add_argument("-m", metavar="MODE", type=int, default=1, help="mode, 1=box, 2=danmaku")
    ap.add_argument("-r", metavar="WxH", type=str, default="1280x720", help="video res")
    ap.add_argument("-b", metavar="WxH+X+Y", type=str, default=None, help="subtitle area")
    ap.add_argument("-f", action="store_true", help="fill chat background")
    ap.add_argument("--sz", metavar="POINTS", type=int, default=0, help="font size")
    ap.add_argument("--spd", metavar="SPEED", type=int, default=256, help="[danmaku] pixels/sec")
    ap.add_argument("--spread", action="store_true", help="[danmaku] even distribution")
    ap.add_argument("--kana", action="store_true", help="convert kanji to kana")
    ap.add_argument("--fontdir", metavar="DIR", type=str, default=None, help="path to noto-hinted")
    ap.add_argument("--dupe_thr", metavar="SEC", type=float, default=10, help="Hide duplicate messages from the same author within this many seconds")
    ap.add_argument("--no_del", action="store_true", help="keep msgs deleted by mods")
    ap.add_argument("--start_time", metavar="STRT", type=int, default=None, help="Start time of the video in as a unix timestamp in seconds. Only used when there is no VOD chat download.")
    ap.add_argument("--offset", metavar="OFS", type=float, default=None, help="Offset in seconds to apply to the chat. Positive values delay the chat, negative values advance the chat, the same as subtitle delay in MPV. Use with incomplete video downloads or when estimating the start time.")
    ap.add_argument("--emote_font", action="store_true", help="Generate a custom emote font for emotes found in this stream. The subtitle file produced will require the specific embedded font generated by this run to be embedded in the media file.")
    ap.add_argument("--emote_cache", metavar="EMOTE_DIR", type=str, default=None, help="Directory to store emotes in. By default it is $pwd/emotes, but using the same directory for all invocations is safe. Will be created if it does not exist.")
    ap.add_argument("--embed_files", action="store_true", help="Will attempt to embed the subtitles and emote font, if generated, into the media file. This will make a copy of the media file.")
    ap.add_argument("--cleanup", action="store_true", help="If --embed_files is used, delete the produced subtitle and font files after embedding them. The original media file and chat downloads are never touched.")
    ap.add_argument("--media", metavar="MEDIA", type=str, default=None, help="The video file for the stream. Passing this is optional since it will be detected automatically if it shares a name with the chat replay file.")
    ap.add_argument("--emote_chat_file", metavar="EMOTE_DUMP", type=str, default=None, help="You probably don't need this. A chat file for another stream including emotes, for use with legacy chat files that do not include emotes when it's impossible to get a new chat replay download.")
    ap.add_argument("fn", metavar="JSON_FILE", nargs="+")
    ar = ap.parse_args()
    # fmt: on

    if ar.kana and not HAVE_TOKENIZER:
        error("you requested --kana but mecab failed to load")
        sys.exit(1)

    if ar.emote_font and not HAVE_FONTS:
        error("you requested --emote_font but lacked imagemagick or fontforge")
        sys.exit(1)

    emote_dir = "emotes"
    if ar.emote_cache:
        emote_dir = ar.emote_cache

    if ar.emote_font:
        if os.path.exists(emote_dir) and not os.path.isdir(emote_dir):
            error("Emote cache directory exists as a regular file.")
            sys.exit(1)
        if not os.path.exists(emote_dir):
            os.mkdir(emote_dir)

    if not ar.sz:
        ar.sz = 18 if ar.m == 1 else 24
        info(f"fontsize {ar.sz} pt")

    vw, vh = [int(x) for x in ar.r.split("x")]

    bw, bh, bx, by = [
        int(x) for x in re.split(r"[x,+]+", ar.b if ar.b else ar.r + "+0+0")
    ]

    z = TextStuff(ar.sz, ar.fontdir)
    fofs = z.font_ofs
    emotes = dict()

    jd = []
    deleted_messages = set()
    deleted_authors = set()
    seen = set()
    for fn in ar.fn:
        info(f"loading {fn}")
        with open(fn, "r", encoding="utf-8") as f:
            err = None
            try:
                jd2 = json.load(f)
            except Exception as ex:
                err = repr(ex)

            if not err and not jd2:
                err = "empty json file?"

            if not err:
                try:
                    if jd2.get("formats"):
                        err = "this is a youtube-dl info file, not a chatlog"
                except:
                    pass

            if not err:
                try:
                    _ = jd2[0]["timestamp"]
                except:
                    err = "does not look like a chatlog"

            if err:
                error(f"failed: {err}")
                sys.exit(1)

            if jd2[0].get("author_id", None):
                info(f"Converting legacy chat json {fn} to new format")
                jd2 = [convert_old(x) for x in jd2]

            for m in jd2:
                at = m.get("action_type", None)
                if at == "mark_chat_item_as_deleted":
                    deleted_messages.add(m["target_message_id"])
                elif at == "mark_chat_items_by_author_as_deleted":
                    deleted_authors.add(m["author"]["id"])

                if (
                    at != "add_chat_item"
                    or m.get("author", {}).get("id", None) is None
                    or (m.get("message", False) is False and "amount" not in m)
                ):
                    continue

                # For now, assume emote shortcuts are unique so we can postpone processing them
                if "emotes" in m:
                    for e in m["emotes"]:
                        if e["id"] not in emotes:
                            emotes[e["id"]] = e

                # Must use a composite ID here so that legacy json can be used with new json
                key = f"{m['timestamp']}\n{m['author']['id']}"
                if key not in seen:
                    seen.add(key)
                    jd.append(m)

    if ar.emote_chat_file is not None:
        info(f"loading emotes from {ar.emote_chat_file}")

        with open(ar.emote_chat_file, "r", encoding="utf-8") as f:
            err = None
            try:
                jd2 = json.load(f)
            except Exception as ex:
                err = repr(ex)

            if not err and not jd2:
                err = "empty json file?"

            if not err:
                try:
                    if jd2.get("formats"):
                        err = "this is a youtube-dl info file, not a chatlog"
                except:
                    pass

            if not err:
                try:
                    _ = jd2[0]["timestamp"]
                except:
                    err = "does not look like a chatlog"

            if err:
                error(f"failed: {err}")
                sys.exit(1)

            for m in jd2:
                # For now, assume emote shortcuts are unique so we can postpone processing them
                if "emotes" in m:
                    for e in m["emotes"]:
                        if e["id"] not in emotes:
                            emotes[e["id"]] = e

    if ar.emote_font and len(emotes) == 0:
        info("No emotes found")
        ar.emote_font = False

    font_name = "Squished Noto Sans CJK JP Regular"
    font_fn = ar.fn[0].rsplit(".", 1)[0] + ".ttf"
    emote_shortcuts = dict()

    if ar.emote_font:
        info(f"Generating custom font with {len(emotes)} emotes")
        cache_emotes(emotes, emote_dir)

        # Try to avoid collisions if someone does install these as system fonts.
        font_name = f"SoftChat Custom Emotes {hashlib.sha256(font_name.encode('utf-8')).hexdigest()}"
        emote_shortcuts = generate_font(emotes, font_fn, font_name)

    use_018 = "; please use softchat v0.18 or older if your chat json was created with a chat_replay_downloader from before 2021-01-29-something"
    if not jd:
        raise Exception("no messages were loaded" + use_018)

    # jd.sort(key=operator.attrgetter("timestamp"))
    jd.sort(key=lambda x: x["timestamp"])
    unix_ofs = None
    for x in jd:
        unix = x["timestamp"] / 1_000_000.0
        t = x.get("time_in_seconds", 0)
        if t >= 10:
            video = t
            unix_ofs = unix - video
            break

    if unix_ofs is None and ar.start_time is not None:
        unix_ofs = ar.start_time

    if unix_ofs is None and ar.offset is None:
        raise Exception(
            "could not find time_in_seconds in json, set a start time or offset "
            "manually with --start_time/--offset or use v0.17 or earlier"
        )

    if unix_ofs is None:
        unix_ofs = jd[0]["timestamp"] / 1_000_000.0

    debug(f"unixtime offset = {unix_ofs:.3f}")
    debug("adding video offset to all messages")
    # Store messages with no video offset in a temporary list
    # The messages may have been sent while the stream was offline
    tjd = list()
    njd = list()
    n_interp = 0
    for x in jd:
        unix = x["timestamp"] / 1_000_000.0
        t = x.get("time_in_seconds", None)
        if t is None:
            n_interp += 1
            sec = unix - unix_ofs
            x["time_in_seconds"] = sec
            x["time_text"] = tt(sec)
            tjd.append(x)
        elif t >= 10 and "amount" not in x:
            njd.append(x)
            video = t
            new_ofs = unix - video
            diff = abs(new_ofs - unix_ofs)
            if diff >= 10:
                print(repr(x))
                m = f"unix/video offset was {unix_ofs:.3f}, new {new_ofs:.3f} at {unix:.3f} and {video:.3f}, diff {new_ofs - unix_ofs:.3f}"
                if diff >= 60:
                    # Assume stream was offline when the gap is greater than a minute
                    tjd.clear()

                    m += ", dropping messages while stream was assumed to be offline"
                    warn(m)
                else:
                    warn(m + ", probably fine")

            unix_ofs = new_ofs
            if tjd:
                njd.extend(tjd)
                tjd.clear()
        else:
            njd.append(x)

        if ar.offset is not None:
            x["time_in_seconds"] += ar.offset
            x["time_text"] = tt(x["time_in_seconds"])

    if tjd:
        njd.extend(tjd)
        tjd.clear()

    jd = njd

    jd.sort(key=lambda x: [x["time_in_seconds"], x["author"]["id"]])
    info("{} msgs total, {} amended".format(len(jd), n_interp))

    # Process deletions from while the stream was live
    # TODO -- consider processing undeletions as well (messages present in VOD after being "deleted" while live)
    ljd = len(jd)

    if not ar.no_del:
        jd = [m for m in jd if m["message_id"] not in deleted_messages]
        jd = [m for m in jd if m["author"]["id"] not in deleted_authors]

    if len(jd) != ljd:
        info(f"Dropped {ljd - len(jd)} deleted messages.")

    # Find all dupe msgs from [author-id, message-text]
    dupes = {}
    for m in jd:
        try:
            mtxt = m.get("message", "--") or "--"
            key = f"{m['author']['id']}\n{mtxt}"
        except:
            raise Exception(pprint.pformat(m))

        try:
            dupes[key].append(m)
        except:
            dupes[key] = [m]

    # filter messages so that no remaining dupes are closer together than dupe_thr seconds
    droplist = set()
    for k, v in dupes.items():
        m = v[0]
        for m2 in v[1:]:
            if m2["timestamp"] - m["timestamp"] < 1_000_000 * ar.dupe_thr:
                droplist.add(m2["message_id"])
            else:
                # Keep chains of dupes from extending indefinitely
                m = m2

    if len(droplist) > 0:
        info(f"Dropping {len(droplist)} duplicate chat entries within threshold")
    jd = [m for m in jd if m["message_id"] not in droplist]

    media_fn = None
    if ar.media and os.path.isfile(ar.media):
        media_fn = ar.media
    else:
        for ext in ["webm", "mp4", "mkv"]:
            f = ar.fn[0]
            while not media_fn and "." in f:
                f = f.rsplit(".", 1)[0]
                mfn = f + "." + ext
                if os.path.isfile(mfn):
                    media_fn = mfn
                    break

    cdur_msg = None
    cdur_err = "could not verify chat duration"
    v_dur = None
    if not media_fn:
        cdur_err += ": could not find media file"
    else:
        info("calculating media duration")
        try:
            ofs = 0
            while True:
                ofs -= 1
                chat_dur = jd[ofs]["time_in_seconds"]
                if chat_dur < 4096 * 4096:
                    break

            v_dur = get_ff_dur(media_fn)
            delta = abs(chat_dur - v_dur)
            perc = delta * 100.0 / max(v_dur, chat_dur)
            if delta > 60:
                cdur_err = f"media duration ({v_dur:.0f}sec) and chat duration ({chat_dur:.0f}sec) differ by {delta:.0f}sec ({perc:.2f}%)"
            else:
                cdur_err = None
                cdur_msg = f"chat duration appears correct; {v_dur:.0f}sec - {chat_dur:.0f}sec = {delta:.0f}sec ({perc:.2f}%)"
        except Exception as ex:
            media_fn = None
            cdur_err += ": " + repr(ex)

    if cdur_err:
        warn(cdur_err)
    else:
        info(cdur_msg)

    ptn_kanji = re.compile(r"[\u4E00-\u9FAF]")
    ptn_kana = re.compile(r"[\u3040-\u30FF]")
    ptn_ascii = re.compile(r"[a-zA-Z]")
    ptn_pre = re.compile(r"([　、。〇〉》」』】〕〗〙〛〜〞〟・…⋯！＂）＊－．／＞？＠＼］＿～｡｣･￭￮]+)")
    ptn_post = re.compile(r"([〈《「『【〔〖〘〚〝（＜［｀｢]+)")

    info(f"deduping nicknames in {len(jd)} chat entries")
    pair_seen = set()
    nick_dupes = set()
    nick_list = {}
    for msg in jd:
        # break  # opt

        uid = msg["author"]["id"]
        try:
            nick = msg["author"]["name"]
        except:
            # warn(repr(msg))
            # raise
            msg["author"]["name"] = nick = uid

        # in case names change mid-stream
        pair = f"{nick}\n{uid}"
        if pair in pair_seen:
            continue

        pair_seen.add(pair)

        try:
            uids = nick_list[nick]
            if uid not in uids:
                uids.append(uid)
                nick_dupes.add(nick)
        except:
            nick_list[nick] = [uid]

    info(f"tagged {len(nick_dupes)} dupes:")
    for k, v in sorted(nick_list.items(), key=lambda x: [-len(x[1]), x[0]])[:20]:
        info(f"  {len(v)}x {k}")

    msgs = []
    info("converting")
    for n_msg, msg in enumerate(jd):
        txt = msg.get("message", "") or ""
        if "amount" not in msg and txt == "":
            txt = "--"

        t_fsec = msg["time_in_seconds"]
        t_isec = int(t_fsec)
        t_hms = msg["time_text"]

        if t_hms.startswith("-") or t_isec < 0 or t_isec > 4096 * 4096:
            continue

        # time integrity check
        try:
            h, m, s = [int(x) for x in t_hms.split(":")]
            t_isec2 = 60 * (60 * h + m) + s
        except:
            m, s = [int(x) for x in t_hms.split(":")]
            t_isec2 = 60 * m + s

        if int(t_fsec) != t_isec or t_isec != t_isec2:
            # at some point, someone observed a difference between time_text
            # and time_in_seconds, so please let me have a look at
            # your chatlog json if you end up here
            raise Exception(
                f"time drift [{t_fsec}] [{t_isec}] [{t_isec2}] [{t_hms}]\n  (pls provide this chat-rip to ed)"
            )

        if ":" in txt:
            for k, v in emote_shortcuts.items():
                txt = txt.replace(k, v)

        n_ascii = len(ptn_ascii.findall(txt))
        n_kanji = len(ptn_kanji.findall(txt))
        n_kana = len(ptn_kana.findall(txt))

        # if the amount of ascii compared to kanji/kana
        # is less than 30%, assume we'll need MeCab
        is_jp = (n_kanji + n_kana) / (n_kanji + n_kana + n_ascii + 0.1) > 0.7

        # transcription from kanji to kana if requested
        if ar.kana and is_jp and n_kanji:
            txt2 = yomi.parse(txt)
            txt = ""
            for ch in txt2:
                co = ord(ch)
                # hiragana >= 0x3041 and <= 0x3096
                # katakana >= 0x30a1 and <= 0x30f6
                if co >= 0x30A1 and co <= 0x30F6:
                    txt += chr(co - (0x30A1 - 0x3041))
                else:
                    txt += ch

        if ar.m == 1:
            wrap_width = bw
        else:
            # vsfilter wraps it anyways orz
            wrap_width = vw / 2

        if n_msg % 100 == 0 and len(z.cache) > 1024 * 64:
            z.cache = {}

        # wrap to specified width
        # by splitting on ascii whitespace
        vtxt = z.unrag(txt, wrap_width)
        vsz = z.vsize("\n".join(vtxt))

        if vsz[0] >= bw and is_jp:
            # too wide, is japanese,
            # try wrapping on japanese punctuation instead
            vtxt = ptn_pre.sub("\\1\n", txt)
            vtxt = ptn_post.sub("\n\\1", vtxt)
            vtxt = vtxt.split("\n")
            vsz = z.vsize("\n".join(vtxt))

            if vsz[0] >= bw and HAVE_TOKENIZER:
                # still too wide, wrap on word-boundaries
                vtxt = z.unrag(wakati.parse(txt), bw)
                vtxt = [x.replace(" ", "") for x in vtxt]

                for n in range(1, len(vtxt)):
                    # move most punctuation to the prev line
                    ln = vtxt[n]
                    m = ptn_pre.search(ln)
                    if m and m.start() == 0:
                        vtxt[n - 1] += ln[: m.end()]
                        vtxt[n] = ln[m.end() :]

                vsz = z.vsize("\n".join(vtxt))

        vtxt = [x for x in vtxt if x.strip()]

        # pillow height calculation is off by a bit; this is roughly it i think
        sx, sy = vsz
        sy = int(sy + fofs * 2.5 + 0.8)

        if n_msg % 100 == 0:
            info(
                "  {} / {}   {}%   {}   {}\n   {}\n".format(
                    n_msg,
                    len(jd),
                    int((n_msg * 100) / len(jd)),
                    t_hms,
                    [sx, sy],
                    "\n   ".join(vtxt),
                )
            )

        nick = msg["author"]["name"]
        if nick in nick_dupes:
            nick += f"  ({msg['author']['id']})"

        o = {
            "nick": nick,
            "uid": msg["author"]["id"],
            "t0": t_fsec,
            "sx": sx,
            "sy": sy,
            "txt": vtxt,
        }

        if "amount" in msg:
            o["shrimp"] = msg["amount"]
            color = None
            for k in [
                "body_background_colour",
                "background_colour",
                "money_chip_background_colour",
            ]:
                if k in msg:
                    color = msg[k]
                    break
            o["color"] = color[1:][:-2] or "444444"  # "#1de9b6ff"

        if "badges" in msg["author"]:
            o["badges"] = [b["title"] for b in msg["author"]["badges"]]

        msgs.append(o)

        # if n_msg > 5000:  # opt
        #    break

    if ar.f:
        opts = {"back": "80", "shad": "ff", "opaq": "3"}
    else:
        opts = {"back": "00", "shad": "80", "opaq": "1"}

    vis = []
    if ar.fn[0].lower().endswith(".json"):
        out_fn = ar.fn[0][:-5] + ".ass"
    else:
        out_fn = ar.fn[0] + ".ass"

    info(f"creating {out_fn}")
    with open(out_fn, "wb") as f:
        f.write(
            """\
[Script Info]
Title: https://ocv.me/dev/?softchat.py
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: {vw}
PlayResY: {vh}

[Aegisub Project Garbage]
Last Style Storage: Default
Video File: ?dummy:30.000000:40000:{vw}:{vh}:47:163:254:
Video AR Value: 1.777778
Video Zoom Percent: 1.000000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: a,{font},{sz},&H00FFFFFF,&H000000FF,&H{back}000000,&H{shad}000000,0,0,0,0,100,100,0,0,{opaq},2,1,1,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(
                vw=vw, vh=vh, sz=ar.sz, font=font_name, **opts
            ).encode(
                "utf-8"
            )
        )

        # Dialogue: 0,0:00:00.00,0:00:05.00,a,,0,0,0,,hello world

        n_msg = 0
        msg = None
        supers = []
        colormap = {}
        for next_msg in msgs + [None]:
            if not msg or (next_msg and next_msg["t0"] <= 0):
                msg = next_msg
                continue

            n_msg += 1
            if n_msg % 1000 == 1:
                info(f"writing {hms(msg['t0'])}, #{n_msg} / {len(msgs)}")

            nick = msg["nick"]
            c = colormap.get(nick, None)
            if not c:
                if ar.m == 1:
                    bri = 0.5
                    sat = 1
                else:
                    bri = 0.4
                    sat = 0.8

                c = zlib.crc32(nick.encode("utf-8")) & 0xFFFFFFFF
                r, g, b = [
                    int(x * 255)
                    for x in colorsys.hsv_to_rgb((c % 256) / 256.0, sat, bri)
                ]
                c = f"{r:02x}{g:02x}{b:02x}"
                colormap[nick] = c

            shrimp = None
            if "shrimp" in msg:
                c2 = msg["color"]
                c2 = f"{c2[4:6]}{c2[2:4]}{c2[0:2]}"  # thx ass
                shrimp = rf"{{\bord4\shad4\3c&H{c2}&\c&H000000&}}{msg['shrimp']}"

            nick = assan(nick)
            msg["txt"] = [assan(x) for x in msg["txt"]]

            if ar.m == 1:
                # text = colored nick followed by the actual lines, ass-escaped
                txt = [rf"{{\3c&H{c}&}}{nick}"]

                badges = msg.get("badges", [])
                if not set(badges).isdisjoint(["Moderator", "Owner", "Verified"]):
                    txt[-1] += r" {\bord16\shad6}*"
                elif msg["uid"] in vips:
                    txt[-1] += r" {\bord16\shad4}----"

                if shrimp:
                    txt.append(shrimp)

                txt.extend(msg["txt"])

                # show new messages bottom-left (heh)
                msg["txt"] = txt
                msg["px"] = bx
                msg["py"] = by + bh

                ta = hms(msg["t0"])
                tb = hms(next_msg["t0"] if next_msg else msg["t0"] + 10)

                rm = 0
                for m in vis:
                    # i'll be honest, no idea why the *1.2 is necessary
                    m["py"] -= msg["sy"] * 1.2
                    if m["py"] - m["sy"] < by:
                        # debug('drop {} at {}'.format(hms(m["t0"]), ta))
                        rm += 1

                vis = vis[rm:] + [msg]

                if True:
                    # rely on squished font for linespacing reduction
                    txt = r"{{\pos({},{})}}".format(bx, by + bh)
                    for m in vis:
                        pad = ""
                        for ln in m["txt"]:
                            txt += pad + ln + r"\N{\r}"
                            pad = r"\h\h"

                    f.write(
                        "Dialogue: 0,{},{},a,,0,0,0,,{}\n".format(ta, tb, txt).encode(
                            "utf-8"
                        )
                    )
                else:
                    # old approach, one ass entry for each line
                    for m in vis:
                        step = m["sy"] / len(m["txt"])
                        x = m["px"]
                        y = m["py"]
                        for ln in m["txt"]:
                            txt = r"{{\pos({},{})}}{}".format(x, y, ln)
                            x = m["px"] + 8
                            y += step
                            f.write(
                                "Dialogue: 0,{},{},a,,0,0,0,,{}\n".format(
                                    ta, tb, txt
                                ).encode("utf-8")
                            )
            else:
                txts, t0, w, h = [msg[x] for x in ["txt", "t0", "sx", "sy"]]
                txt = "\\N".join(txts)

                # ass linespacing is huge, compensate (wild guess btw)
                h += int(ar.sz * 0.25 * (len(txts) - 1) + 0.99)

                # plus some horizontal margin between the messages
                w += 8

                shrimp_mul = 1
                if shrimp:
                    txt = f"{shrimp} {txt}"
                    shrimp_mul = 2
                    w += h * 4  # donation is not included, TODO maybe

                if "badges" in msg and "Moderator" in msg["badges"]:
                    txt = rf"{{\bord24\shad6}}*{{\bord6}}{txt}"
                elif msg["uid"] in vips:
                    txt = rf"{{\bord16\shad4}}_{{\bord4}}{txt}"

                len_boost = 0.7
                td = (vw + w - w * len_boost) * shrimp_mul / ar.spd
                t1 = t0 + td

                # collision detection polls at certain points from the left,
                # so figure out timestamps when the right-side hits those
                abs_spd = (vw + w * 1.0) / td
                p9 = t0 + (w + vw * 0.1) / abs_spd  # 10% right
                p8 = t0 + (w + vw * 0.2) / abs_spd
                p5 = t0 + (w + vw * 0.5) / abs_spd
                p3 = t0 + (w + vw * 0.7) / abs_spd
                p1 = t0 + (w + vw * 0.9) / abs_spd  # 10% left

                # and when the left-side hits those,
                # to compare against other pN's and find a free slot
                a9 = t0 + (vw * 0.1) / abs_spd
                a8 = t0 + (vw * 0.2) / abs_spd
                a5 = t0 + (vw * 0.5) / abs_spd
                a3 = t0 + (vw * 0.7) / abs_spd
                a1 = t0 + (vw * 0.9) / abs_spd

                rm = []
                taken_best = []  # 10..90%
                taken_good = []  # 30..90%
                taken_okay = []  # 60..80%
                for m in vis:
                    m_py, m_sy, m_p9, m_p8, m_p5, m_p3, m_p1, m_txt = [
                        m[x] for x in ["py", "sy", "p9", "p8", "p5", "p3", "p1", "txt"]
                    ]

                    if t0 > m_p5:
                        rm.append(m)
                        continue

                    entry = [m_py, m_py + m_sy, id(m)]

                    if a8 < m_p8 or a5 < m_p5:
                        # add txt to avoid sorted() trying to compare m's
                        taken_okay.append(entry)

                    if a9 < m_p9 or a3 < m_p3:
                        taken_good.append(entry)

                    if a9 < m_p9 or a1 < m_p1:
                        taken_best.append(entry)

                for m in rm:
                    vis.remove(m)

                ymax = vh - h
                overlap_mul = 0.9
                frees_merged = []  # crit + prefer
                for lst in [taken_best, taken_good, taken_okay]:
                    frees = [[ymax, 0, ymax]]  # size, y0, y1
                    for y1, y2, _ in sorted(lst):
                        rm = []
                        add = []
                        for free in frees:
                            _, fy1, fy2 = free

                            if fy1 >= y2 or y1 >= fy2:
                                # does not intersect
                                continue

                            elif fy1 <= y1 and fy2 >= y2:
                                # sub slices range in half, split it
                                rm.append(free)

                                nfsz = y1 - fy1
                                if nfsz > h * overlap_mul:
                                    # h/3 to ensure less than 10% overlap
                                    add.append([nfsz, fy1, y1])

                                nfsz = fy2 - y2
                                if nfsz > h * overlap_mul:
                                    add.append([nfsz, y2, fy2])

                            elif y2 >= fy1:
                                # sub slices top of free
                                rm.append(free)

                                nfsz = fy2 - y2
                                if nfsz > h * overlap_mul:
                                    add.append([nfsz, y2, fy2])

                            elif y1 <= fy2:
                                # slices bottom
                                rm.append(free)

                                nfsz = y1 - fy1
                                if nfsz > h * overlap_mul:
                                    add.append([nfsz, fy1, y1])

                            else:
                                raise Exception("fug")

                        for x in rm:
                            frees.remove(x)

                        frees.extend(add)

                    frees_merged.append(frees)
                    overlap_mul = 0.8  # allow 20% overlap in critical

                # use the first non-zero list of free slots
                # (ordered by least amount of horizontal collision)
                frees = next((x for x in frees_merged if x), None)

                if not frees:
                    # can't be helped, pick a random y to collide in
                    y = int(random.randrange(ymax))
                elif ar.spread:
                    avail, y0, y1 = sorted(frees)[-1]
                    if avail <= h:
                        y = int(y0 + avail / 2)
                    else:
                        # just centering looks boring, let's rand
                        y = y0 + random.randrange(avail - h)
                else:
                    y = None
                    best = 5318008
                    target = vh / 2
                    # print(json.dumps([target, frees], indent=4, sort_keys=True))
                    for avail, y0, y1 in frees:
                        if y0 <= target and y1 >= target + h:
                            y = target
                            break
                        elif y0 >= target:
                            this = y0 - target
                            if best > this:
                                best = this
                                y = y0
                        elif y1 <= target + h:
                            this = target - (y1 - h)
                            if best > this:
                                best = this
                                y = y1 - h

                y = int(y)
                txt = rf"{{\move({vw},{y+h},{-w},{y+h})\3c&H{c}&}}{txt}{{\fscx40\fscy40\bord1}}\N{nick}"

                msg["t1"] = t1
                msg["p9"] = p9
                msg["p8"] = p8
                msg["p5"] = p5
                msg["p3"] = p3
                msg["p1"] = p1
                msg["px"] = vw
                msg["py"] = y
                msg["sy"] = h
                msg["txt"] = txt
                vis.append(msg)

                ln = "Dialogue: 0,{},{},a,,0,0,0,,{}\n".format(
                    hms(t0), hms(msg["t1"]), msg["txt"]
                ).encode("utf-8")

                if shrimp:
                    supers.append(ln)
                else:
                    f.write(ln)

            msg = next_msg

        for ln in supers:
            f.write(ln)

    if cdur_err:
        warn(cdur_err)
    else:
        info(cdur_msg)

    if ar.embed_files and not media_fn:
        error("you requested --embed_files but the media file could not be located")
    elif ar.embed_files:
        split = media_fn.rsplit(".", 1)
        merged_fn = media_fn.rsplit(".", 1)[0] + ".softchat-merged.mkv"
        info(f"Producing merged file {merged_fn}.")

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-i",
            media_fn,
            "-i",
            out_fn,
            "-map",
            "0:v",
            "-map",
            "0:a",
            "-map",
            "1",
            "-t",
            # Subtitles will still run longer than the video due to in-progress
            # animations past the end of the video, but only about 10 seconds
            # unless there's a poorly timed superchat.
            str(v_dur),
            "-codec",
            "copy",
            "-disposition:s:0",
            "default",
        ]

        if ar.emote_font:
            cmd.extend(
                [
                    "-attach",
                    font_fn,
                    "-metadata:s:t",
                    "mimetype=application/x-truetype-font",
                ]
            )

        cmd.extend([merged_fn, "-y"])

        completed = sp.run(cmd, capture_output=True)
        if completed.returncode == 0:
            info(
                "Merged media file finished. "
                "You should check the new file before removing the old file."
            )
            if ar.cleanup:
                os.remove(out_fn)
                if ar.emote_font:
                    os.remove(font_fn)
        if completed.returncode != 0:
            error(f"Failed to embed files into {merged_fn}")
            error(completed.stderr.decode("utf-8"))
            sys.exit(1)

    # from pprint import pprint; pprint(msgs[-5:])
    t1_main = time.time()
    info(f"finished in {t1_main-t0_main:.2f} sec")


if __name__ == "__main__":
    main()


r"""

===[ side-by-side with kanji transcription ]===========================

chat_replay_downloader.py https://www.youtube.com/watch?v=7LXgVlrfsWw -output ars-37-minecraft-3.json

softchat.py ..\yt\ars-37-minecraft-3.json -b 340x500+32+32 && copy /y ..\yt\ars-37-minecraft-3.ass ..\yt\ars-37-minecraft-3.1.ass

softchat.py ..\yt\ars-37-minecraft-3.json -b 340x500+360+32 --kana && copy /y ..\yt\ars-37-minecraft-3.ass ..\yt\ars-37-minecraft-3.2.ass

(head -n 21 ars-37-minecraft-3.1.ass ; (tail -n +22 ars-37-minecraft-3.1.ass; tail -n +22 ars-37-minecraft-3.2.ass) | sort) > ars-37-minecraft-3.ass

c:\users\ed\bin\mpv.com "..\yt\ars-37-minecraft-3.json.mkv" -ss 1:15:20


===[ re-parse a downloaded youtube json ]==============================

chat_replay_downloader.py https://www.youtube.com/watch?v=0Qygvs0rG50 -output ame-minecraft-railway-research.json
chat_replay_downloader.py ame-minecraft-railway-research.json.json -output ame-minecraft-railway-research-2.json


===[ danmaku / nnd-style ]=============================================

# assumes your mpv config is interpolation=no, blend-subtitles=no
..\dev\softchat.py -m 2 "ame-minecraft-railway-research-2.json" && C:\Users\ed\bin\mpv.com ame-minecraft-railway-research-2.json.mkv --vo=direct3d --vf=fps=90 --sub-delay=-2

# sanic
--vo=direct3d --sub-delay=-2 --vf=fps=75 --speed=1.2

# alternate display mode, usually worse
C:\Users\ed\bin\mpv.com ame-minecraft-railway-research-2.json.mkv --interpolation=yes --blend-subtitles=yes --video-sync=display-resample --tscale=mitchell --hwdec=off --vo=direct3d

# use --sub-files=some.ass to specify a sub with another name


===[ p5 and p8 overlay for mpv ]=======================================

mpv.com "[MINECRAFT] WHERE AM I #GAWRGURA-lMFrn59TN_c.mkv" -ss 12:15 --vf "lavfi=[drawtext=fontfile='C\:\\Users\\ed\\dev\\noto-hinted\\SquishedNotoSansCJKjp-Regular.otf':x=16:y=16:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=4:fontsize=28:text='%{pts\:hms}, %{pts}', drawtext=fontfile='C\:\\Users\\ed\\dev\\noto-hinted\\SquishedNotoSansCJKjp-Regular.otf':x=956:y=600:fontcolor=white:box=1:boxcolor=black:fontsize=48:text='|', drawtext=fontfile='C\:\\Users\\ed\\dev\\noto-hinted\\SquishedNotoSansCJKjp-Regular.otf':x=1532:y=600:fontcolor=white:box=1:boxcolor=black:fontsize=48:text='|']"

"""
