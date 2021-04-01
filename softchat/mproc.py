# must be a separate file because mp is dum

import re
import os
import tempfile
from multiprocessing import current_process
from PIL import ImageFont, ImageDraw, Image
from .util import debug, info, warn, error, WINDOWS, load_fugashi


message_translation_table = "".maketrans(
    "",
    "",
    # Skin tone modifiers do not render in subtitles.
    "🏻🏼🏽🏾🏿",
)


class TextStuff(object):
    def __init__(self, sz, fontdir, emote_scale):
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
        self.pad1 = ["\x00" * 1024 * 1024]
        self.font = ImageFont.truetype(self.otf_mod, size=int(sz * 0.9 + 0.9))
        self.pad2 = ["\x00" * 1024 * 1024]
        self.im = Image.new("RGB", (3840, 2160), "white")
        self.pad3 = ["\x00" * 1024 * 1024]
        self.imd = ImageDraw.Draw(self.im)
        self.pad4 = ["\x00" * 1024 * 1024]
        self.pipe_width = self.font.getsize("|")[0]
        # LD_PRELOAD=/usr/lib/libtcmalloc_debug.so ^ memory stomping bug: a word after object has been ocrrupted
        self.pad5 = ["\x00" * 1024 * 1024]
        self.font_ofs = self.font.getmetrics()[1]
        self.cache = {}
        self.vsize = self.caching_vsize
        self.emote_scale = emote_scale
        self.emote_repl = "/%"  # good enough
        self.emote_vsz = self.vsize_impl(self.emote_repl, False)

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

    def unemote(self, text):
        return "".join(
            [
                c if u < 0xE000 or u > 0xF8FF else self.emote_repl
                for c, u in zip(text, [ord(x) for x in text])
            ]
        )

    def vsize_impl(self, text, msg_emotes):
        if msg_emotes:
            text = self.unemote(text)

        w, h = self.imd.textsize("|" + text.replace("\n", "\n|"), self.font)

        if msg_emotes and self.emote_scale > 1.01:
            em_dw, em_dh = [x * self.emote_scale - x for x in self.emote_vsz]
            add_w = 0
            add_h = 0
            for ln in text.split("\n"):
                # yolo: self.emote_repl unlikely to be in messages
                num_emotes = min(len(msg_emotes), ln.count(self.emote_repl))
                if num_emotes:
                    ln_w = em_dw * num_emotes
                    add_w = max(add_w, ln_w)
                    add_h += em_dh
            w += add_w
            h += add_h

        return w - self.pipe_width, h

    def caching_vsize(self, text, msg_emotes):
        if len(text) > 24:
            # debug("cache_skip [{}]".format(text))
            return self.vsize_impl(text, msg_emotes)

        # faster than try/catch and get(text,None)
        if text in self.cache:
            # debug("cache_hit  [{}]".format(text))
            return self.cache[text]

        # debug("cache_miss [{}]".format(text))
        ret = self.vsize_impl(text, msg_emotes)
        self.cache[text] = ret
        return ret

    def unrag(self, text, width, msg_emotes):
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
            offsets.append(offsets[-1] + self.vsize(w + "_", msg_emotes)[0])

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


def gen_msg_initializer(fn, ar, vw, bw, emote_shortcuts, have_fugashi):
    fn.args = [ar, vw, bw, emote_shortcuts]

    ptn_kanji = re.compile(r"[\u4E00-\u9FAF]")
    ptn_kana = re.compile(r"[\u3040-\u30FF]")
    ptn_ascii = re.compile(r"[a-zA-Z]")
    ptn_pre = re.compile(r"([　、。〇〉》」』】〕〗〙〛〜〞〟・…⋯！＂）＊－．／＞？＠＼］＿～｡｣･￭￮]+)")
    ptn_post = re.compile(r"([〈《「『【〔〖〘〚〝（＜［｀｢]+)")

    fn.regs = [ptn_kanji, ptn_kana, ptn_ascii, ptn_pre, ptn_post]

    fn.z = TextStuff(ar.sz, ar.fontdir, ar.emote_sz)
    if have_fugashi:
        try:
            fn.wakati, fn.yomi = load_fugashi()
        except Exception as ex:
            msg = "\033[33m\nfailed to load fugashi in worker:\n{}\n\033[0m\n"
            print(msg.format(repr(ex)), end="")


def gen_msg_thr(a):
    n_msg, msg = a
    [ar, vw, bw, emote_shortcuts] = gen_msg_thr.args
    [ptn_kanji, ptn_kana, ptn_ascii, ptn_pre, ptn_post] = gen_msg_thr.regs

    z = gen_msg_thr.z
    try:
        wakati = gen_msg_thr.wakati
        yomi = gen_msg_thr.yomi
        have_fugashi = True
    except:
        have_fugashi = False

    txt = msg.get("message", "") or ""
    txt = txt.translate(message_translation_table)
    if "amount" not in msg and "money" not in msg and txt == "":
        txt = "--"

    t_fsec = msg["time_in_seconds"]
    t_isec = int(t_fsec)
    t_hms = msg["time_text"]

    if t_hms.startswith("-") or t_isec < 0 or t_isec > 4096 * 4096:
        return None

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
    msg_emotes = []
    if ":" in txt and ar.emote_font:
        old_txt = txt
        for k, v in emote_shortcuts.items():
            txt = txt.replace(k, v)

        if txt != old_txt:
            msg_emotes = [u for u in txt if ord(u) >= 0xE000 and ord(u) <= 0xF8FF]

    # wordwrap gets wonky when emotes are 2big
    # so ensure whtiespace between text and emote regions
    if msg_emotes and ar.emote_sz >= 1.5:
        txt2 = ""
        was_emote = False
        for c, u in zip(txt, [ord(x) for x in txt]):
            if u >= 0xE000 and u <= 0xF8FF:
                if not was_emote and txt2:
                    txt2 += " "
                was_emote = True
            else:
                if was_emote:
                    was_emote = False
                    txt2 += " "
            txt2 += c
        txt = txt2

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
    vtxt = z.unrag(txt, wrap_width, msg_emotes)
    vsz = z.vsize("\n".join(vtxt), msg_emotes)

    if vsz[0] >= bw and is_jp:
        # too wide, is japanese,
        # try wrapping on japanese punctuation instead
        vtxt = ptn_pre.sub("\\1\n", txt)
        vtxt = ptn_post.sub("\n\\1", vtxt)
        vtxt = vtxt.split("\n")
        vsz = z.vsize("\n".join(vtxt), msg_emotes)

        if vsz[0] >= bw and have_fugashi:
            # still too wide, wrap on word-boundaries
            vtxt = z.unrag(wakati.parse(txt), bw, msg_emotes)
            vtxt = [x.replace(" ", "") for x in vtxt]

            for n in range(1, len(vtxt)):
                # move most punctuation to the prev line
                ln = vtxt[n]
                m = ptn_pre.search(ln)
                if m and m.start() == 0:
                    vtxt[n - 1] += ln[: m.end()]
                    vtxt[n] = ln[m.end() :]

            vsz = z.vsize("\n".join(vtxt), msg_emotes)

    vtxt = [x for x in vtxt if x.strip()]

    return [n_msg, msg, vtxt, vsz, t_fsec, t_hms, msg_emotes]
