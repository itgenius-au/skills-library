"""attach_file.py: the three comment shapes, the refusals, the stop block and resume.

The Asana calls (token, list, upload, post) are replaced by a fake task held in
memory, so nothing leaves the machine. How Asana renders each comment is not
provable here; that is checked by eye on a sandbox task.
"""
import email.parser
import io
import re
import urllib.error

import pytest

import attach_file as af

TASK = "1200000000000300"


class FakeTask:
    """A task's attachments and comments, in memory, standing in for Asana."""

    def __init__(self, attachments=(), fail_upload=None, fail_comment=False, size_override=None,
                 lost_upload=None, lost_comment=False, other_comment_appears=False,
                 fail_list_on_call=None, fail_upload_code=400, fail_comment_code=400,
                 lost_error=None, stories=(), comment_reply=None):
        self.attachments = [dict(a) for a in attachments]
        self.uploaded = []          # file names, in upload order
        self.stories = []           # comment HTML as posted
        self.fail_upload = fail_upload
        self.fail_comment = fail_comment
        self.size_override = size_override or {}
        self.lost_upload = lost_upload        # this name lands, but the response is lost
        self.lost_comment = lost_comment      # the comment lands, but the response is lost
        self.other_comment_appears = other_comment_appears
        self.fail_list_on_call = fail_list_on_call  # the Nth list_attachments call raises
        self.fail_upload_code = fail_upload_code    # 4xx = refused; 5xx = may have landed
        self.fail_comment_code = fail_comment_code
        self.lost_error = lost_error or urllib.error.URLError("connection reset")
        self.story_rows = [dict(r) for r in stories]
        self.comment_reply = comment_reply          # override the POST /stories reply
        self.list_calls = 0
        self._next = 1200000000009001
        self.followed = []          # (story gid, comment HTML) per follow_mentions call

    def install(self, monkeypatch, agent=True):
        monkeypatch.setattr(af, "get_token", lambda: "t")
        if agent:
            # The fake token "t" is an agent account: no author line, no lookup.
            monkeypatch.setattr(af._asana, "_AUTHOR_CACHE", {"t": ""})
        monkeypatch.setattr(af, "list_attachments", self.list_attachments)
        monkeypatch.setattr(af, "upload", self.upload)
        monkeypatch.setattr(af, "post_story", self.post_story)
        monkeypatch.setattr(af, "list_stories", self.list_stories)
        monkeypatch.setattr(af, "my_user_gid", lambda token: "me")
        monkeypatch.setattr(af, "follow_mentions", self.follow_mentions)
        return self

    def follow_mentions(self, token, task, story_gid, comment_html):
        assert task == TASK
        self.followed.append((story_gid, comment_html))
        return []

    def list_attachments(self, token, task):
        assert task == TASK
        self.list_calls += 1
        if self.list_calls == self.fail_list_on_call:
            raise urllib.error.URLError("network down")
        return [dict(a) for a in self.attachments]

    def list_stories(self, token, task):
        return [dict(s) for s in self.story_rows]

    def upload(self, token, task, path):
        if path.name == self.fail_upload:
            raise urllib.error.HTTPError("u", self.fail_upload_code, "boom", {},
                                         io.BytesIO(b"server error"))
        gid = str(self._next)
        self._next += 1
        size = self.size_override.get(path.name, path.stat().st_size)
        self.attachments.append({"gid": gid, "name": path.name, "size": size,
                                 "permanent_url": f"https://app.asana.com/app/asana/-/get_asset?asset_id={gid}"})
        self.uploaded.append(path.name)
        if path.name == self.lost_upload:
            raise self.lost_error
        return {"gid": gid, "name": path.name}

    def post_story(self, token, task, comment_html):
        if self.other_comment_appears:
            self.story_rows.append({"gid": "555", "resource_subtype": "comment_added",
                                    "created_by": {"gid": "someone-else"},
                                    "text": self.other_comment_appears
                                    if isinstance(self.other_comment_appears, str)
                                    else "someone else's comment"})
        if self.fail_comment:
            raise urllib.error.HTTPError("u", self.fail_comment_code, "down", {},
                                         io.BytesIO(b""))
        self.stories.append(comment_html)
        # Stored the way Asana stores comments:
        # html_text keeps the markup; text puts each list item on its own line.
        self.story_rows.append({"gid": "777", "resource_subtype": "comment_added",
                                "created_by": {"gid": "me"},
                                "html_text": f"<body>{comment_html}</body>",
                                "text": re.sub(r"<[^>]+>", "",
                                               comment_html.replace("<li>", "\n    "))})
        if self.lost_comment:
            raise self.lost_error
        return self.comment_reply if self.comment_reply is not None else {"gid": "777"}


def make(tmp_path, *specs):
    out = []
    for name, content in specs:
        p = tmp_path / name
        p.write_bytes(content)
        out.append(str(p))
    return out


def run(*argv):
    return af.main([TASK, *argv])


