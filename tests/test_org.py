"""조직 분류 — 층으로 좁혀 고르기 (대분류 → 중분류 → 소분류).

규칙이 틀리면 표가 조용히 다른 것을 센다. 화면만 봐서는 안 보이므로 streamlit 없이 여기서 잰다.
"""


def _table():
    from ragdiag.org import parse_classification

    return parse_classification({"dept_classes": [
        {"id": 1, "name": "경영지원본부", "subclasses": [
            {"name": "인사", "items": ["인사팀", "인재개발팀"]},
            {"name": "재무", "items": ["회계팀"]}]},
        {"id": 2, "name": "기술본부", "subclasses": [
            {"name": "플랫폼", "items": ["플랫폼팀"]}]},
    ]})


SEEN = ["인사팀", "인재개발팀", "회계팀", "플랫폼팀", "어디에도없는팀"]


def test_tree_holds_only_what_the_log_actually_has():
    """체계 전부를 늘어놓으면 이 데이터에 없는 팀을 고르고 0건을 보게 된다."""
    from ragdiag.org import UNMAPPED, observed_tree

    tree = observed_tree(_table(), ["인사팀", "어디에도없는팀"])
    assert set(tree) == {"경영지원본부", UNMAPPED}
    assert tree["경영지원본부"] == {"인사": ["인사팀"]}, tree
    # 체계에 없는 값을 버리면 "그 조직은 문제가 없다"로 잘못 읽힌다.
    assert tree[UNMAPPED] == {UNMAPPED: ["어디에도없는팀"]}


def test_lower_levels_are_bound_to_the_upper_choice():
    from ragdiag.org import level_options, observed_tree

    tree = observed_tree(_table(), SEEN)

    majors, middles, items = level_options(tree, [], [])
    assert middles == sorted(["인사", "재무", "플랫폼", "(미분류)"])

    _, middles, items = level_options(tree, ["경영지원본부"], [])
    assert middles == ["인사", "재무"], "다른 본부의 중분류가 보인다"
    assert "플랫폼팀" not in items

    _, _, items = level_options(tree, ["경영지원본부"], ["인사"])
    assert items == ["인사팀", "인재개발팀"], items


def test_nothing_chosen_means_everything():
    """빈 선택을 '해당 없음'으로 다루면 첫 화면이 0건이 된다."""
    from ragdiag.org import allowed_values, observed_tree

    tree = observed_tree(_table(), SEEN)
    assert allowed_values(tree, [], [], []) is None


def test_choosing_only_a_major_keeps_everything_under_it():
    from ragdiag.org import allowed_values, observed_tree

    tree = observed_tree(_table(), SEEN)
    assert allowed_values(tree, ["경영지원본부"], [], []) == {
        "인사팀", "인재개발팀", "회계팀"}


def test_each_level_narrows_further():
    from ragdiag.org import allowed_values, observed_tree

    tree = observed_tree(_table(), SEEN)
    assert allowed_values(tree, ["경영지원본부"], ["인사"], []) == {"인사팀", "인재개발팀"}
    assert allowed_values(tree, ["경영지원본부"], ["인사"], ["인사팀"]) == {"인사팀"}


def test_several_can_be_chosen_at_every_level():
    from ragdiag.org import allowed_values, observed_tree

    tree = observed_tree(_table(), SEEN)
    assert allowed_values(tree, ["경영지원본부", "기술본부"], [], []) == {
        "인사팀", "인재개발팀", "회계팀", "플랫폼팀"}
    assert allowed_values(tree, [], ["인사", "플랫폼"], []) == {
        "인사팀", "인재개발팀", "플랫폼팀"}


def test_unmapped_can_be_looked_at_on_purpose():
    """체계에 없는 값도 골라서 볼 수 있어야 한다. 무엇이 안 붙었는지가 정보다."""
    from ragdiag.org import UNMAPPED, allowed_values, observed_tree

    tree = observed_tree(_table(), SEEN)
    assert allowed_values(tree, [UNMAPPED], [], []) == {"어디에도없는팀"}
