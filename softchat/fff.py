# fff = fontforge fix (meaning of last f is disputed)

import os
import sys
import json
import fontforge

from .util import debug, warn, init_logger


def gen_fonts(emotes, font_fn, font_name):
    shortcuts = dict()
    # Start of one of the private use areas.
    # The other two don't work with embedded subtitle files for some reason.
    point = 0xE000
    font = fontforge.font()
    font.familyname = font_name

    for e in emotes.values():
        g = font.createChar(point)
        raster_fn = e["filename"]
        if not os.path.exists(raster_fn):
            raise Exception("not found: " + raster_fn)

        debug("src: " + raster_fn)
        g.importOutlines(raster_fn)
        g.autoTrace()
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
