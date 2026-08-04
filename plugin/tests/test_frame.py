from casino import frame


def test_render_pairs_rows_and_resets():
    grid = [[(255, 0, 0)], [(0, 0, 255)]]  # one column, two pixel rows
    out = frame.render(grid)
    assert out.count("▀") == 1          # one half-block cell
    assert "38;2;255;0;0" in out             # top pixel as foreground
    assert "48;2;0;0;255" in out             # bottom pixel as background
    assert out.endswith("\x1b[0m")


def test_blank_and_stamp():
    g = frame.blank(3, 3, fill=None)
    frame.stamp(g, ["111", "010", "111"], 0, 0, (9, 9, 9))
    assert g[0][0] == (9, 9, 9)
    assert g[1][0] is None                   # a "0" cell stays transparent


def test_hconcat_widths():
    a = frame.blank(2, 2, (1, 1, 1))
    b = frame.blank(3, 2, (2, 2, 2))
    joined = frame.hconcat([a, b], gap=1, bg=None)
    assert len(joined[0]) == 2 + 1 + 3


def test_scale_doubles():
    g = [[(1, 2, 3)]]
    big = frame.scale(g, 2)
    assert len(big) == 2 and len(big[0]) == 2
    assert big[1][1] == (1, 2, 3)