def file_args(paths):
    out = []
    for p in paths:
        out += ["--file", p]
    return out


# --- the upload request ------------------------------------------------------

def test_multipart_carries_the_task_and_the_exact_file_bytes():
    content = b"line one\r\n--not-a-boundary\r\n\x00\xffbinary"
    body, header = af.encode_multipart({"parent": TASK}, "file", "notes.md", content,
                                       "text/markdown", boundary="b0undary")
    msg = email.parser.BytesParser().parsebytes(
        f"Content-Type: {header}\r\n\r\n".encode() + body)
    parts = {p.get_param("name", header="content-disposition"): p for p in msg.get_payload()}
    assert parts["parent"].get_payload() == TASK
    assert parts["file"].get_filename() == "notes.md"
    assert parts["file"].get_payload(decode=True) == content


# --- the three shapes --------------------------------------------------------

def test_link_comment_links_its_one_file(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("qa-screenshot.png", b"\x89PNG"))
    assert run(*file_args(f), "--comment", "link") == 0
    gid = fake.attachments[0]["gid"]
    assert fake.stories == [f'<a href="https://app.asana.com/app/asana/-/get_asset?asset_id={gid}">'
                            "qa-screenshot.png</a>"]


def test_name_comment_names_every_file_tags_everyone_and_links_none(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("plan.md", b"p"), ("R&D notes <v2>.md", b"r"))
    body = tmp_path / "body.html"
    body.write_text("Written by Claude. Hand-over for the report.")
    assert run(*file_args(f), "--comment", "name", "--body-file", str(body),
               "--mention", "1200000000000401", "--mention", "1200000000000402") == 0
    [comment] = fake.stories
    assert "Hand-over for the report." in comment
    assert '<a data-asana-gid="1200000000000401"/>' in comment
    assert '<a data-asana-gid="1200000000000402"/>' in comment
    listed = re.findall(r"<li><code>(.*?)</code></li>", comment)
    assert listed == ["plan.md", "R&amp;D notes &lt;v2&gt;.md"]
    assert "href" not in comment
    attachment_gids = {a["gid"] for a in fake.attachments}
    assert not any(g in comment for g in attachment_gids)
    # Everyone tagged is made a follower, from the comment that posted.
    assert fake.followed == [("777", comment)]


def test_no_follow_leaves_followers_alone(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("plan.md", b"p"))
    assert run(*file_args(f), "--comment", "name", "--mention", "1200000000000401",
               "--no-follow") == 0
    assert len(fake.stories) == 1
    assert fake.followed == []


def test_comment_without_mentions_makes_no_follow_call(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("qa-screenshot.png", b"\x89PNG"))
    assert run(*file_args(f), "--comment", "link") == 0
    assert fake.followed == []


def test_reconciled_comment_still_follows_the_mentions(tmp_path, monkeypatch):
    fake = FakeTask(lost_comment=True).install(monkeypatch)
    f = make(tmp_path, ("plan.md", b"p"))
    assert run(*file_args(f), "--comment", "name", "--mention", "1200000000000401") == 0
    assert [gid for gid, _ in fake.followed] == ["777"]


def test_resume_command_keeps_no_follow(tmp_path, monkeypatch, capsys):
    FakeTask(fail_comment=True).install(monkeypatch)
    f = make(tmp_path, ("plan.md", b"p"))
    assert run(*file_args(f), "--comment", "name", "--mention", "1200000000000401",
               "--no-follow") == 4
    assert "--no-follow" in capsys.readouterr().out


def test_none_posts_no_comment(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("claims-1200000000000403-2026-10-01.md", b"c"))
    assert run(*file_args(f), "--comment", "none") == 0
    assert fake.uploaded == ["claims-1200000000000403-2026-10-01.md"]
    assert fake.stories == []


