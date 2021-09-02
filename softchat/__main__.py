#!/usr/bin/env python3

about = {
    "name": "softchat",
    "version": "1.3",
    "date": "2021-09-02",
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
import shlex
import string
import base64
import random
import requests
import pprint
import hashlib
import shutil
import argparse
import tempfile
import colorsys
import multiprocessing
import subprocess as sp
from PIL import Image
from .util import debug, info, warn, error, init_logger
from .util import WINDOWS, HAVE_FONTFORGE
from .util import shell_esc, zopen, tt, hms, get_ff_dur, load_fugashi
from .mproc import TextStuff, gen_msg_thr, gen_msg_initializer
from .ass import assan, segment_msg, render_msegs


try:
    from nototools import merge_fonts

    HAVE_NOTO_MERGE = True
except ImportError:
    HAVE_NOTO_MERGE = False


if __name__ == "__main__":
    init_logger("-d" in sys.argv)


HAVE_MAGICK = False
try:
    magick = ["magick", "convert"]
    if shutil.which(magick[0]) is None and not WINDOWS:
        magick = ["convert"]

    if shutil.which(magick[0]) is not None:
        HAVE_MAGICK = True
except:
    pass


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


def cache_emotes(emotes, emote_dir, overwrite):
    try:
        lastmod_softchat = os.stat(os.path.abspath(__file__)).st_mtime
    except:
        lastmod_softchat = 0
        warn("could not lastmod self, will not replace existing png/svg emotes")

    for e in emotes.values():
        source_fname = os.path.join(emote_dir, e["id"].replace("/", "_"))
        try:
            im = Image.open(source_fname)
            source_ok = True
        except:
            source_ok = False

        if not source_ok:
            url = None
            alts = []
            best = 0
            for img in e["images"]:
                if img["id"] == "source":
                    url = img["url"]
                    break

                w = img["width"]
                if w < best:
                    continue

                if w > best:
                    best = w
                    alts = []

                alts.append(img)
                if "dark" in img["id"]:
                    url = img["url"]

            if url is None and alts:
                url = alts[-1]["url"]

            if url is None:
                error(f"Could not find URL for {e['name']}")
                sys.exit(1)

            r = requests.get(url)
            # Save the originals in case youtube stops providing them for whatever reason.
            # These can also be used to manually replace the svgs if the automatically
            # generated one is of low quality.
            with open(source_fname, "wb") as f:
                f.write(r.content)

            r.close()

        # look for existing intermediate file for fontforge
        for ext in [".png", ".svg"]:
            fname = source_fname + ext
            try:
                lastmod = os.stat(fname).st_mtime
                break
            except:
                lastmod = 0
                fname = None

        if not fname:
            if WINDOWS:
                # windows imagemagick doesn't seem to have potrace
                fname = source_fname + ".png"
            else:
                # macports does, most linux distros probably do
                fname = source_fname + ".svg"

        e["filename"] = os.path.abspath(fname)

        fill_fname = source_fname + ".bg"
        e["fill"] = os.path.exists(fill_fname)

        manual_fname = source_fname + ".manual.svg"
        if os.path.isfile(manual_fname):
            debug(f"Using {e['name']:14} {manual_fname}")
            e["filename"] = os.path.abspath(manual_fname)
        elif (lastmod != 0 and not overwrite) or lastmod > lastmod_softchat:
            debug(f"Reusing {e['name']:14} {fname}")
        else:
            info(f"Converting {e['name']:14} {fname}")
            cmd = magick[:]
            # fmt: off
            cmd.extend([
                source_fname,
                "-fill", "white",
                "-flatten",
                "-filter", "Jinc",
                "-resize", "1000x",
                "-colorspace", "gray",
                # Determined experimentally to be a good middle-ground.
                # Higher black values catch more detail but values that are too
                # high produce noisy, ugly output. Higher white values result
                # in better handling of flat areas and gradients but values
                # that are too high will destroy detail.
                # There is no single best option for all emotes.
                "-contrast-stretch", "3%x9%",
                "-channel", "rgb",
                "-negate",
                fname,
            ])
            # fmt: on

            completed = sp.run(cmd)
            if completed.returncode != 0:
                error(f"Failed to convert {e['name']}")
                warn(shell_esc(cmd))
                sys.exit(1)


def generate_font_with_ffpython(*args):
    jtxt = json.dumps(args)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="softchat-", delete=False
    ) as tf:
        tf_path = tf.name
        tf.write(jtxt)

    libdir = os.path.dirname(os.path.abspath(__file__))
    libdir = os.path.join(libdir, "..")

    env = os.environ.copy()
    old_libdir = env.get("PYTHONPATH")
    if old_libdir:
        libdir = [x.strip(os.pathsep) for x in [libdir, old_libdir]]
        libdir = os.pathsep.join(libdir)

    env["PYTHONPATH"] = libdir

    sp.check_call([HAVE_FONTFORGE, "-m", "softchat.fff", tf_path], env=env)

    with open(tf_path, "r", encoding="utf-8") as f:
        ret = f.read()

    os.unlink(tf_path)
    return json.loads(ret)


