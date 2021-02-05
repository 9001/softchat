#!/usr/bin/env python3

about = {
    "name": "softchat",
    "version": "0.2",
    "date": "2020-10-12",
    "description": "convert twitch/youtube chat into softsubs",
    "author": "ed",
    "license": "MIT",
    "url": "https://github.com/9001/softchat",
}

import re
import os
import sys
import json
import zlib
import logging
import argparse
import colorsys
from PIL import ImageFont, ImageDraw, Image


"""
DEPENDENCIES
each version below is the latest as of writing,
tested on cpython 3.8.1

 - chat rips made using the modified chat_replay_downloader.py
     mod: https://ocv.me/dev/?chat_replay_downloader.py
     orig: https://github.com/xenova/chat-replay-downloader/

 - all the noto fonts in a subfolder called noto-hinted
     see https://www.google.com/get/noto/
     or just https://noto-website-2.storage.googleapis.com/pkgs/Noto-hinted.zip
     (remove "un" from "unhinted" in the download link)

 - OPTIONAL (recommended):
   python -m pip install --user git+https://github.com/googlefonts/nototools.git@v0.2.13#egg=nototools

 - OPTIONAL (recommended):
   python -m pip install --user "fugashi[unidic]"
   python -m unidic download

 - OPTIONAL (this also works with some modifications):
   python -m pip install --user mecab-python3
   # bring your own dictionaries

"""


try:
    from nototools import merge_fonts

    HAVE_NOTO_MERGE = True
except ImportError:
    HAVE_NOTO_MERGE = False


try:
    # TODO
    #   help python find libmecab.dll, adjust this to fit your env
    dll_path = r'C:\Users\ed\AppData\Roaming\Python\lib\site-packages\fugashi'
    os.add_dll_directory(dll_path)
    from fugashi import Tagger
    
    dicrc = os.path.join(dll_path, 'dicrc')
    with open(dicrc, 'wb') as f:
        f.write('\n'.join([
            r'node-format-yomi = %f[9] ',
            r'unk-format-yomi = %m',
            r'eos-format-yomi  = \n',
            ''
        ]).encode('utf-8'))

    wakati = Tagger('-Owakati')
    yomi = Tagger('-Oyomi -r ' + dicrc.replace('\\', '\\\\'))

    #import MeCab
    #wakati = MeCab.Tagger('-Owakati')
    HAVE_TOKENIZER = True
except ImportError:
    HAVE_TOKENIZER = False
    raise


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
        return f"\033[0;36m{ts}{ansi} {record.msg}"


# globals
#
im = None
imd = None
font = None
font_ofs = None
pipe_width = None
#
# end globals


def vsize(text):
    global font, im, imd, font_ofs, pipe_width
    if not font:
        #font = ImageFont.truetype("NotoSans-Regular.ttf", size=24)
        font = ImageFont.truetype("NotoSansCJKjp-Regular.otf", size=24)
        im = Image.new("RGB", (3840, 2160), "white")
        imd = ImageDraw.Draw(im)
        pipe_width = font.getsize('|')[0]
        font_ofs = font.getmetrics()[1]

    w, h = imd.textsize('|' + text.replace('\n', '\n|'), font)
    return w - pipe_width, h


def vsize_nih(text):
    global font, pipe_width
    if not font:
        #font = ImageFont.truetype("NotoSans-Regular.ttf", size=24)
        font = ImageFont.truetype("NotoSansCJKjp-Regular.otf", size=24)
        pipe_width = font.getsize('|')[0]
    
    w = 0
    h = 0
    for ln in text.split('\n'):
        cw, ch = font.getsize('|' + ln)
        w = max(w, cw - pipe_width)
        h += ch

    return w, h


def unrag(text, width):
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
        offsets.append(offsets[-1] + vsize(w + "_")[0])

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
        lines.append(u" ".join(words[i:j]))
        j = i
    lines.reverse()
    return lines


def test1():
    txt = sys.argv[1]
    vsz = vsize(txt)
    print('visible dimensions of [{}] = {}'.format(txt, vsz))


def hms(s):
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return '{:d}:{:02d}:{:05.2f}'.format(int(h), int(m), s)


