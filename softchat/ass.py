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


def segment_msg(txt, fill_all, fill_list):
    ret = []
    plv = 0
    buf = ""
    for c, u in list(zip(txt, [ord(x) for x in txt])) + [[None, 0]]:
        if u >= 0xE000 and u <= 0xF8FF:
            if fill_all or c in fill_list:
                nlv = 2
            else:
                nlv = 1
        else:
            nlv = 0

        if plv == nlv and c:
            buf += c
        else:
            if buf:
                ret.append([plv, buf])
            buf = c

        plv = nlv

    return ret


def render_msegs(msegs, tsz, esz, bg, fg, bord, shad):
    ret = ""
    plv = 0
    for lv, txt in msegs + [[0, ""]]:
        cmd = ""

        if plv < 1 and lv > 0:
            cmd += f"\\fs{esz:.1f}"

        if plv < 2 and lv > 1:
            # compensate the 1100 padding in fff by subtracting a constant,
            scx = int(len(txt) * 110) - 10  # ~109 otherwise

            # and bump this a bit to shift some of the padding to the left
            fsp = esz / 0.9111  # 0.9091

            cmd += f"\\c&H{bg}\\fscx{scx:.2f}\\fsp-{fsp:.2f}}}\ue000{{\\fscx100\\fsp0\\c&H{fg}\\1a&H00&\\bord1\\shad0"

        if plv > 1 and lv < 2:
            cmd += f"\\bord{bord}\\shad{shad}"

        if plv > 0 and lv < 1:
            cmd += f"\\fs{tsz:.1f}"

        plv = lv
        if cmd:
            ret += f"{{{cmd}}}{txt}"
        else:
            ret += txt

    return ret
