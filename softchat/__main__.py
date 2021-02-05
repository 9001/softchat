#!/usr/bin/env python3

about = {
    "name": "softchat",
    "version": "0.3",
    "date": "2020-10-13",
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
from datetime import datetime
from PIL import ImageFont, ImageDraw, Image

"""
==[ DEPENDENCIES ]=====================================================
each version below is the latest as of writing,
tested on cpython 3.8.1

 - chat rips made using the modified chat_replay_downloader.py
     mod: https://ocv.me/dev/?chat_replay_downloader.py
     orig: https://github.com/xenova/chat-replay-downloader/

 - all the noto fonts in a subfolder called noto-hinted
     see https://www.google.com/get/noto/
     or just https://noto-website-2.storage.googleapis.com/pkgs/Noto-hinted.zip
     (remove "un" from "unhinted" in the download link)

 - REQUIRED:
   python -m pip install --user pillow

 - OPTIONAL (recommended):
   python -m pip install --user git+https://github.com/googlefonts/nototools.git@v0.2.13#egg=nototools

 - OPTIONAL (recommended):
   python -m pip install --user "fugashi[unidic]"
   python -m unidic download

 - OPTIONAL (this also works with some modifications):
   python -m pip install --user mecab-python3
   # bring your own dictionaries

==[ TODO ]=============================================================

 - build optimal font using noto-merge-fonts
 - per-line background shading (optional)
 - more stuff probably

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
except:
    HAVE_TOKENIZER = False


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


class TextStuff(object):
    def __init__(self, sz):
        self.sz = sz
        self.font = ImageFont.truetype("NotoSansCJKjp-Regular.otf", size=sz)
        self.im = Image.new("RGB", (3840, 2160), "white")
        self.imd = ImageDraw.Draw(self.im)
        self.pipe_width = self.font.getsize('|')[0]
        self.font_ofs = self.font.getmetrics()[1]

    def vsize(self, txt):
        w, h = self.imd.textsize('|' + txt.replace('\n', '\n|'), self.font)
        return w - self.pipe_width, h

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
            lines.append(u" ".join(words[i:j]))
            j = i
        lines.reverse()
        return lines


def hms(s):
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return '{:d}:{:02d}:{:05.2f}'.format(int(h), int(m), s)


def assan(x):
    return x.replace("{", "<").replace("}", ">").replace('\\', '\\{}')


def main():
    t0_main = time.time()

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

    random.seed(b'nope')

    ap = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="convert modified chat_replay_downloader.py json into box-confined or danmaku-style softsubs")

    ap.add_argument("-m", metavar='MODE', type=int, default=1, help="mode, 1=box, 2=danmaku")
    ap.add_argument("-r", metavar='WxH', type=str, default="1280x720", help="video res")
    ap.add_argument("-b", metavar='WxH+X+Y', type=str, default=None, help="subtitle area")
    ap.add_argument("-f", action='store_true', help='fill chat background')
    ap.add_argument("--sz", metavar='POINTS', type=int, default=0, help="font size")
    ap.add_argument("--spd", metavar='SPEED', type=int, default=256, help="[danmaku] pixels/sec")
    ap.add_argument("--kana", action="store_true", help="convert kanji to kana")
    ap.add_argument("fn", metavar='JSON_FILE')
    ar = ap.parse_args()

    if not ar.sz:
        ar.sz = 24 if ar.m == 1 else 32
        info(f"fontsize {ar.sz} pt")

    vw, vh = [int(x) for x in ar.r.split('x')]

    bw, bh, bx, by = [int(x) for x in re.split(r'[x,+]+', ar.b if ar.b else ar.r + '+0+0')]

    z = TextStuff(ar.sz)
    fofs = z.font_ofs

    info(f"loading {ar.fn}")
    with open(ar.fn, 'r', encoding='utf-8') as f:
        jd = json.load(f)

    ptn_kanji = re.compile(r'[\u4E00-\u9FAF]')
    ptn_kana = re.compile(r'[\u3040-\u30FF]')
    ptn_ascii = re.compile(r'[a-zA-Z]')
    ptn_pre = re.compile(r'([　、。〇〉》」』】〕〗〙〛〜〞〟・…⋯！＂）＊－．／＞？＠＼］＿～｡｣･￭￮]+)')
    ptn_post = re.compile(r'([〈《「『【〔〖〘〚〝（＜［｀｢]+)')

    msgs = []
    info(f"converting {len(jd)} chat entries")
    last_msg = None
    for n_msg, msg in enumerate(jd):
        txt = msg['message'] or '--'
        cmp_msg = f"{msg['author_id']}\n{txt}"
        if last_msg == cmp_msg:
            continue

        last_msg = cmp_msg

        n_ascii = len(ptn_ascii.findall(txt))
        n_kanji = len(ptn_kanji.findall(txt))
        n_kana = len(ptn_kana.findall(txt))
        
        # if the amount of ascii compared to kanji/kana
        # is less than 30%, assume we'll need MeCab
        is_jp = (n_kanji + n_kana) / (n_kanji + n_kana + n_ascii + 0.1) > 0.7

        # transcription from kanji to kana if requested
        if ar.kana and is_jp and n_kanji:
            txt = yomi.parse(txt)

        if ar.m == 1:
            # wrap to specified width
            # by splitting on ascii whitespace
            vtxt = z.unrag(txt, bw)
            vsz = z.vsize('\n'.join(vtxt))
            
            if vsz[0] >= bw and is_jp:
                # too wide, is japanese,
                # try wrapping on japanese punctuation instead
                vtxt = ptn_pre.sub("\\1\n", txt)
                vtxt = ptn_post.sub("\n\\1", vtxt)
                vtxt = vtxt.split('\n')
                vsz = z.vsize('\n'.join(vtxt))

                if vsz[0] >= bw and HAVE_TOKENIZER:
                    # still too wide, wrap on word-boundaries
                    vtxt = z.unrag(wakati.parse(txt), bw)
                    vtxt = [x.replace(' ', '') for x in vtxt]

                    for n in range(1, len(vtxt)):
                        # move most punctuation to the prev line
                        ln = vtxt[n]
                        m = ptn_pre.search(ln)
                        if m and m.start() == 0:
                            vtxt[n-1] += ln[:m.end()]
                            vtxt[n] = ln[m.end():]

                    vsz = z.vsize('\n'.join(vtxt))
        else:
            # danmaku; no wrapping
            vsz = z.vsize(txt.replace('\n', ' '))
            vtxt = [txt]

        if n_msg % 100 == 0:
            info('  {} / {}   {}   {}\n   {}\n'.format(
                n_msg, len(jd), msg["time_text"], vsz, '\n   '.join(vtxt)))

        o = {
            "name": msg["author"],
            "t0": msg["time_in_seconds"],
            "sx": vsz[0],
            "sy": vsz[1],
            "txt": vtxt
        }

        if 'amount' in msg:
            o['shrimp'] = msg['amount']
            o['color'] = msg['body_color']['hex'][1:][:-2]  # "#1de9b6ff"
        
        msgs.append(o)

        if n_msg > 5000:
            break
    
    if ar.f:
        opts = {
            'back': '80',
            'shad': 'ff',
            'opaq': '3'
        }
    else:
        opts = {
            'back': '00',
            'shad': '80',
            'opaq': '1'
        }

    vis = []
    out_fn = ar.fn + ".ass"
    info(f"creating {out_fn}")
    with open(out_fn, "wb") as f:
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
Style: a,Noto Sans CJK JP Regular,{sz},&H00FFFFFF,&H000000FF,&H{back}000000,&H{shad}000000,0,0,0,0,100,100,0,0,{opaq},2,1,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(vw=vw, vh=vh, sz=ar.sz, **opts).encode('utf-8'))

        # Dialogue: 0,0:00:00.00,0:00:05.00,a,,0,0,0,,hello world

        msg = None
        yhist = []
        supers = []
        colormap = {}
        for next_msg in msgs + [None]:
            if not msg or (next_msg and next_msg["t0"] <= 0):
                msg = next_msg
                continue

            name = msg["name"]
            c = colormap.get(name, None)
            if not c:
                if ar.m == 1:
                    bri = 0.5
                    sat = 1
                else:
                    bri = 0.4
                    sat = 0.8

                c = zlib.crc32(name.encode('utf-8')) & 0xffffffff
                r, g, b = [int(x*255) for x in colorsys.hsv_to_rgb((c % 256) / 256.0, sat, bri)]
                c = f'{r:02x}{g:02x}{b:02x}'
                colormap[name] = c

            shrimp = None
            if 'shrimp' in msg:
                c2 = msg['color']
                c2 = f"{c2[4:6]}{c2[2:4]}{c2[0:2]}"  # thx ass
                shrimp = rf"{{\bord4\shad4\3c&H{c2}&\c&H000000&}}{msg['shrimp']}"

            name = assan(name)
            msg["txt"] = [assan(x) for x in msg["txt"]]

            if ar.m == 1:
                # text = colored name followed by the actual lines, ass-escaped
                txt = [rf"{{\3c&H{c}&}}{name}"]
                if shrimp:
                    txt.append(shrimp)

                txt.extend(msg["txt"])
                
                # show new messages bottom-left (heh)
                msg["txt"] = txt
                msg["px"] = bx
                msg["py"] = by + bh - msg["sy"] - fofs / 2  # or something idgi
                
                ta = hms(msg["t0"])
                tb = hms(next_msg["t0"] if next_msg else msg["t0"] + 10)

                rm = 0
                for m in vis:
                    m["py"] -= msg["sy"]
                    if m["py"] + m["sy"] < by:
                        #debug('drop {} at {}'.format(hms(m["t0"]), ta))
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
            else:
                txt, t0, w, h = [msg[x] for x in ["txt", "t0", "sx", "sy"]]
                txt = ' '.join(txt)
                
                len_boost = 0.3
                td = (vw + w - w * len_boost) / ar.spd
                
                # find an y-pos that isn't too crowded;
                # and try 16 random y-positions, and
                # look through the <=128 last y-positions used
                # summing up the distance between selected and past
                # with decreasing importance (mul) as we move older
                ys = []
                for _ in range(32):
                    y = int(random.randrange(int(vh - h)) - fofs)
                    dist = 0
                    mul = 1.1
                    for oy in reversed(yhist[-8:]):
                        dist += abs(y - oy) * mul
                        mul /= 8.0

                    ys.append([dist, y])
                
                yhist.append(sorted(ys)[-1][1])
                if len(yhist) > 128:
                    yhist = yhist[64:]
                
                if shrimp:
                    td *= 2
                    txt = f"{shrimp} {txt}"
                    w += 256  # amount is not included, TODO maybe

                txt = rf"{{\move({vw},{y},{-w},{y})\3c&H{c}&}}{txt}{{\fscx40\fscy40\bord1}}\N{name}"

                ln = "Dialogue: 0,{},{},a,,0,0,0,,{}\n".format(
                    hms(t0), hms(t0 + td), txt).encode('utf-8')

                if shrimp:
                    supers.append(ln)
                else:
                    f.write(ln)

            msg = next_msg

        for ln in supers:
            f.write(ln)

    from pprint import pprint; pprint(msgs[-5:])
    t1_main = time.time()
    info(f'finished in {t1_main-t0_main:.2f} sec')


if __name__ == '__main__':
    main()


r"""
chat_replay_downloader.py https://www.youtube.com/watch?v=7LXgVlrfsWw -output ars-37-minecraft-3.json

softchat.py ..\yt\ars-37-minecraft-3.json -b 320x550+64+75

softchat.py ..\yt\ars-37-minecraft-3.json -b 320x450+64+75 && copy /y ..\yt\ars-37-minecraft-3.json.ass ..\yt\ars-37-minecraft-3.json.1.ass

softchat.py ..\yt\ars-37-minecraft-3.json --kana -b 320x450+324+75 && copy /y ..\yt\ars-37-minecraft-3.json.ass ..\yt\ars-37-minecraft-3.json.2.ass

(head -n 21 ars-37-minecraft-3.json.1.ass ; (tail -n +22 ars-37-minecraft-3.json.1.ass; tail -n +22 ars-37-minecraft-3.json.2.ass) | sort) > ars-37-minecraft-3.json.ass

c:\users\ed\bin\mpv.com "..\yt\ars-37-minecraft-3.json.mkv" -ss 1:15:20

-----------------------------------------------------------------------

chat_replay_downloader.py https://www.youtube.com/watch?v=0Qygvs0rG50 -output ame-minecraft-railway-research.json
chat_replay_downloader.py ame-minecraft-railway-research.json.json -output ame-minecraft-railway-research-2.json

..\dev\softchat.py -m 2 "ame-minecraft-railway-research-2.json" && C:\Users\ed\bin\mpv.com ame-minecraft-railway-research-2.json.mkv --vo=direct3d --vf=fps=90 --sub-delay=-3 -ss 30:20
C:\Users\ed\bin\mpv.com ame-minecraft-railway-research-2.json.mkv --interpolation=yes --blend-subtitles=yes --video-sync=display-resample --tscale=mitchell --hwdec=off --vo=direct3d
C:\Users\ed\bin\mpv.com ame-minecraft-railway-research-2.json.mkv --vo=direct3d --vf=fps=90 --interpolation=no --blend-subtitles=no --sub-delay=-3

..\dev\softchat.py -m 1 -b 320x600+960+32 ame-minecraft-railway-research-2-2.json && C:\Users\ed\bin\mpv.com ame-minecraft-railway-research-2.json.mkv --vo=direct3d --sub-files=ame-minecraft-railway-research-2-2.json.ass --sub-delay=-3 -ss 120

-----------------------------------------------------------------------

pypy: 7.68 sec
cpy3: 5.88 sec

grep -E '"(amount|hex|message|time_text)":|^    \},' ame-minecraft-railway-research-2.json | grep -E '"amount":' -C5 | less

"""