def main():
    global font_ofs  # pillow bug workaround i think

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

    ap = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="convert modified chat_replay_downloader.py json into box-confined or danmaku-style softsubs")

    ap.add_argument("-m", metavar='MODE', type=int, default=1, help="mode, 1=box, 2=danmaku")
    ap.add_argument("-r", metavar='WxH', type=str, default="1280x720", help="video res")
    ap.add_argument("-b", metavar='WxH+X+Y', type=str, default=None, help="subtitle area")
    ap.add_argument("--kana", action="store_true", help="convert kanji to kana")
    ap.add_argument("fn", metavar='JSON_FILE')
    ar = ap.parse_args()

    vw, vh = [int(x) for x in ar.r.split('x')]

    bw, bh, bx, by = [int(x) for x in re.split(r'[x,+]+', ar.b if ar.b else ar.r + '+0+0')]

    with open(ar.fn, 'r', encoding='utf-8') as f:
        jd = json.load(f)

    ptn_kanji = re.compile(r'[\u4E00-\u9FAF]')
    ptn_kana = re.compile(r'[\u3040-\u30FF]')
    ptn_ascii = re.compile(r'[a-zA-Z]')
    ptn_pre = re.compile(r'([　、。〇〉》」』】〕〗〙〛〜〞〟・…⋯！＂）＊－．／＞？＠＼］＿～｡｣･￭￮]+)')
    ptn_post = re.compile(r'([〈《「『【〔〖〘〚〝（＜［｀｢]+)')

    msgs = []
    for n_msg, msg in enumerate(jd):
        txt = msg['message']
        n_ascii = len(ptn_ascii.findall(txt))
        n_kanji = len(ptn_kanji.findall(txt))
        n_kana = len(ptn_kana.findall(txt))
        
        # if the amount of ascii compared to kanji/kana
        # is less than 30%, assume we'll need MeCab
        is_jp = (n_kanji + n_kana) / (n_kanji + n_kana + n_ascii + 0.1) > 0.7

        # transcription from kanji to kana if requested
        if ar.kana and is_jp and n_kanji:
            txt = yomi.parse(txt)

        # then wrap to specified width
        # by splitting on ascii whitespace
        vtxt = unrag(txt, bw)
        vsz = vsize('\n'.join(vtxt))
        
        if vsz[0] >= bw and is_jp:
            # too wide, is japanese,
            # try wrapping on japanese punctuation instead
            vtxt = ptn_pre.sub("\\1\n", txt)
            vtxt = ptn_post.sub("\n\\1", vtxt)
            vtxt = vtxt.split('\n')
            vsz = vsize('\n'.join(vtxt))

            if vsz[0] >= bw and HAVE_TOKENIZER:
                # still too wide, wrap on word-boundaries
                vtxt = unrag(wakati.parse(txt), bw)
                vtxt = [x.replace(' ', '') for x in vtxt]

                for n in range(1, len(vtxt)):
                    # move most punctuation to the prev line
                    ln = vtxt[n]
                    m = ptn_pre.search(ln)
                    if m and m.start() == 0:
                        vtxt[n-1] += ln[:m.end()]
                        vtxt[n] = ln[m.end():]

                vsz = vsize('\n'.join(vtxt))

        if n_msg % 100 == 0:
            print('{} / {}   {}   {}\n   {}\n'.format(
                n_msg, len(jd), msg["time_text"], vsz, '\n   '.join(vtxt)))

        msgs.append({
            "name": msg["author"],
            "t0": msg["time_in_seconds"],
            "sx": vsz[0],
            "sy": vsz[1],
            "txt": vtxt
        })

        #if n_msg > 500:
        #    break
    
    vis = []
    fofs = font_ofs
    with open(ar.fn + ".ass", "wb") as f:
        f.write("""\
[Script Info]
Title: softchat.py
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
Style: a,Noto Sans CJK JP Regular,24,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(vw=vw, vh=vh).encode('utf-8'))

        # Dialogue: 0,0:00:00.00,0:00:05.00,a,,0,0,0,,hello world

        msg = None
        colormap = {}
        for next_msg in msgs:
            if not msg or next_msg["t0"] <= 0:
                msg = next_msg
                continue

            name = msg["name"]
            c = colormap.get(name, None)
            if not c:
                c = zlib.crc32(name.encode('utf-8')) & 0xffffffff
                r, g, b = [int(x*255) for x in colorsys.hsv_to_rgb((c % 256) / 256.0, 1, 0.5)]
                c = f'{r:02x}{g:02x}{b:02x}'
                colormap[name] = c

            # text = colored name followed by the actual lines, ass-escaped
            txt = [rf"{{\3c&H{c}&}}{name}"]
            txt.extend([x.replace('\\', '\\{}').replace("{", "<").replace("}", ">") for x in msg["txt"]])
            
            # show new messages bottom-left (heh)
            msg["txt"] = txt
            msg["px"] = bx
            msg["py"] = by + bh - msg["sy"] - fofs / 2  # or something idgi
            
            ta = hms(msg["t0"])
            tb = hms(next_msg["t0"])

            rm = 0
            for m in vis:
                m["py"] -= msg["sy"]
                if m["py"] + m["sy"] < by:
                    #print('drop {} at {}'.format(hms(m["t0"]), ta))
                    rm += 1

            vis = vis[rm:] + [msg]
            
            for m in vis:
                step = m["sy"] / len(m["txt"])
                x = m["px"]
                y = m["py"]
                for ln in m["txt"]:
                    txt = r'{{\pos({},{})}}{}'.format(x, y, ln)
                    x = m["px"] + 8
                    y += step
                    f.write("Dialogue: 0,{},{},a,,0,0,0,,{}\n".format(
                        ta, tb, txt).encode('utf-8'))

            msg = next_msg

    from pprint import pprint; pprint(msgs[-5:])


if __name__ == '__main__':
    main()


r"""
python chat_replay_downloader.py https://www.youtube.com/watch?v=7LXgVlrfsWw -output ars-37-minecraft-3.json

softchat.py ..\yt\ars-37-minecraft-3.json -b 320x550+64+75
softchat.py ..\yt\ars-37-minecraft-3.json -b 320x450+64+75
copy /y ..\yt\ars-37-minecraft-3.json.ass ..\yt\ars-37-minecraft-3.json.1.ass
softchat.py ..\yt\ars-37-minecraft-3.json --kana -b 320x450+364+75
copy /y ..\yt\ars-37-minecraft-3.json.ass ..\yt\ars-37-minecraft-3.json.2.ass
(head -n 21 ars-37-minecraft-3.json.1.ass ; (tail -n +22 ars-37-minecraft-3.json.1.ass; tail -n +22 ars-37-minecraft-3.json.2.ass) | sort) > ars-37-minecraft-3.json.ass
c:\users\ed\bin\mpv.com "..\yt\ars-37-minecraft-3.json.mkv" -ss 1:15:20
"""
