from unittest.mock import Mock

import pytest

import _asana


# Rich-text guard (tag table: references/rich-text.md).
def test_wrap_body_accepts_verified_rich_text():
    html = ("<h1>T</h1><h2>S</h2>x <strong>b</strong> <code>c</code> <a href=\"https://e.x\">l</a>"
            "<hr/><ul><li>a <em>b</em><ol><li>c</li></ol></li></ul><blockquote>q</blockquote>"
            "<pre>a &lt; b</pre><table><tr><td><strong>A</strong></td></tr></table> a < b")
    assert _asana.wrap_body(html) == f"<body>{html}</body>"


@pytest.mark.parametrize("html", ["<p>para</p>", "one<br/>two", "<table><tr><th>H</th></tr></table>",
                                  '<img src="x.png"/>', "<div>d</div>"])
def test_wrap_body_refuses_tags_asana_rejects(html):
    with pytest.raises(ValueError, match="unsupported Asana rich-text tag"):
        _asana.wrap_body(html)


def test_extract_task_gid_from_project_scoped_url():
    assert _asana.extract_task_gid(
        "https://app.asana.com/0/1200000000000500/1200000000000501/f"
    ) == "1200000000000501"


def test_extract_task_gid_from_zero_project_url():
    assert _asana.extract_task_gid(
        "https://app.asana.com/0/0/1200000000000501/f"
    ) == "1200000000000501"


def test_paginate_follows_offsets_and_concatenates_rows(monkeypatch):
    api_request = Mock(
        side_effect=[
            {"data": [{"gid": "1"}], "next_page": {"offset": "next-offset"}},
            {"data": [{"gid": "2"}]},
        ]
    )
    monkeypatch.setattr(_asana, "request", api_request)

    assert _asana.paginate("/things", "token", {"workspace": "workspace"}) == [
        {"gid": "1"},
        {"gid": "2"},
    ]
    assert api_request.call_args_list == [
        (("GET", "/things", "token"), {"params": {"workspace": "workspace", "limit": 100}}),
        (
            ("GET", "/things", "token"),
            {"params": {"workspace": "workspace", "limit": 100, "offset": "next-offset"}},
        ),
    ]


def test_mentioned_user_gids_keeps_users_in_order_without_repeats():
    body = ('<a data-asana-gid="2"/> and <a data-asana-gid="1"/> '
            "and <a data-asana-gid='2'/> again")
    assert _asana.mentioned_user_gids(body) == ["2", "1"]


def test_mentioned_user_gids_skips_task_and_project_links():
    body = ('<a href="x" data-asana-gid="1" data-asana-type="user">@A</a> '
            '<a data-asana-type="task" data-asana-gid="2">T</a> '
            '<a data-asana-gid="3" data-asana-type="project">P</a>')
    assert _asana.mentioned_user_gids(body) == ["1"]


def test_mentioned_user_gids_ignores_plain_links_and_empty_bodies():
    assert _asana.mentioned_user_gids('<a href="https://example.com">l</a>') == []
    assert _asana.mentioned_user_gids("") == []
    assert _asana.mentioned_user_gids(None) == []
