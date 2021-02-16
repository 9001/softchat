# fff = fontforge fix (meaning of last f is disputed)

import os
import sys
import json
import tempfile
import fontforge

from .util import debug, warn, init_logger


def gen_fonts(emotes, font_fn, font_name, dont_write):
    shortcuts = dict()
    # Start of one of the private use areas.
    # The other two don't work with embedded subtitle files for some reason.
    point = 0xE000
    font = fontforge.font()
    font.familyname = font_name

    # the first point is reserved for a solid black box
    # which helps determine the visual size of emotes
    # and also serves as the background for --emote_fill
    svg_txt = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="1000" height="1000" viewBox="0 0 1000 1000" xmlns="http://www.w3.org/2000/svg">
<g><path d="M 0,0 V 1000 H 1000 V 0 Z"
    style="fill:#000000;fill-opacity:1;stroke:none;stroke-width:0px" /></g></svg>
"""

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="softchat-", suffix=".svg", delete=False
    ) as f:
        blk_svg = f.name
        f.write(svg_txt)

    g = font.createChar(point)
    g.importOutlines(blk_svg)
    g.width = 1100
    point += 1

    filled_emotes = []
    for e in emotes.values():
        g = font.createChar(point)
        src_fn = e["filename"]
        if not os.path.exists(src_fn):
            raise Exception("not found: " + src_fn)

        if not dont_write:
            debug("src: " + src_fn)
            g.importOutlines(src_fn)
            if not src_fn.endswith(".svg"):
                g.autoTrace()

        # Lie about their width as a hacky way to give them some breathing room.
        # Could do better, maybe will, but good enough for now.
        g.width = 1100

        for s in e["shortcuts"]:
            if s in shortcuts:
                warn("Found duplicate emote shortcut " + s)

            ch = chr(point)
            shortcuts[s] = ch
            if e["fill"]:
                filled_emotes.append(ch)

        point += 1

    if not dont_write:
        font.correctDirection()
        font.generate(font_fn)

    os.unlink(blk_svg)
    return [shortcuts, filled_emotes]


def main():
    tf_path = sys.argv[1]
    with open(tf_path, "r", encoding="utf-8") as f:
        args = f.read()

    args = json.loads(args)
    ret = gen_fonts(*args)
    ret = json.dumps(ret)

    with open(tf_path, "w", encoding="utf-8") as f:
        f.write(ret)


if __name__ == "__main__":
    init_logger(True)
    main()
