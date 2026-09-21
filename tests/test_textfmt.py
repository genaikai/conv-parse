"""터미널 표 정렬 — 한글은 두 칸이다."""

from ragdiag.textfmt import pad, text_width


def test_pad_accounts_for_wide_characters():
    assert text_width("해외영업팀") == 10
    assert text_width(pad("해외영업팀", 14)) == 14
    assert text_width(pad("abc", 14, right=True)) == 14
    assert pad("abc", 2) == "abc", "폭보다 길면 자르지 않는다"