def test_dry_run_sends_nothing_and_shows_the_comment(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(af, "get_token", lambda: pytest.fail("dry run fetched a token"))
    f = make(tmp_path, ("plan.md", b"p"))
    assert run(*file_args(f), "--comment", "name", "--mention", "1200000000000401",
               "--dry-run") == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "<li><code>plan.md</code></li>" in out
    assert "Will add as followers (after the post, users only): 1200000000000401" in out


# --- refusals before anything is sent -----------------------------------------

def no_network(monkeypatch):
    monkeypatch.setattr(af, "get_token", lambda: pytest.fail("a refusal reached the network"))


@pytest.mark.parametrize("name", [".env", "service-key.json", "deploy.pem", "aws_credentials.txt"])
def test_credential_looking_names_are_refused(tmp_path, monkeypatch, name):
    no_network(monkeypatch)
    f = make(tmp_path, (name, b"x"))
    assert run(*file_args(f), "--comment", "none") == 4


def test_oversize_is_refused(tmp_path, monkeypatch):
    no_network(monkeypatch)
    monkeypatch.setattr(af, "MAX_BYTES", 3)
    f = make(tmp_path, ("big.log", b"1234"))
    assert run(*file_args(f), "--comment", "none") == 4


def test_link_with_two_files_is_refused(tmp_path, monkeypatch):
    no_network(monkeypatch)
    f = make(tmp_path, ("a.png", b"a"), ("b.png", b"b"))
    assert run(*file_args(f), "--comment", "link") == 4


def test_none_with_a_mention_is_refused(tmp_path, monkeypatch):
    no_network(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "none", "--mention", "1200000000000401") == 4


def test_same_name_twice_is_refused(tmp_path, monkeypatch):
    no_network(monkeypatch)
    (tmp_path / "x").mkdir()
    f = make(tmp_path, ("a.md", b"a")) + make(tmp_path / "x", ("a.md", b"b"))
    assert run(*file_args(f), "--comment", "name") == 4


def test_body_with_a_tag_asana_rejects_is_refused(tmp_path, monkeypatch):
    no_network(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    body = tmp_path / "body.html"
    body.write_text("<p>para</p>")
    assert run(*file_args(f), "--comment", "name", "--body-file", str(body)) == 4


# --- duplicates and stops -----------------------------------------------------

def test_a_name_already_on_the_task_uploads_nothing(tmp_path, monkeypatch):
    fake = FakeTask(attachments=[{"gid": "1", "name": "b.md", "size": 1}]).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"), ("b.md", b"b"))
    assert run(*file_args(f), "--comment", "name") == 3
    assert fake.uploaded == [] and fake.stories == []


def test_failed_upload_stops_with_what_landed_and_a_resume_command(tmp_path, monkeypatch, capsys):
    fake = FakeTask(fail_upload="b.md").install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"), ("b.md", b"b"), ("c.md", b"c"))
    assert run(*file_args(f), "--comment", "name", "--mention", "1200000000000401") == 4
    out = capsys.readouterr().out
    assert fake.uploaded == ["a.md"]          # c.md never tried
    assert fake.stories == []                 # no comment claiming files that aren't there
    assert "Landed:        a.md (1200000000009001)" in out
    assert "Not uploaded:  b.md, c.md" in out
    assert "Comment:       not posted" in out
    resume = out.split("Resume with:", 1)[1].splitlines()[0]
    assert "--resume 1200000000009001" in resume
    assert "--mention 1200000000000401" in resume and "--comment name" in resume


def test_comment_failure_after_uploads_stops_with_every_file_landed(tmp_path, monkeypatch, capsys):
    fake = FakeTask(fail_comment=True).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"), ("b.md", b"b"))
    assert run(*file_args(f), "--comment", "name") == 4
    out = capsys.readouterr().out
    assert "Not uploaded:  none" in out and "Comment:       not posted" in out
    resume = out.split("Resume with:", 1)[1].splitlines()[0]
    assert "--resume 1200000000009001" in resume and "--resume 1200000000009002" in resume


def test_verify_catches_a_size_mismatch(tmp_path, monkeypatch, capsys):
    fake = FakeTask(size_override={"a.md": 999}).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 2
    assert fake.stories == []
    assert "VERIFY FAILED" in capsys.readouterr().out


def test_verify_catches_an_attachment_missing_after_upload(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    monkeypatch.setattr(fake, "attachments", [])
    real_upload = fake.upload

    def upload_then_vanish(token, task, path):
        out = real_upload(token, task, path)
        fake.attachments.clear()
        return out
    monkeypatch.setattr(af, "upload", upload_then_vanish)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "none") == 2


# --- resume -------------------------------------------------------------------

def test_resume_uploads_only_the_missing_files_and_comments_on_all(tmp_path, monkeypatch, capsys):
    f = make(tmp_path, ("a.md", b"a"), ("b.md", b"b"))
    landed = {"gid": "5", "name": "a.md", "size": 1, "permanent_url": "u5"}
    fake = FakeTask(attachments=[landed]).install(monkeypatch)
    assert run(*file_args(f), "--comment", "name", "--resume", "5") == 0
    assert fake.uploaded == ["b.md"]
    out = capsys.readouterr().out
    assert "Already attached (--resume) a.md  gid 5" in out and "\nAttached b.md" in out
    assert re.findall(r"<li><code>(.*?)</code></li>", fake.stories[0]) == ["a.md", "b.md"]


def test_resume_with_everything_landed_only_posts_the_comment(tmp_path, monkeypatch):
    f = make(tmp_path, ("a.md", b"a"))
    fake = FakeTask(attachments=[{"gid": "5", "name": "a.md", "size": 1,
                                  "permanent_url": "u5"}]).install(monkeypatch)
    assert run(*file_args(f), "--comment", "link", "--resume", "5") == 0
    assert fake.uploaded == []
    assert fake.stories == ['<a href="u5">a.md</a>']


def test_resume_gid_not_on_the_task_is_refused(tmp_path, monkeypatch, capsys):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name", "--resume", "5") == 4
    assert fake.uploaded == []
    assert "Do not rename" in capsys.readouterr().out


def test_resume_gid_that_matches_no_file_by_size_is_refused(tmp_path, monkeypatch):
    fake = FakeTask(attachments=[{"gid": "5", "name": "a.md", "size": 42}]).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name", "--resume", "5") == 4
    assert fake.uploaded == []


def test_resume_matches_by_gid_not_by_an_older_file_of_the_same_name(tmp_path, monkeypatch):
    """An older a.md (gid 4) is also on the task; only the resumed gid counts."""
    older = {"gid": "4", "name": "a.md", "size": 1, "permanent_url": "u4"}
    mine = {"gid": "5", "name": "a.md", "size": 1, "permanent_url": "u5"}
    fake = FakeTask(attachments=[older, mine]).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "link", "--resume", "5") == 0
    assert fake.stories == ['<a href="u5">a.md</a>']


# --- the token ----------------------------------------------------------------

def test_a_gcloud_sign_in_failure_stops_before_anything_is_sent(tmp_path, monkeypatch, capsys):
    import subprocess

    def expired():
        raise subprocess.CalledProcessError(1, ["gcloud"], stderr="Reauthentication failed.")
    monkeypatch.setattr(af._asana, "fetch_token", expired)
    monkeypatch.setattr(af, "list_attachments", lambda *a: pytest.fail("listed without a token"))
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "none") == 4
    assert "Nothing was sent" in capsys.readouterr().out


