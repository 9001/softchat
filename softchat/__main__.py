#!/usr/bin/env python3

about = {
    "name": "softchat",
    "version": "0.12",
    "date": "2020-11-16",
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
import logging
import argparse
import colorsys
import subprocess as sp
from datetime import datetime
from PIL import ImageFont, ImageDraw, Image

"""
==[ NOTES / README ]===================================================

 - superchats will display for 2x the time and with inverted colors

 - moderator messages are emphasized
     (larger outline, and prefixed with a ball)

 - mode 1, sidebar chat, creates a huge amount of subtitle events
     which many media players (including mpv) will struggle with

     for example, seeking will take like 5sec

     you can fix this by muxing the subtitle into the vid:
     ffmpeg -i the.webm -i the.ass -c copy muxed.mkv

 - mode 2, danmaku, will look blurry and/or jerky in most players
     unless you have the subtitles render at your native screen res

     for example in mpv you could add these arguments:
     --vo=direct3d --sub-delay=-2 --vf=fps=90

     replace 90 with your monitor's fps

 - after an upgrade, you can reconvert old rips like this:
     for f in *.json.ass; do ./softchat.py -m2 -- "${f%.*}"; done

==[ DEPENDENCIES ]=====================================================
each version below is the latest as of writing,
tested on cpython 3.8.1

 - chat rips made using chat_replay_downloader.py;
   latest-tested may at times have softchat-specific modifications
   but upstream is likely more maintained:
     latest-tested: https://ocv.me/dev/?chat_replay_downloader.py
     upstream: https://github.com/xenova/chat-replay-downloader/blob/master/chat_replay_downloader.py

 - all the noto fonts in a subfolder called noto-hinted
     see https://www.google.com/get/noto/
     or just https://noto-website-2.storage.googleapis.com/pkgs/Noto-hinted.zip
     (remove "un" from "unhinted" in the download link)

 - REQUIRED:
   python -m pip install --user pillow

 - REQUIRED:
   python -m pip install --user fontTools

 - OPTIONAL (not yet implemented here):
   python -m pip install --user git+https://github.com/googlefonts/nototools.git@v0.2.13#egg=nototools

 - OPTIONAL (recommended):
   python -m pip install --user "fugashi[unidic]"
   python -m unidic download

 - OPTIONAL (this also works with some modifications):
   python -m pip install --user mecab-python3
   # bring your own dictionaries

==[ HOW-TO / EXAMPLE ]=================================================

 1 download the youtube video, for example with youtube-dl or
   https://ocv.me/dev/?ytdl-tui.py

   it will eventually say "Merging formats into some.mkv",
   use that filename below except replace extension as necessary
 
 2 download the chatlog:
   chat_replay_downloader.py https://youtu.be/fgsfds -message_type all -o "some.json"

 3 convert the chatlog into subtitles (-m2=danmaku)
   softchat.py -m2 "some.json"

 4 play the video (with --vf=fps=FRAMERATE due to danmaku)
   mpv some.mkv --sub-files "some.json.ass" --sub-delay=-2 --vf=fps=60

==[ NEW ]==============================================================

 - avoid some collisions in -m2, especially without --spread
 - added note on reconverting rips after upgrading
 - translation mapping for emotes

==[ TODO ]=============================================================

 - build optimal font using noto-merge-fonts
 - per-line background shading (optional)
 - more stuff probably

==[ RELATED ]==========================================================

 - https://ocv.me/dev/?gist/chat-heatmap.py

"""


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
    # help python find libmecab.dll, adjust this to fit your env,
    # TODO make this fix less bad (linux/macos, python versions, sys/user)
    home = os.path.expanduser("~")
    dll_path = os.path.join(home, r"AppData\Roaming\Python\lib\site-packages\fugashi")

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
    info("found mecab")
except:
    HAVE_TOKENIZER = False
    import traceback

    warn("could not load mecab:\n" + traceback.format_exc() + "-" * 72 + "\n")


class TextStuff(object):
    def __init__(self, sz):
        self.sz = sz
        self.otf_src = self.resolve_path("noto-hinted/NotoSansCJKjp-Regular.otf")
        self.otf_mod = self.resolve_path(
            "noto-hinted/SquishedNotoSansCJKjp-Regular.otf"
        )
        if not os.path.exists(self.otf_mod):
            self.conv_otf()

        # mpv=870 pil=960 mul=0.9 (due to fontsquish?)
        self.font = ImageFont.truetype(self.otf_mod, size=int(sz * 0.9 + 0.9))
        self.im = Image.new("RGB", (3840, 2160), "white")
        self.imd = ImageDraw.Draw(self.im)
        self.pipe_width = self.font.getsize("|")[0]
        self.font_ofs = self.font.getmetrics()[1]
        self.cache = {}
        self.vsize = self.caching_vsize

    def resolve_path(self, path):
        return os.path.join(os.path.dirname(os.path.realpath(__file__)), path)

    def conv_otf(self):
        # import fontline.commands as flc
        #
        # flc.modify_linegap_percent(self.otf_src, "30")
        # x = flc.get_linegap_percent_filepath(self.otf_src, "30")
        # os.rename(x, self.otf_mod)

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


def main():
    t0_main = time.time()

    random.seed(b"nope")

    emotes = {
        ":_hic1:": "🅷",
        ":_hic2:": "🅸",
        ":_hic3:": "🅲",
        ":_tea1:": "🅣",
        ":_tea2:": "🅔",
        ":_tea3:": "🅐",
        ":_nou:": "🅄",
        ":_yyy:": "🅈",
    }

    ap = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="convert modified chat_replay_downloader.py json into box-confined or danmaku-style softsubs",
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
    ap.add_argument("fn", metavar="JSON_FILE")
    ar = ap.parse_args()
    # fmt: on

    if ar.kana and not HAVE_TOKENIZER:
        error("you requested --kana but mecab failed to load")
        sys.exit(1)

    if not ar.sz:
        ar.sz = 18 if ar.m == 1 else 24
        info(f"fontsize {ar.sz} pt")

    vw, vh = [int(x) for x in ar.r.split("x")]

    bw, bh, bx, by = [
        int(x) for x in re.split(r"[x,+]+", ar.b if ar.b else ar.r + "+0+0")
    ]

    z = TextStuff(ar.sz)
    fofs = z.font_ofs

    info(f"loading {ar.fn}")
    with open(ar.fn, "r", encoding="utf-8") as f:
        jd = json.load(f)

    media_fn = None
    for ext in ["webm", "mp4", "mkv"]:
        f = ar.fn.rsplit(".", 2)[0] + "." + ext
        if os.path.exists(f):
            media_fn = f
            break

    cdur_msg = None
    cdur_err = "could not verify chat duration"
    if not media_fn:
        cdur_err += ": could not find media file"
    else:
        info("calculating media duration")
        try:
            chat_dur = jd[-1]["time_in_seconds"]
            v_dur = get_ff_dur(media_fn)
            delta = abs(chat_dur - v_dur)
            perc = delta * 100.0 / max(v_dur, chat_dur)
            if delta > 60:
                cdur_err = f"media duration ({v_dur:.0f}sec) and chat duration ({chat_dur:.0f}sec) differ by {delta:.0f}sec ({perc:.2f}%)"
            else:
                cdur_err = None
                cdur_msg = f"chat duration appears correct; {v_dur:.0f}sec - {chat_dur:.0f}sec = {delta:.0f}sec ({perc:.2f}%)"
        except Exception as ex:
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

        nick = msg["author"]
        uid = msg["author_id"]

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

        # if nick == "McDoogle":
        #    print(f"{nick} {uid} {msg['message']}")

    info(f"tagged {len(nick_dupes)} dupes:")
    for k, v in sorted(nick_list.items(), key=lambda x: [-len(x[1]), x[0]])[:20]:
        info(f"  {len(v)}x {k}")

    msgs = []
    info(f"converting")
    last_msg = None
    for n_msg, msg in enumerate(jd):
        txt = msg["message"] or "--"
        cmp_msg = f"{msg['author_id']}\n{txt}"
        if last_msg == cmp_msg:
            continue

        last_msg = cmp_msg

        try:
            t_fsec = msg["video_offset_time_msec"] / 1000.0
            t_isec = msg["time_in_seconds"]
            t_hms = msg["time_text"]
        except:
            # rip was made using a chat_replay_downloader.py from before 2020-11-01
            t_fsec = msg["time_in_seconds"]
            t_hms = msg["time_text"].split(".")[0]
            t_isec = int(t_fsec)

        if t_hms.startswith("-") or t_isec < 0:
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
            # and video_offset_time_msec, so please let me have a look at
            # your chatlog json if you end up here
            raise Exception(
                f"time drift [{t_fsec}] [{t_isec}] [{t_isec2}] [{t_hms}]\n  (pls provide this chat-rip to ed)"
            )

        for k, v in emotes.items():
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

        # if n_msg % 100 == 0 and len(z.cache) > 1024 * 1024:
        #    z.cache = {}

        # wrap to specified width
        # by splitting on ascii whitespace
        vtxt = z.unrag(txt, bw)
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

        nick = msg["author"]
        if nick in nick_dupes:
            nick += f"  ({msg['author_id']})"

        o = {"nick": nick, "t0": t_fsec, "sx": sx, "sy": sy, "txt": vtxt}

        if "amount" in msg:
            o["shrimp"] = msg["amount"]
            o["color"] = msg["body_color"]["hex"][1:][:-2]  # "#1de9b6ff"

        if "badges" in msg:
            o["badges"] = msg["badges"]

        msgs.append(o)

        # if n_msg > 5000:  # opt
        #    break

    if ar.f:
        opts = {"back": "80", "shad": "ff", "opaq": "3"}
    else:
        opts = {"back": "00", "shad": "80", "opaq": "1"}

    vis = []
    out_fn = ar.fn + ".ass"
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
Style: a,Squished Noto Sans CJK JP Regular,{sz},&H00FFFFFF,&H000000FF,&H{back}000000,&H{shad}000000,0,0,0,0,100,100,0,0,{opaq},2,1,1,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(
                vw=vw, vh=vh, sz=ar.sz, **opts
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

                if "badges" in msg and "Moderator" in msg["badges"]:
                    # mods and other VIPs
                    txt[-1] += rf" {{\bord16\shad6}}*"

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
                    # mods and other VIPs
                    txt = rf"{{\bord24\shad6}}*{{\bord6}}{txt}"

                len_boost = 0.5
                td = (vw + w - w * len_boost) * shrimp_mul / ar.spd
                t1 = t0 + td

                # collision detection polls at 60%..80% (critical) and 30..90% (prefer)
                # from the left, figure out timestamps when the right-side hits those
                abs_spd = (vw + w * 1.0) / td
                p9 = t0 + (w + vw * 0.1) / abs_spd
                p8 = t0 + (w + vw * 0.2) / abs_spd
                p5 = t0 + (w + vw * 0.5) / abs_spd
                p3 = t0 + (w + vw * 0.7) / abs_spd

                # and when the left-side hits those,
                # to compare against other pN's and find a free slot
                a9 = t0 + (vw * 0.1) / abs_spd
                a8 = t0 + (vw * 0.2) / abs_spd
                a5 = t0 + (vw * 0.5) / abs_spd
                a3 = t0 + (vw * 0.7) / abs_spd

                rm = []
                taken_crit = []
                taken_prefer = []
                for m in vis:
                    m_py, m_sy, m_p9, m_p8, m_p5, m_p3, m_txt = [
                        m[x] for x in ["py", "sy", "p9", "p8", "p5", "p3", "txt"]
                    ]

                    # if (
                    #    "So what's the to do list for today G" in m_txt
                    #    and msg["nick"] == "AverageDoggo"
                    # ):
                    #    print("a")

                    if t0 > m_p5:
                        rm.append(m)
                        continue

                    if a8 < m_p8 or a5 < m_p5:
                        # k = f"{m_py} {m_sy} {m_p8}"
                        # if k in seen8:
                        #    desc = json.dumps([seen8[k], m], indent=4, sort_keys=True)
                        #    raise Exception(f"collision: {desc}")
                        #
                        # seen8[k] = m

                        # add txt to avoid sorted() trying to compare m's
                        taken_crit.append([m_py, m_py + m_sy, m_p8, m_txt, m])

                    if a9 < m_p9 or a3 < m_p3:
                        taken_prefer.append([m_py, m_py + m_sy, m_p5, m_txt, m])

                for m in rm:
                    vis.remove(m)

                ymax = vh - h
                overlap_mul = 0.9
                frees_merged = []  # crit + prefer
                for lst in [taken_crit, taken_prefer]:
                    frees = [[ymax, 0, ymax]]  # size, y0, y1
                    for y1, y2, _, _, _ in sorted(lst):
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

                # fallback to critical if no free prefer
                frees = frees_merged[0]
                if not frees:
                    frees = frees_merged[1]

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

                # if "Sandwich is technically correct too" in txt:
                #    print("a")

                y = int(y)
                txt = rf"{{\move({vw},{y+h},{-w},{y+h})\3c&H{c}&}}{txt}{{\fscx40\fscy40\bord1}}\N{nick}"

                msg["t1"] = t1
                msg["p9"] = p9
                msg["p8"] = p8
                msg["p5"] = p5
                msg["p3"] = p3
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

    # from pprint import pprint; pprint(msgs[-5:])
    t1_main = time.time()
    info(f"finished in {t1_main-t0_main:.2f} sec")


if __name__ == "__main__":
    main()


r"""

===[ side-by-side with kanji transcription ]===========================

chat_replay_downloader.py https://www.youtube.com/watch?v=7LXgVlrfsWw -output ars-37-minecraft-3.json

softchat.py ..\yt\ars-37-minecraft-3.json -b 340x500+32+32 && copy /y ..\yt\ars-37-minecraft-3.json.ass ..\yt\ars-37-minecraft-3.json.1.ass

softchat.py ..\yt\ars-37-minecraft-3.json -b 340x500+360+32 --kana && copy /y ..\yt\ars-37-minecraft-3.json.ass ..\yt\ars-37-minecraft-3.json.2.ass

(head -n 21 ars-37-minecraft-3.json.1.ass ; (tail -n +22 ars-37-minecraft-3.json.1.ass; tail -n +22 ars-37-minecraft-3.json.2.ass) | sort) > ars-37-minecraft-3.json.ass

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


===[ junk ]============================================================

..\dev\softchat.py -m 1 -b 320x600+960+32 ame-minecraft-railway-research-2-2.json && C:\Users\ed\bin\mpv.com ame-minecraft-railway-research-2.json.mkv --vo=direct3d --sub-files=ame-minecraft-railway-research-2-2.json.ass --sub-delay=-2 -ss 120

cpy3: 15.46 sec @15k NOcache
cpy3:  8.87 sec @15k 16k 24

pypy: 18.75 sec @15k NOcache
pypy: 15.32 sec @15k 128 32
pypy: 13.32 sec @15k  1k 32
pypy: 12.59 sec @15k  4k 64
pypy: 12.23 sec @15k  4k 16
pypy: 12.09 sec @15k  4k 32
pypy: 12.10 sec @15k  8k 24
pypy: 11.42 sec @15k 16k 64
pypy: 11.39 sec @15k 16k 16
pypy: 11.26 sec @15k 16k 32
pypy: 11.23 sec @15k 16k 24

cpy3 full: 46.45 unb 24
cpy3 full: 48.56 32k 24
pypy full: 54.92 unb 24
pypy full: 57.34 32k 24

grep -E '"(amount|hex|message|time_text)":|^    \},' ame-minecraft-railway-research-2.json | grep -E '"amount":' -C5 | less


===[ p5 and p8 overlay for mpv ]=======================================

mpv.com "[MINECRAFT] WHERE AM I #GAWRGURA-lMFrn59TN_c.mkv" -ss 12:15 --vf "lavfi=[drawtext=fontfile='C\:\\Users\\ed\\dev\\noto-hinted\\SquishedNotoSansCJKjp-Regular.otf':x=16:y=16:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=4:fontsize=28:text='%{pts\:hms}, %{pts}', drawtext=fontfile='C\:\\Users\\ed\\dev\\noto-hinted\\SquishedNotoSansCJKjp-Regular.otf':x=956:y=600:fontcolor=white:box=1:boxcolor=black:fontsize=48:text='|', drawtext=fontfile='C\:\\Users\\ed\\dev\\noto-hinted\\SquishedNotoSansCJKjp-Regular.otf':x=1532:y=600:fontcolor=white:box=1:boxcolor=black:fontsize=48:text='|']"

"""