def generate_font(emotes, font_fn, font_name, dont_write):
    args = [emotes, font_fn, font_name, dont_write]
    if HAVE_FONTFORGE is not True:
        return generate_font_with_ffpython(*args)

    from . import fff

    return fff.gen_fonts(*args)


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
    ap.add_argument("-d", action="store_true", help="emable debug logging")
    ap.add_argument("-m", metavar="MODE", type=int, default=1, help="mode, 1=box, 2=danmaku")
    ap.add_argument("-r", metavar="WxH", type=str, default="1280x720", help="video res")
    ap.add_argument("-b", metavar="WxH+X+Y", type=str, default=None, help="subtitle area")
    ap.add_argument("-j", metavar="CORES", type=int, default=0, help="number of cores to use (0=all, 1=single-threaded)")
    ap.add_argument("--sz", metavar="POINTS", type=int, default=0, help="font size")
    ap.add_argument("--spd", metavar="SPEED", type=int, default=256, help="[danmaku] pixels/sec")
    ap.add_argument("--spread", action="store_true", help="[danmaku] even distribution")
    ap.add_argument("--kana", action="store_true", help="convert kanji to kana")
    ap.add_argument("--fontdir", metavar="DIR", type=str, default=None, help="path to noto-hinted")
    ap.add_argument("--dupe_thr", metavar="SEC", type=float, default=10, help="Hide duplicate messages from the same author within this many seconds")
    ap.add_argument("--no_del", action="store_true", help="keep msgs deleted by mods")
    ap.add_argument("--start_time", metavar="STRT", type=int, default=None, help="Start time of the video in as a unix timestamp in seconds. Only used when there is no VOD chat download.")
    ap.add_argument("--offset", metavar="OFS", type=float, default=None, help="Offset in seconds to apply to the chat. Positive values delay the chat, negative values advance the chat, the same as subtitle delay in MPV. Use with incomplete video downloads or when estimating the start time.")
    ap.add_argument("--badge_sz", metavar="MUL", type=float, default=2, help="Multiplier for VIP icon size")
    ap.add_argument("--emote_font", action="store_true", help="Generate a custom emote font for emotes found in this stream. The subtitle file produced will require the specific embedded font generated by this run to be embedded in the media file.")
    ap.add_argument("--emote_cache", metavar="EMOTE_DIR", type=str, default=None, help="Directory to store emotes in. By default it is $pwd/emotes, but using the same directory for all invocations is safe. Will be created if it does not exist.")
    ap.add_argument("--emote_sz", metavar="MUL", type=float, default=1, help="Emote size multiplier")
    ap.add_argument("--emote_fill", action="store_true", help="Fill emote backgrounds")
    ap.add_argument("--emote_refilter", action="store_true", help="Replaces your preprocessed emotes (*.png) if this version of softchat is more recent than each png")
    ap.add_argument("--embed_files", action="store_true", help="Will attempt to embed the subtitles and emote font, if generated, into the media file. This will make a copy of the media file.")
    ap.add_argument("--cleanup", action="store_true", help="If --embed_files is used, delete the produced subtitle and font files after embedding them. The original media file and chat downloads are never touched.")
    ap.add_argument("--media", metavar="MEDIA", type=str, default=None, help="The video file for the stream. Passing this is optional since it will be detected automatically if it shares a name with the chat replay file.")
    ap.add_argument("--emote_chat_file", metavar="EMOTE_DUMP", type=str, default=None, help="You probably don't need this. A chat file for another stream including emotes, for use with legacy chat files that do not include emotes when it's impossible to get a new chat replay download.")
    ap.add_argument("--emote_nofont", action="store_true", help="[DEBUG] disable font generation")
    ap.add_argument("--emote_install", action="store_true", help="install emote fonts into media player folders")
    ap.add_argument("--emote_install_dir", type=str, default=None, help="Optional directory to install fonts, if not present will try to determine a default system location.")
    ap.add_argument("--no_errdep_emotes", action="store_true", help="ignore missing dependencies for requested emote stuff; disable the unsatisfiable arguments and continue")
    ap.add_argument("fn", metavar="JSON_FILE", nargs="+")
    ar = ap.parse_args()
    # fmt: on

    have_fugashi = bool(load_fugashi(write_cfg=True))
    if ar.kana and not have_fugashi:
        error("you requested --kana but mecab failed to load")
        sys.exit(1)

    if ar.emote_font:
        err = []
        if not HAVE_MAGICK:
            err.append("imagemagick")

        if not HAVE_FONTFORGE:
            err.append("fontforge")

        if err:
            err = ", ".join(err)
            error(f"you requested --emote_font but {err} is not installed")
            if ar.no_errdep_emotes:
                ar.emote_font = None
                ar.emote_sz = 1
            else:
                sys.exit(1)

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

                mfn = os.path.join(os.getcwd(), os.path.split(mfn)[1])
                if os.path.isfile(mfn):
                    media_fn = mfn
                    break

    base_fn = ar.fn[0].rsplit(".json", 1)[0]
    if media_fn:
        base_fn = media_fn.rsplit(".", 1)[0]

    out_fn = base_fn + ".ass"
    font_fn = base_fn + ".ttf"
    if WINDOWS:
        allowed = string.ascii_letters + string.digits + ".,-"
        font_fn = "".join([x if x in allowed else "_" for x in font_fn])

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

    z = TextStuff(ar.sz, ar.fontdir, ar.emote_sz)
    fofs = z.font_ofs
    emotes = dict()

    jd = []
    deleted_messages = set()
    deleted_authors = set()
    seen = set()
    for fn in ar.fn:
        info(f"loading {fn}")
        with zopen(fn, "r", encoding="utf-8") as f:
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

                if "emotes" in m:
                    customs = []
                    stocks = []
                    for x in m["emotes"]:
                        if x.get("is_custom_emoji", True):
                            customs.append(x)
                        else:
                            stocks.append(x)
                    
                    # only keep/convert the custom emotes
                    m["emotes"] = customs

                    # non-customs have regular unicode emojis as IDs,
                    # so swap out the shortcuts with those instead
                    for emote in stocks:
                        uchar = emote["id"]
                        if len(uchar) > 8:
                            continue
                        
                        txt = m["message"]
                        for sc in emote["shortcuts"]:
                            txt = txt.replace(sc, uchar)
                        
                        m["message"] = txt

                if at is None and "message" in m:
                    # twitch
                    msg = m["message"]
                    at = "add_chat_item"
                    for emote in m.get("emotes", []):
                        if "shortcuts" in emote:
                            warn(f"expected no shortcuts, got [{emote['shortcuts']}]")
                            continue

                        shortcut = ":" + emote["name"] + ":"
                        msg = msg.replace(emote["name"], shortcut)
                        emote["shortcuts"] = [shortcut]

                    m["message"] = msg

                if (
                    at != "add_chat_item"
                    or m.get("author", {}).get("id", None) is None
                    or (
                        m.get("message", False) is False
                        and "amount" not in m
                        and "money" not in m
                    )
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

        with zopen(ar.emote_chat_file, "r", encoding="utf-8") as f:
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
    emote_shortcuts = dict()
    filled_emotes = []
    if ar.emote_font:
        info(f"Generating custom font with {len(emotes)} emotes")
        cache_emotes(emotes, emote_dir, ar.emote_refilter)

        # Try to avoid collisions if someone does install these as system fonts.
        font_hash = hashlib.sha512(base_fn.encode("utf-8")).digest()
        font_hash = base64.urlsafe_b64encode(font_hash)[:16].decode("ascii")
        font_name = f"SoftChat Custom Emotes {font_hash}"
        emote_shortcuts, filled_emotes = generate_font(
            emotes, font_fn, font_name, ar.emote_nofont
        )
        filled_emotes = set(filled_emotes)

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
    prev_msg = None
    for x in jd:
        unix = x["timestamp"] / 1_000_000.0
        t = x.get("time_in_seconds", None)

        # Superchats have bizarre time_in_seconds that can be off by multiple
        # minutes from when the superchat was originally displayed while the
        # stream was live.
        # At least for now, ignore time_in_seconds for SCs.
        if "amount" in x or "money" in x:
            t = None

        if t is None:
            n_interp += 1
            sec = unix - unix_ofs
            x["time_in_seconds"] = sec
            x["time_text"] = tt(sec)
            tjd.append(x)
        elif t >= 10 and "amount" not in x and "money" not in x:
            njd.append(x)
            video = t
            new_ofs = unix - video
            diff = abs(new_ofs - unix_ofs)
            if diff >= 10:
                m = f"unix/video offset was {unix_ofs:.3f}, new {new_ofs:.3f} at {unix:.3f} and {video:.3f}, diff {new_ofs - unix_ofs:.3f}"
                if diff >= 60:
                    # Assume stream was offline when the gap is greater than a minute
                    tjd.clear()

                    m += ", dropping messages while stream was assumed to be offline"
                    warn(m)
                else:
                    warn(m + ", probably fine")
                pprint.pprint({"prev": prev_msg, "this": x})

            unix_ofs = new_ofs
            if tjd:
                njd.extend(tjd)
                tjd.clear()
        else:
            njd.append(x)

        if ar.offset is not None:
            x["time_in_seconds"] += ar.offset
            x["time_text"] = tt(x["time_in_seconds"])

        prev_msg = x

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
    conv_t0 = time.time()
    for n_msg, msg, vtxt, vsz, t_fsec, t_hms, msg_emotes in gen_msgs(
        jd, vw, bw, ar, emote_shortcuts, have_fugashi
    ):
        sx, sy = vsz
        sy = int(sy - 10)

        if n_msg % 1000 == 0:
            info(
                "  {} / {}   {}%   {}/s   {}   {}\n   {}  \n".format(
                    n_msg,
                    len(jd),
                    int((n_msg * 100) / len(jd)),
                    int(n_msg / (time.time() - conv_t0)),
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
            "msg_emotes": msg_emotes,
        }

        if "amount" in msg or "money" in msg:
            o["shrimp"] = msg["money"]["text"] if "money" in msg else msg["amount"]
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

    vis = []

    info(f"creating {out_fn}")
    with open(out_fn, "wb") as f:
        f.write(
            """\
[Script Info]
Title: https://github.com/9001/softchat
; {cmd}
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
Style: a,{font},{sz},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,1,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(
                vw=vw,
                vh=vh,
                sz=ar.sz,
                font=font_name,
                cmd=" ".join(map(shlex.quote, sys.argv[1:])),
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
            bgr_nick = colormap.get(nick, None)
            if not bgr_nick:
                if ar.m == 1:
                    bri = 0.5
                    sat = 1
                else:
                    bri = 0.4
                    sat = 0.8

                bgr_nick = zlib.crc32(nick.encode("utf-8")) & 0xFFFFFFFF
                r, g, b = [
                    int(x * 255)
                    for x in colorsys.hsv_to_rgb((bgr_nick % 256) / 256.0, sat, bri)
                ]
                bgr_nick = f"{r:02x}{g:02x}{b:02x}"  # and its gonna stay that way
                colormap[nick] = bgr_nick

            # defaults from ass header
            bord = 2
            shad = 1

            shrimp = None
            bgr_msg = bgr_nick
            bgr_fg = "ffffff"
            if "shrimp" in msg:
                bord = shad = 4
                bgr_fg = "000000"
                bgr_msg = msg["color"]
                bgr_msg = f"{bgr_msg[4:6]}{bgr_msg[2:4]}{bgr_msg[0:2]}"  # thx ass
                shrimp = rf"{{\bord{bord}\shad{shad}\3c&H{bgr_msg}&\c&H{bgr_fg}&}}{msg['shrimp']}"

            nick = assan(nick)
            msg["txt"] = [assan(x) for x in msg["txt"]]

            if ar.m == 1:
                # text = colored nick followed by the actual lines, ass-escaped
                txt = [rf"{{\3c&H{bgr_nick}&\fs{ar.sz*0.67:.1f}}}{nick}"]
                lineh = z.emote_vsz[1]
                nickh = lineh * 0.7

                badges = msg.get("badges", [])
                if not set(badges).isdisjoint(["Moderator", "Owner", "Verified"]):
                    txt[0] += r" {\bord16\shad6}*"
                elif msg["uid"] in vips:
                    txt[0] += r" {\bord16\shad4}----"

                if shrimp:
                    txt.append(rf"{{\fscx90\fscy90}}{shrimp}{{\fscx100\fscy100}}")
                    msg["sy"] += lineh

                txt.extend(msg["txt"])
                txt[1] = rf"{{\fs{ar.sz}}}{txt[1]}"

                if msg["msg_emotes"] and (
                    ar.emote_fill or filled_emotes or ar.emote_sz > 1.01
                ):
                    txt = "\n".join(txt)
                    msegs = segment_msg(txt, ar.emote_fill, filled_emotes)
                    txt = render_msegs(
                        msegs, ar.sz, ar.sz * ar.emote_sz, bgr_msg, bgr_fg, bord, shad
                    )
                    txt = txt.split("\n")

                # show new messages bottom-left (heh)
                msg["txt"] = txt
                msg["px"] = bx
                msg["py"] = by + bh - msg["sy"] - nickh

                ta = hms(msg["t0"])
                tb = hms(next_msg["t0"] if next_msg else msg["t0"] + 10)

                rm = 0
                for m in vis:
                    m["py"] -= msg["sy"] + nickh
                    if m["py"] < by:
                        # debug('drop {} at {}'.format(hms(m["t0"]), ta))
                        rm += 1

                vis = vis[rm:] + [msg]

                if True:
                    # rely on squished font for linespacing reduction
                    txt = r"{{\pos({:.1f},{:.1f})}}".format(bx, by + bh)
                    for m in vis:
                        pad = ""
                        for ln in m["txt"]:
                            txt += pad + ln + r"\N{\r}"
                            pad = r"\h\h"

                    f.write(f"Dialogue: 0,{ta},{tb},a,,0,0,0,,{txt}\n".encode("utf-8"))
                else:
                    # verification, one ass entry for each line
                    for m in vis:
                        step = nickh
                        x = m["px"]
                        y = m["py"]
                        for ln in m["txt"]:
                            txt = r"{{\pos({:.1f},{:.1f})}}{}".format(x, y, ln)
                            x = m["px"] + 8
                            y += step
                            step = m["sy"] / (len(m["txt"]) - 1)
                            txt = f"Dialogue: 0,{ta},{tb},a,,0,0,0,,{txt}\n"
                            f.write(txt.encode("utf-8"))

            else:
                txts, t0, w, h, msg_emotes = [
                    msg[x] for x in ["txt", "t0", "sx", "sy", "msg_emotes"]
                ]
                txt = "\\N".join(txts)

                lineh = z.emote_vsz[1]
                nickh = lineh * 0.6

                # ass linespacing is huge, compensate (wild guess btw)
                h += int(ar.sz * 0.25 * (len(txts) - 1) + 0.99 + nickh)

                # plus some horizontal margin between the messages
                w += 8

                shrimp_mul = 1
                if shrimp:
                    txt = f"{shrimp} {txt}"
                    shrimp_mul = 2
                    w += h * 4  # donation is not included, TODO maybe

                vip = False
                badges = msg.get("badges", [])
                if not set(badges).isdisjoint(["Moderator", "Owner", "Verified"]):
                    bord = shad = 6
                    badge_sz = int(12 * ar.badge_sz)
                    txt = rf"{{\bord{badge_sz}\shad{shad}}}*{{\bord{bord}}}{txt}"
                    vip = True
                elif msg["uid"] in vips:
                    bord = shad = 4
                    badge_sz = int(8 * ar.badge_sz)
                    txt = rf"{{\bord{badge_sz}\shad{shad}}}_{{\bord{bord}}}{txt}"
                    vip = True

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
                if ymax < 1:
                    ymax = 1  # thx emotes

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

                if msg_emotes and (
                    ar.emote_fill or filled_emotes or ar.emote_sz > 1.01
                ):
                    msegs = segment_msg(txt, ar.emote_fill, filled_emotes)
                    txt = render_msegs(
                        msegs, ar.sz, ar.sz * ar.emote_sz, bgr_msg, bgr_fg, bord, shad
                    )

                y = int(y)
                txt = rf"{{\move({vw:.1f},{y+h:.1f},{-w:.1f},{y+h:.1f})\3c&H{bgr_nick}&}}{txt}{{\fscx40\fscy40\bord1}}\N{nick}"

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

                if shrimp or vip:
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

    if ar.emote_font and ar.emote_install:
        fontdir = None
        if ar.emote_install_dir:
            fontdir = ar.emote_install_dir
        else:
            if WINDOWS:
                mpv_dir = os.path.expandvars(r"%appdata%/mpv")
            else:
                mpv_dir = os.path.expanduser(r"~/.config/mpv")

            if not os.path.exists(mpv_dir):
                warn(f"to enable emote font installation, create directory {mpv_dir}/")
            else:
                fontdir = os.path.join(mpv_dir, "fonts")

        if fontdir:
            if os.path.exists(fontdir) and not os.path.isdir(fontdir):
                error(f"Requested font installation, but {fontdir} is not a directory")
                fontdir = None
            elif not os.path.exists(fontdir):
                os.mkdir(fontdir)

        if fontdir:
            shutil.copy2(font_fn, fontdir)
            info(f"emote font installed to {fontdir}")
            if ar.cleanup and not ar.embed_files:
                os.remove(font_fn)

    if ar.embed_files and not media_fn:
        error("you requested --embed_files but the media file could not be located")
    elif ar.embed_files:
        split = media_fn.rsplit(".", 1)
        merged_fn = split[0] + ".softchat-merged.mkv"
        info(f"Producing merged file {merged_fn}.")

        # fmt: off
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-i", media_fn,
            "-i", out_fn,
            "-map", "0:v",
            "-map", "0:a",
            "-map", "1",
            # Subtitles will still run longer than the video due to in-progress
            # animations past the end of the video, but only about 10 seconds
            # unless there's a poorly timed superchat.
            "-t", str(v_dur),
            "-codec", "copy",
            "-disposition:s:0", "default",
        ]

        if ar.emote_font:
            cmd.extend([
                "-attach", font_fn,
                "-metadata:s:t", "mimetype=application/x-truetype-font",
            ])
        # fmt: on

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

    # pprint(msgs[-5:])
    t1_main = time.time()
    info(f"finished in {t1_main-t0_main:.2f} sec")


def gen_msgs(jd, vw, bw, ar, emote_shortcuts, have_fugashi):
    j = ar.j
    if j == 0:
        j = os.cpu_count()

    initargs = [gen_msg_thr, ar, vw, bw, emote_shortcuts, have_fugashi]

    with multiprocessing.Pool(
        j, initializer=gen_msg_initializer, initargs=initargs
    ) as pool:
        # Cannot return the generator directly, since the context manager will close the pool
        # 100 was picked experimentally and seems to perform well for both 4c8t and 16c/32t.
        for x in pool.imap(gen_msg_thr, enumerate(jd), 100):
            if x:
                yield x


if __name__ == "__main__":
    main()


r"""

===[ side-by-side with kanji transcription ]===========================

ytdl-tui.py https://www.youtube.com/watch?v=7LXgVlrfsWw

softchat.py ..\yt\ars-37-minecraft-3.json -b 360x500+24+40 --sz 26 --emote_font --emote_sz 1.8 && copy /y ..\yt\ars-37-minecraft-3.ass ..\yt\ars-37-minecraft-3.1.ass

softchat.py ..\yt\ars-37-minecraft-3.json -b 360x500+300+40 --sz 26 --emote_font --emote_sz 1.8 --kana && copy /y ..\yt\ars-37-minecraft-3.ass ..\yt\ars-37-minecraft-3.2.ass

(head -n 22 ars-37-minecraft-3.1.ass ; (tail -n +23 ars-37-minecraft-3.1.ass; tail -n +23 ars-37-minecraft-3.2.ass) | sort) > ars-37-minecraft-3.ass

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