# --- a write whose response was lost ------------------------------------------

def test_an_upload_that_landed_but_lost_its_response_is_adopted_not_repeated(tmp_path, monkeypatch, capsys):
    fake = FakeTask(lost_upload="a.md").install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"), ("b.md", b"b"))
    assert run(*file_args(f), "--comment", "name") == 0
    assert fake.uploaded == ["a.md", "b.md"]          # each uploaded once
    assert len(fake.stories) == 1
    assert "Reconciled: a.md landed" in capsys.readouterr().out


def test_an_upload_response_without_a_gid_is_reconciled(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    real = fake.upload
    monkeypatch.setattr(af, "upload", lambda t, k, p: {k2: v for k2, v in real(t, k, p).items()
                                                        if k2 != "gid"})
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "none") == 0
    assert fake.uploaded == ["a.md"]


def test_a_failed_upload_that_cannot_be_checked_is_marked_uncertain(tmp_path, monkeypatch, capsys):
    # list call 1 = before uploading; call 2 = the reconcile after b.md fails
    fake = FakeTask(fail_upload="b.md", fail_list_on_call=2).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"), ("b.md", b"b"))
    assert run(*file_args(f), "--comment", "name") == 4
    out = capsys.readouterr().out
    assert "Uncertain:     b.md" in out
    assert "Not uploaded:  none" in out


def test_a_comment_that_landed_but_lost_its_response_is_not_posted_twice(tmp_path, monkeypatch, capsys):
    fake = FakeTask(lost_comment=True).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"), ("b.md", b"b"))
    assert run(*file_args(f), "--comment", "name") == 0
    assert len(fake.stories) == 1
    assert "Reconciled: the comment posted (777)" in capsys.readouterr().out


def test_a_failed_comment_with_an_unexplained_new_comment_is_unknown_not_absent(tmp_path, monkeypatch, capsys):
    FakeTask(fail_comment=True, other_comment_appears=True).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 4
    out = capsys.readouterr().out
    assert "Comment:       UNKNOWN" in out and "do not run it" in out


def test_a_failed_comment_with_no_new_comment_is_reported_not_posted(tmp_path, monkeypatch, capsys):
    FakeTask(fail_comment=True).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 4
    assert "Comment:       not posted" in capsys.readouterr().out


def test_the_printed_resume_command_finishes_the_job_without_duplicates(tmp_path, monkeypatch, capsys):
    """Replay the STOPPED block's command exactly as printed."""
    import shlex
    fake = FakeTask(fail_upload="b.md").install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"), ("b.md", b"b"))
    body = tmp_path / "body with space.html"
    body.write_text("Written by Claude. Hand-over.")
    assert run(*file_args(f), "--comment", "name", "--body-file", str(body),
               "--mention", "1200000000000401") == 4
    resume = capsys.readouterr().out.split("Resume with:", 1)[1].splitlines()[0]
    argv = shlex.split(resume)
    assert argv[0] == "python3"
    fake.fail_upload = None                     # Asana works again
    assert af.main(argv[2:]) == 0
    assert fake.uploaded == ["a.md", "b.md"]    # a.md not uploaded twice
    [comment] = fake.stories
    assert "Hand-over." in comment and '<a data-asana-gid="1200000000000401"/>' in comment
    assert re.findall(r"<li><code>(.*?)</code></li>", comment) == ["a.md", "b.md"]


