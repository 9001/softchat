import pytest
from .ass import segment_msg, render_msegs


tx = "a"
em = "\ue000"
fi = "\ue001"
atx = [0, tx]
aem = [1, em]
afi = [2, fi]


def seg(tx):
    return segment_msg(tx, False, ["\ue001"])


def rend(sl):
    return render_msegs(sl, 3, 5, "", "", 7, 9)


def test_segment_msg():
    assert seg(tx) == [atx]
    assert seg(tx) == [atx]
    assert seg(em) == [aem]
    assert seg(fi) == [afi]
    assert seg(tx + em) == [atx, aem]
    assert seg(em + fi) == [aem, afi]
    assert seg(tx + fi) == [atx, afi]
    assert seg(tx + tx + em) == [[0, tx + tx], aem]
    assert seg(tx + fi + fi) == [atx, [2, fi + fi]]


def test_render_msegs():
    assert rend([atx]) == "a"
    assert rend([aem]) == f"{{\\fs5}}{em}{{\\fs3}}"
    r = rend([afi])
    print(r)
    assert len(r.split(fi)) == 2
    assert len(r.split(r"\fs5")) == 2
    assert len(r.split(r"\fs3")) == 2
    assert len(r.split(r"\fscx")) == 3