def test_listing_the_attachments_fails_before_anything_is_sent(tmp_path, monkeypatch):
    fake = FakeTask(fail_list_on_call=1).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 4
    assert fake.uploaded == [] and fake.stories == []


def test_a_lost_upload_whose_size_does_not_match_is_uncertain_not_adopted(tmp_path, monkeypatch, capsys):
    FakeTask(lost_upload="a.md", size_override={"a.md": 999}).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 4
    out = capsys.readouterr().out
    assert "Uncertain:     a.md" in out and "Landed:        none" in out


# --- names, symlinks, empty files ---------------------------------------------

@pytest.mark.parametrize("name", ['say "hi".md', "two\nlines.md"])
def test_a_name_the_upload_would_change_is_refused(tmp_path, monkeypatch, name):
    no_network(monkeypatch)
    f = make(tmp_path, (name, b"x"))
    assert run(*file_args(f), "--comment", "none") == 4


def test_the_resume_command_keeps_a_symlink_s_own_name(tmp_path, monkeypatch, capsys):
    target = tmp_path / "source.md"
    target.write_bytes(b"s")
    link = tmp_path / "report.md"
    link.symlink_to(target)
    fake = FakeTask(fail_comment=True).install(monkeypatch)
    assert run("--file", str(link), "--comment", "name") == 4
    assert fake.uploaded == ["report.md"]
    resume = capsys.readouterr().out.split("Resume with:", 1)[1].splitlines()[0]
    assert str(link) in resume and str(target) not in resume


def test_an_empty_file_uploads_and_verifies(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("empty.log", b""))
    assert run(*file_args(f), "--comment", "none") == 0
    assert fake.attachments[0]["size"] == 0


def test_resume_accepts_an_empty_file_already_landed(tmp_path, monkeypatch):
    fake = FakeTask(attachments=[{"gid": "5", "name": "empty.log", "size": 0,
                                  "permanent_url": "u5"}]).install(monkeypatch)
    f = make(tmp_path, ("empty.log", b""))
    assert run(*file_args(f), "--comment", "link", "--resume", "5") == 0
    assert fake.uploaded == []


# --- the body file -------------------------------------------------------------

def test_a_body_already_wrapped_in_body_tags_keeps_everything_inside_one_body(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    body = tmp_path / "body.html"
    body.write_text("<body>Approved</body>")
    assert run(*file_args(f), "--comment", "name", "--body-file", str(body)) == 0
    [comment] = fake.stories
    assert "<body>" not in comment and comment.startswith("Approved")
    assert af.wrap_body(comment).count("<body>") == 1


def test_a_missing_body_file_is_bad_input_not_a_crash(tmp_path, monkeypatch):
    no_network(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name", "--body-file", str(tmp_path / "nope.html")) == 4


# --- the success report --------------------------------------------------------

def test_success_prints_the_comment_as_posted_with_the_real_link(tmp_path, monkeypatch, capsys):
    FakeTask().install(monkeypatch)
    f = make(tmp_path, ("shot.png", b"\x89PNG"))
    assert run(*file_args(f), "--comment", "link") == 0
    report = capsys.readouterr().out.split("Posted story 777:", 1)[1]
    assert "get_asset?asset_id=1200000000009001" in report
    assert af.LINK_PLACEHOLDER not in report


def test_the_link_falls_back_to_the_asset_url_shape_when_permanent_url_is_missing(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    real = fake.upload

    def upload_without_url(token, task, path):
        out = real(token, task, path)
        fake.attachments[-1].pop("permanent_url")
        return out
    monkeypatch.setattr(af, "upload", upload_without_url)
    f = make(tmp_path, ("shot.png", b"\x89PNG"))
    assert run(*file_args(f), "--comment", "link") == 0
    assert fake.stories == ['<a href="https://app.asana.com/app/asana/-/get_asset?asset_id='
                            '1200000000009001">shot.png</a>']


def test_none_with_a_body_is_refused(tmp_path, monkeypatch):
    no_network(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    body = tmp_path / "body.html"
    body.write_text("hi")
    assert run(*file_args(f), "--comment", "none", "--body-file", str(body)) == 4


# --- attribution, absence, cut-off responses -----------------------------------

def test_someone_else_s_comment_naming_the_files_is_not_adopted(tmp_path, monkeypatch, capsys):
    fake = FakeTask(fail_comment=True, fail_comment_code=503,
                    other_comment_appears="Where is a.md?").install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 4
    out = capsys.readouterr().out
    assert "Reconciled" not in out and "Comment:       UNKNOWN" in out
    assert fake.stories == []


def test_a_5xx_comment_failure_with_nothing_new_is_unknown_not_absent(tmp_path, monkeypatch, capsys):
    FakeTask(fail_comment=True, fail_comment_code=503).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 4
    assert "Comment:       UNKNOWN" in capsys.readouterr().out


def test_a_5xx_upload_failure_with_nothing_new_is_uncertain_not_absent(tmp_path, monkeypatch, capsys):
    FakeTask(fail_upload="a.md", fail_upload_code=500).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 4
    out = capsys.readouterr().out
    assert "Uncertain:     a.md" in out and "Not uploaded:  none" in out


def test_a_comment_whose_response_is_cut_off_is_reconciled(tmp_path, monkeypatch, capsys):
    import http.client
    fake = FakeTask(lost_comment=True,
                    lost_error=http.client.IncompleteRead(b"{", 40)).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 0
    assert len(fake.stories) == 1
    assert "Reconciled: the comment posted" in capsys.readouterr().out


def test_an_upload_whose_response_is_cut_off_is_reconciled(tmp_path, monkeypatch):
    import http.client
    fake = FakeTask(lost_upload="a.md",
                    lost_error=http.client.IncompleteRead(b"{", 40)).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "none") == 0
    assert fake.uploaded == ["a.md"]


def test_a_comment_reply_without_a_story_id_is_reconciled(tmp_path, monkeypatch, capsys):
    fake = FakeTask(comment_reply={}).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 0
    assert len(fake.stories) == 1
    assert "Reconciled: the comment posted (777)" in capsys.readouterr().out


def test_a_matching_comment_that_existed_before_the_post_is_not_adopted(tmp_path, monkeypatch, capsys):
    earlier = {"gid": "100", "resource_subtype": "comment_added", "created_by": {"gid": "me"},
               "text": "a.md"}
    FakeTask(stories=[earlier], fail_comment=True, fail_comment_code=503).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 4
    out = capsys.readouterr().out
    assert "Reconciled" not in out and "Comment:       UNKNOWN" in out


def test_reading_the_comments_before_posting_fails_stops_with_the_ledger(tmp_path, monkeypatch, capsys):
    fake = FakeTask().install(monkeypatch)
    monkeypatch.setattr(af, "list_stories", lambda *a: (_ for _ in ()).throw(
        urllib.error.URLError("down")))
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 4
    out = capsys.readouterr().out
    assert "Landed:        a.md (1200000000009001)" in out and "Comment:       not posted" in out
    assert fake.stories == []


def test_a_name_with_a_carriage_return_is_refused(tmp_path, monkeypatch):
    no_network(monkeypatch)
    f = make(tmp_path, ("cr\rname.md", b"x"))
    assert run(*file_args(f), "--comment", "none") == 4


def test_an_undecodable_body_file_is_bad_input(tmp_path, monkeypatch):
    no_network(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    body = tmp_path / "body.html"
    body.write_bytes(b"\xff\xfe\xfa")
    assert run(*file_args(f), "--comment", "name", "--body-file", str(body)) == 4


def test_an_unreadable_file_stops_at_the_preview(tmp_path, monkeypatch):
    import os
    no_network(monkeypatch)
    f = make(tmp_path, ("locked.md", b"secret-ish"))
    os.chmod(f[0], 0)
    try:
        if os.access(f[0], os.R_OK):
            pytest.skip("running with privileges that ignore file modes")
        assert run(*file_args(f), "--comment", "none") == 4
    finally:
        os.chmod(f[0], 0o600)


def test_story_names_reads_code_items_and_link_labels_exactly():
    assert af.story_names({"text": "", "html_text":
                           '<body><ul><li><code>R&amp;D.md</code></li></ul>'
                           '<a href="u" data-asana-type="attachment">shot.png</a></body>'}) \
        == {"R&D.md", "shot.png"}


LIVE_LINK_STORY = {   # a link comment, in the shape Asana returns it
    "gid": "990", "resource_subtype": "comment_added", "created_by": {"gid": "me"},
    "text": "Written by Claude. Example of the link shape (plain web link to the "
            "file). Safe to ignore.\nhttps://app.asana.com/app/asana/-/get_asset?asset_id=1200000000000404",
    "html_text": '<body>Written by Claude. Example of the link shape (plain web link '
                 'to the file). Safe to ignore.\n<a href="https://app.asana.com/app/asana/-/get_asset'
                 '?asset_id=1200000000000404" data-asana-gid="1200000000000404" data-asana-accessible='
                 '"true" data-asana-type="attachment" data-asana-dynamic="true">'
                 'qa-screenshot-probe-2026-10-01.png</a></body>'}


@pytest.mark.parametrize("name, adopted", [
    ("qa-screenshot-probe-2026-10-01.png", True),   # the real label
    ("attachment", False),                          # only in data-asana-type
    ("body", False),                                # only in the markup
    ("screenshot-probe-2026-10-01.png", False),     # a suffix of the real name
    ("get_asset", False),                           # only in the URL
])
def test_the_comment_check_matches_whole_names_not_markup_urls_or_parts(name, adopted):
    """Each false case would be adopted by a substring check."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(af, "list_stories", lambda t, k: [dict(LIVE_LINK_STORY)])
        mp.setattr(af, "my_user_gid", lambda t: "me")
        state, _ = af.reconcile_comment("t", TASK, set(), [name], was_refused=False)
    assert (state == "posted") is adopted


def test_a_lost_link_comment_is_adopted_though_its_plain_text_shows_only_the_url(
        tmp_path, monkeypatch, capsys):
    """The shape Asana stores a link comment in."""
    fake = FakeTask().install(monkeypatch)

    def post_as_asana_stores_it_then_lose_the_reply(token, task, comment_html):
        gid = fake.attachments[-1]["gid"]
        url = f"https://app.asana.com/app/asana/-/get_asset?asset_id={gid}"
        fake.story_rows.append({
            "gid": "990", "resource_subtype": "comment_added", "created_by": {"gid": "me"},
            "text": f"Written by Claude.\n{url}",
            "html_text": f'<body>Written by Claude.\n<a href="{url}" data-asana-gid="{gid}" '
                         f'data-asana-type="attachment">shot.png</a></body>'})
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(af, "post_story", post_as_asana_stores_it_then_lose_the_reply)
    f = make(tmp_path, ("shot.png", b"\x89PNG"))
    assert run(*file_args(f), "--comment", "link") == 0
    assert "Reconciled: the comment posted (990)" in capsys.readouterr().out


def test_two_new_comments_of_ours_are_ambiguous_not_adopted(tmp_path, monkeypatch, capsys):
    fake = FakeTask().install(monkeypatch)

    def post_twice_then_fail(token, task, comment_html):
        for gid in ("801", "802"):
            fake.story_rows.append({"gid": gid, "resource_subtype": "comment_added",
                                    "created_by": {"gid": "me"}, "text": "a.md"})
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(af, "post_story", post_twice_then_fail)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 4
    out = capsys.readouterr().out
    assert "Reconciled" not in out and "Comment:       UNKNOWN" in out


def test_an_own_comment_naming_only_some_of_the_files_is_not_adopted(tmp_path, monkeypatch, capsys):
    fake = FakeTask().install(monkeypatch)

    def post_partial_then_fail(token, task, comment_html):
        fake.story_rows.append({"gid": "901", "resource_subtype": "comment_added",
                                "created_by": {"gid": "me"}, "text": "a.md only"})
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(af, "post_story", post_partial_then_fail)
    f = make(tmp_path, ("a.md", b"a"), ("b.md", b"b"))
    assert run(*file_args(f), "--comment", "name") == 4
    out = capsys.readouterr().out
    assert "Reconciled: the comment" not in out and "Comment:       UNKNOWN" in out


# --- found in the self-assessment ---------------------------------------------

def test_two_resume_gids_matching_the_same_file_are_refused(tmp_path, monkeypatch):
    rows = [{"gid": "4", "name": "a.md", "size": 1}, {"gid": "5", "name": "a.md", "size": 1}]
    fake = FakeTask(attachments=rows).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name", "--resume", "4", "--resume", "5") == 4
    assert fake.uploaded == [] and fake.stories == []


def test_the_stop_block_says_what_to_do_if_a_plugin_update_moved_the_script(tmp_path, monkeypatch, capsys):
    """Source guard on the wording: a recorded resume command can outlive the
    plugin version folder it names."""
    FakeTask(fail_comment=True).install(monkeypatch)
    f = make(tmp_path, ("a.md", b"a"))
    assert run(*file_args(f), "--comment", "name") == 4
    assert "a plugin update moves it" in capsys.readouterr().out


# --- --name: send a file under another name ------------------------------------
# Before, a caller that wanted another name uploaded a renamed temp copy, and a
# STOPPED block's resume command then named the deleted temp file.

def test_name_uploads_the_file_under_the_new_name(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("IMG_0001.pdf", b"%PDF boarding pass"))
    assert run(*file_args(f), "--name", "Boarding pass SFO to LAX_Sam", "--comment", "name") == 0
    assert fake.uploaded == ["Boarding pass SFO to LAX_Sam.pdf"]
    assert fake.attachments[0]["size"] == len(b"%PDF boarding pass")
    assert "<code>Boarding pass SFO to LAX_Sam.pdf</code>" in fake.stories[0]
    assert "IMG_0001" not in fake.stories[0]


def test_name_with_its_own_extension_is_kept(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("scan.jpeg", b"x"))
    assert run(*file_args(f), "--name", "Bag tags SEA to DEN.jpg", "--comment", "none") == 0
    assert fake.uploaded == ["Bag tags SEA to DEN.jpg"]


def test_the_duplicate_check_uses_the_new_name(tmp_path, monkeypatch):
    fake = FakeTask(attachments=[{"gid": "1", "name": "E-ticket SFO-LAX.pdf", "size": 1}]
                    ).install(monkeypatch)
    f = make(tmp_path, ("download.pdf", b"x"))
    assert run(*file_args(f), "--name", "E-ticket SFO-LAX", "--comment", "none") == 3
    assert fake.uploaded == []


def test_names_are_paired_with_files_in_order(tmp_path, monkeypatch):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("a.png", b"a"), ("b.png", b"bb"))
    assert run(*file_args(f), "--name", "First", "--name", "Second", "--comment", "name") == 0
    assert fake.uploaded == ["First.png", "Second.png"]
    assert {a["name"]: a["size"] for a in fake.attachments} == {"First.png": 1, "Second.png": 2}


@pytest.mark.parametrize("names", [["only one"], ["a", "b", "c"]])
def test_name_count_must_match_file_count(tmp_path, monkeypatch, names):
    no_network(monkeypatch)
    f = make(tmp_path, ("a.png", b"a"), ("b.png", b"b"))
    argv = [x for n in names for x in ("--name", n)]
    assert run(*file_args(f), *argv, "--comment", "none") == 4


@pytest.mark.parametrize("name", ["SFO/LAX","..", "  ", "aws_token.txt", 'say "hi"'])
def test_a_bad_name_is_refused_before_any_call(tmp_path, monkeypatch, name):
    no_network(monkeypatch)
    f = make(tmp_path, ("photo.png", b"x"))
    assert run(*file_args(f), "--name", name, "--comment", "none") == 4


def test_a_credential_file_is_refused_even_under_a_safe_name(tmp_path, monkeypatch):
    no_network(monkeypatch)
    f = make(tmp_path, (".env", b"SECRET=1"))
    assert run(*file_args(f), "--name", "notes.txt", "--comment", "none") == 4


def test_two_files_given_the_same_name_are_refused(tmp_path, monkeypatch):
    no_network(monkeypatch)
    f = make(tmp_path, ("a.png", b"a"), ("b.png", b"b"))
    assert run(*file_args(f), "--name", "Same", "--name", "Same", "--comment", "none") == 4


def test_the_printed_resume_command_with_names_finishes_the_job(tmp_path, monkeypatch, capsys):
    """Replay the printed command itself: two renamed files, one name starting with '-'."""
    import shlex
    fake = FakeTask(fail_upload="-Second.png").install(monkeypatch)
    f = make(tmp_path, ("IMG_1.png", b"one"), ("IMG_2.png", b"two!"))
    assert run(*file_args(f), "--name", "First", "--name=-Second", "--comment", "name") == 4
    resume = capsys.readouterr().out.split("Resume with:", 1)[1].splitlines()[0].strip()
    argv = shlex.split(resume)
    assert "--name=-Second" in argv and argv.index("--name=First") < argv.index("--name=-Second")
    fake.fail_upload = None
    assert af.main(argv[2:]) == 0
    assert fake.uploaded == ["First.png", "-Second.png"]          # each file once
    assert "<code>First.png</code>" in fake.stories[-1] and "<code>-Second.png</code>" in fake.stories[-1]


@pytest.mark.parametrize("name, sent", [
    ("Boarding pass 07.15 SFO to LAX", "Boarding pass 07.15 SFO to LAX.pdf"),
    ("Mr. Smith e-ticket", "Mr. Smith e-ticket.pdf"),
    ("Receipt 12.50", "Receipt 12.50.pdf"),
    ("Itinerary.v2", "Itinerary.v2"),
    ("scan.PDF", "scan.PDF"),
])
def test_only_a_real_extension_counts(tmp_path, monkeypatch, name, sent):
    fake = FakeTask().install(monkeypatch)
    f = make(tmp_path, ("IMG_0001.pdf", b"x"))
    assert run(*file_args(f), "--name", name, "--comment", "none") == 0
    assert fake.uploaded == [sent]


def test_the_real_upload_sends_the_new_name_and_the_file_s_bytes(tmp_path, monkeypatch):
    sent = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"data": {"gid": "1", "name": "Boarding pass_Sam.pdf"}}'

    def fake_urlopen(req, timeout=None):
        sent["body"], sent["type"] = req.data, req.headers["Content-type"]
        return Reply()

    monkeypatch.setattr(af.urllib.request, "urlopen", fake_urlopen)
    src = tmp_path / "IMG_0001.pdf"
    src.write_bytes(b"%PDF real bytes")
    af.upload("t", TASK, af.Named(src, "Boarding pass_Sam.pdf"))
    msg = email.parser.BytesParser().parsebytes(
        b"Content-Type: " + sent["type"].encode() + b"\r\n\r\n" + sent["body"])
    part = [p for p in msg.get_payload() if p.get_param("name", header="content-disposition") == "file"][0]
    assert part.get_filename() == "Boarding pass_Sam.pdf"
    assert part.get_content_type() == "application/pdf"
    assert part.get_payload(decode=True) == b"%PDF real bytes"


def test_dry_run_shows_the_new_name(tmp_path, monkeypatch, capsys):
    no_network(monkeypatch)
    f = make(tmp_path, ("IMG_2.pdf", b"x"))
    assert run(*file_args(f), "--name", "E-ticket", "--comment", "none", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "E-ticket.pdf  (from " in out and "IMG_2.pdf" in out
