"""Tests for redact_doc.py: a redacted copy of one personal or financial document, plus --check.

Every value here is fake: zero or sequential digits, example.invalid emails, made-up ids.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "redact_doc.py"

IBAN_SPACED = "ES00 1234 5678 9012 3456 7890"
IBAN_PLAIN = "ES0012345678901234567890"
IBAN_MASKED = "ES00...7890"
NIE = "X0000000T"
NIF = "00000000T"
CIF = "B00000000"
VAT_ES = "ESB00000001"
VAT_DE = "DE000000002"
EMAIL = "someone.fake@example.invalid"
DRIVE_LINK = "https://docs.google.com/document/d/1FakeDocIdAbCdEfGhIjKlMnOpQrStUvW/edit"
DRIVE_ID = "1FakeIdAbCdEfGhIjKlMnOpQrStUvWx00"  # 33 characters
GMAIL_ID = "18f00000000abcde"
SHA = "0123456789abcdef0123456789abcdef01234567"  # a git SHA must stay
SLUG = "2026-01-15-example-plan-fake-slug"  # 33-character kebab slug must stay
REGISTRY = "REG-FAKE-0001"

RAW_VALUES = [IBAN_SPACED, IBAN_PLAIN, IBAN_MASKED, NIE, NIF, CIF, VAT_ES, VAT_DE, EMAIL,
              DRIVE_LINK, DRIVE_ID, GMAIL_ID, REGISTRY]

DOC = f"""# Fake tax decision

Pay to {IBAN_SPACED} or {IBAN_PLAIN}; the old account was {IBAN_MASKED}.
Owner NIE {NIE}, spouse DNI {NIF}, company CIF {CIF}.
VAT ids: {VAT_ES} and {VAT_DE}.
Contact {EMAIL}. Source: {DRIVE_LINK} and file {DRIVE_ID}.
Gmail message {GMAIL_ID}. Registry code {REGISTRY}.
Commit {SHA}, plan {SLUG}.
"""


def run(*args: str):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def write_doc(tmp_path: Path, text: str = DOC, name: str = "decision.md") -> Path:
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    path = src / name
    path.write_text(text, encoding="utf-8")
    return path


def count_line(stdout: str, label: str) -> list[str]:
    for line in stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == label:
            return parts[1:]
    raise AssertionError(f"no count line for {label} in:\n{stdout}")


def test_redacts_every_default_pattern(tmp_path):
    doc = write_doc(tmp_path)
    out = tmp_path / "subject"
    result = run(str(doc), "--out", str(out), "--extra", REGISTRY)
    assert result.returncode == 0, result.stderr
    copy = (out / "decision.md").read_text(encoding="utf-8")
    for value in RAW_VALUES:
        assert value.lower() not in copy.lower(), value
    for placeholder in ("[IBAN]", "[NIE]", "[NIF]", "[CIF]", "[VAT-ID]", "[email]", "[drive-link]",
                        "[drive-id]", "[gmail-id]", "[extra-1]"):
        assert placeholder in copy, placeholder
    assert copy.count("[IBAN]") == 3 and copy.count("[VAT-ID]") == 2
    assert SHA in copy and SLUG in copy  # look-alikes are kept
    assert doc.read_text(encoding="utf-8") == DOC  # the original is untouched


def test_prints_counts_for_original_and_copy(tmp_path):
    doc = write_doc(tmp_path)
    result = run(str(doc), "--out", str(tmp_path / "subject"), "--extra", REGISTRY)
    assert result.returncode == 0, result.stderr
    assert count_line(result.stdout, "[IBAN]") == ["3", "0"]
    assert count_line(result.stdout, "[VAT-ID]") == ["2", "0"]
    assert count_line(result.stdout, "[NIE]") == ["1", "0"]
    assert count_line(result.stdout, "[extra-1]") == ["1", "0"]
    assert "survivors=0" in result.stdout
    for value in RAW_VALUES:  # counts only: no raw value reaches the terminal
        assert value not in result.stdout and value not in result.stderr


def test_extra_literal_is_case_insensitive(tmp_path):
    doc = write_doc(tmp_path, "code reg-fake-0001 and REG-FAKE-0001\n")
    out = tmp_path / "subject"
    result = run(str(doc), "--out", str(out), "--extra", REGISTRY)
    assert result.returncode == 0, result.stderr
    assert (out / "decision.md").read_text(encoding="utf-8") == "code [extra-1] and [extra-1]\n"


def test_longer_extra_is_replaced_whole(tmp_path):
    # Shortest-first would write "[extra-1] Person" and leave the surname in the copy.
    doc = write_doc(tmp_path, "signed by Fake Person\n")
    out = tmp_path / "subject"
    result = run(str(doc), "--out", str(out), "--extra", "Fake", "--extra", "Fake Person")
    assert result.returncode == 0, result.stderr
    assert (out / "decision.md").read_text(encoding="utf-8") == "signed by [extra-2]\n"


def test_one_extra_flag_takes_several_literals(tmp_path):
    doc = write_doc(tmp_path, f"Fake Person, code {REGISTRY}\n")
    out = tmp_path / "subject"
    result = run(str(doc), "--out", str(out), "--extra", "Fake Person", REGISTRY)
    assert result.returncode == 0, result.stderr
    assert (out / "decision.md").read_text(encoding="utf-8") == "[extra-1], code [extra-2]\n"


def test_extra_survivor_exits_1_and_removes_copy(tmp_path):
    # The extra runs first; the IBAN pattern then writes "[IBAN]", which holds the literal again.
    doc = write_doc(tmp_path, f"pay {IBAN_PLAIN}\n")
    out = tmp_path / "subject"
    result = run(str(doc), "--out", str(out), "--extra", "IBAN")
    assert result.returncode == 1
    assert "[extra-1] survived" in result.stderr
    assert not (out / "decision.md").exists()


def test_pattern_survivor_exits_1_and_removes_copy(tmp_path):
    # [TWO] writes "[TWO]", which the earlier [ONE] pattern matches: a survivor in the copy.
    patterns = tmp_path / "patterns.txt"
    patterns.write_text("[ONE] O\\]\n[TWO] T\n", encoding="utf-8")
    doc = write_doc(tmp_path, "T\n")
    out = tmp_path / "subject"
    result = run(str(doc), "--out", str(out), "--patterns", str(patterns))
    assert result.returncode == 1
    assert "[ONE] survived" in result.stderr
    assert not (out / "decision.md").exists()


def test_equal_length_overlap_takes_the_earlier_rule(tmp_path):
    patterns = tmp_path / "patterns.txt"
    patterns.write_text("[FIRST] bc\n[SECOND] ab\n", encoding="utf-8")
    doc = write_doc(tmp_path, "abc\n")
    out = tmp_path / "subject"
    result = run(str(doc), "--out", str(out), "--patterns", str(patterns))
    assert result.returncode == 0, result.stderr
    assert (out / "decision.md").read_text(encoding="utf-8") == "[FIRST]\n"


def test_custom_patterns_replace_the_default(tmp_path):
    patterns = tmp_path / "patterns.txt"
    patterns.write_text("# private\n\n[case-ref] \\bCASE-\\d{4}\\b\n", encoding="utf-8")
    doc = write_doc(tmp_path, f"see CASE-0042 and {NIE}\n")
    out = tmp_path / "subject"
    result = run(str(doc), "--out", str(out), "--patterns", str(patterns))
    assert result.returncode == 0, result.stderr
    assert (out / "decision.md").read_text(encoding="utf-8") == f"see [case-ref] and {NIE}\n"


def test_bad_pattern_lines_are_usage_errors(tmp_path):
    doc = write_doc(tmp_path)
    for body, needle in (("no placeholder here\n", "line 1"), ("[bad] (unclosed\n", "line 1")):
        patterns = tmp_path / "patterns.txt"
        patterns.write_text(body, encoding="utf-8")
        result = run(str(doc), "--out", str(tmp_path / "subject"), "--patterns", str(patterns))
        assert result.returncode == 2 and needle in result.stderr, result.stderr


def test_refuses_to_overwrite_the_original(tmp_path):
    doc = write_doc(tmp_path)
    result = run(str(doc), "--out", str(doc.parent))
    assert result.returncode == 2
    assert "overwrite the original" in result.stderr
    assert doc.read_text(encoding="utf-8") == DOC


def test_non_utf8_input_is_a_usage_error(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    doc = src / "scan.pdf"
    doc.write_bytes(b"%PDF-1.4 \xff\xfe\x00")
    result = run(str(doc), "--out", str(tmp_path / "subject"))
    assert result.returncode == 2 and "UTF-8" in result.stderr


def test_out_is_required_without_check(tmp_path):
    result = run(str(write_doc(tmp_path)))
    assert result.returncode == 2 and "--out" in result.stderr


def test_check_finds_a_raw_value_in_leg_output(tmp_path):
    doc = write_doc(tmp_path)
    legs = tmp_path / "legs"
    (legs / "codex").mkdir(parents=True)
    (legs / "codex" / "out.txt").write_text("all clean: [NIE] [IBAN]\n", encoding="utf-8")
    (legs / "gemini.md").write_text(f"the owner is {NIE.lower()}\n", encoding="utf-8")
    result = run(str(doc), "--check", str(legs), "--extra", REGISTRY)
    assert result.returncode == 1
    assert "gemini.md" in result.stdout and "[NIE]" in result.stdout
    assert "out.txt" not in result.stdout  # the clean leg output is not reported
    assert "hits=1" in result.stdout
    assert NIE not in result.stdout and NIE.lower() not in result.stdout  # placeholder only, never the value


def test_check_clean_outputs_exit_0_with_positive_control(tmp_path):
    doc = write_doc(tmp_path)
    legs = tmp_path / "legs"
    legs.mkdir()
    (legs / "fable.md").write_text("[IBAN] [NIE] [extra-1] looks fine\n", encoding="utf-8")
    result = run(str(doc), "--check", str(legs), "--extra", REGISTRY)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "hits=0" in result.stdout
    control = next(line for line in result.stdout.splitlines() if line.startswith("control:"))
    # 13 values plus the Drive id inside the link, found by the per-rule pass on the original
    assert "values=14" in control and "found_in_original=14" in control


def test_check_finds_an_extra_literal(tmp_path):
    doc = write_doc(tmp_path, f"registry {REGISTRY}\n")
    legs = tmp_path / "legs"
    legs.mkdir()
    (legs / "glm.txt").write_text(f"code {REGISTRY}\n", encoding="utf-8")
    result = run(str(doc), "--check", str(legs), "--extra", REGISTRY)
    assert result.returncode == 1
    assert "glm.txt" in result.stdout and "[extra-1]" in result.stdout


LOOKALIKE_CASES = [
    ("IBAN with no-break spaces", "ES00 1234 5678 9012 3456 7890", "[IBAN]"),
    ("IBAN with double spaces", "ES00  1234  5678  9012  3456  7890", "[IBAN]"),
    ("IBAN partly masked", "ES00 1234 **** **** **** 7890", "[IBAN]"),
    ("NIE in Markdown emphasis", "_Y0000000T_", "_[NIE]_"),
    ("NIF in Markdown bold", "__00000000T__", "__[NIF]__"),
    ("email with underscore", "first_last@example.invalid", "[email]"),
    ("email in Markdown emphasis", "_someone@example.invalid_", "_[email]_"),
    ("Romanian short VAT", "RO12", "[VAT-ID]"),
    ("Irish VAT with a letter inside", "IE0A00000A", "[VAT-ID]"),
    ("uppercase Gmail id", "18F00000000ABCDE", "[gmail-id]"),
    ("legacy Drive id", "0BFakeIdAbCdEfGhIjKlMnOpQrSt", "[drive-id]"),
    ("CIF before a hyphen", "B00000000-", "[CIF]-"),
    ("CIF before a lowercase suffix", "B00000000-invoice", "[CIF]-invoice"),
    ("lowercase CIF", "b00000000", "[CIF]"),
    ("NIF with K prefix", "K0000000T", "[NIF]"),
    ("NIF with L prefix", "L0000000T", "[NIF]"),
    ("NIF with M prefix", "M0000000T", "[NIF]"),
    ("old 8-digit NIE", "X00000000T", "[NIE]"),
    ("lowercase NIE", "x0000000t", "[NIE]"),
    ("lowercase NIF", "00000000t", "[NIF]"),
    ("lowercase IBAN", "es00 1234 5678 9012 3456 7890", "[IBAN]"),
    ("quoted email local part", '"fake.person"@example.invalid', "[email]"),
    ("email with apostrophe", "o'fake@example.invalid", "[email]"),
    ("IBAN in other groups", "ES00 1234 5678 90 1234567890", "[IBAN]"),
    ("masked IBAN with a visible middle group", "ES00 **** 5678 **** **** 7890", "[IBAN]"),
    ("lowercase VAT", "de000000002", "[VAT-ID]"),
    ("VAT with a space after the prefix", "DE 000000002", "[VAT-ID]"),
    ("email with ! and /", "fake!per/son@example.invalid", "[email]"),
    ("masked IBAN before a full stop", "ES00...7890.", "[IBAN]."),
    ("masked IBAN before an amount", "ES00...7890 2500.00 EUR", "[IBAN] 2500.00 EUR"),
    ("quoted email with @ inside", '"fake@person"@example.invalid', "[email]"),
    ("email with an address literal", "fake@[192.0.2.1]", "[email]"),
    ("Drive id with no digit", "FakeAbAbAbAbAbAbAbAbAbAbAbAbAbAbZ", "[drive-id]"),
    ("Drive id in Markdown emphasis", "_1FakeIdAbCdEfGhIjKlMnOpQrStUvWx00_", "_[drive-id]_"),
    ("44-character Drive id with underscores", "1Fake_IdAbCdEfGhIjKlMnOpQrStUvWx00_AbCdEfGhI", "[drive-id]"),
]


OVERLAP_CASES = [
    # An NIE inside an email: the whole email goes, not "name_[NIE]_[email]".
    ("NIE inside an email", "first_X0000000T_last@example.invalid", "[email]"),
    # A VAT-shaped prefix inside a Drive-id-shaped token: the whole token goes.
    ("VAT inside a Drive id", "RO12_abcdefghijklmnopqrstuvwx1234", "[drive-id]"),
]

KEPT_CASES = [
    ("dated slug with capitals", "2026-01-15-API-migration-plan-v2"),
    ("dated 33-character slug", "2026-01-15-API-migration-plan-v22"),
    ("mixed-case 40-character SHA", "0123456789Abcdef0123456789abcdef01234567"),
]


def test_overlapping_matches_are_redacted_whole(tmp_path):
    out = tmp_path / "subject"
    for name, value, expected in OVERLAP_CASES:
        doc = write_doc(tmp_path, f"value {value} end\n")
        result = run(str(doc), "--out", str(out))
        assert result.returncode == 0, f"{name}: {result.stderr}"
        assert (out / "decision.md").read_text(encoding="utf-8") == f"value {expected} end\n", name


def test_plan_references_are_kept(tmp_path):
    out = tmp_path / "subject"
    for name, value in KEPT_CASES:
        doc = write_doc(tmp_path, f"see {value} end\n")
        result = run(str(doc), "--out", str(out))
        assert result.returncode == 0, f"{name}: {result.stderr}"
        assert (out / "decision.md").read_text(encoding="utf-8") == f"see {value} end\n", name


def test_lookalike_formats_are_redacted(tmp_path):
    out = tmp_path / "subject"
    for name, value, expected in LOOKALIKE_CASES:
        doc = write_doc(tmp_path, f"value {value} end\n")
        result = run(str(doc), "--out", str(out))
        assert result.returncode == 0, f"{name}: {result.stderr}"
        assert (out / "decision.md").read_text(encoding="utf-8") == f"value {expected} end\n", name


def test_refuses_to_overwrite_the_original_through_a_link(tmp_path):
    doc = write_doc(tmp_path)
    for kind in ("symlink", "hardlink"):
        out = tmp_path / f"subject-{kind}"
        out.mkdir()
        link = out / doc.name
        if kind == "symlink":
            link.symlink_to(doc)
        else:
            link.hardlink_to(doc)
        result = run(str(doc), "--out", str(out))
        assert result.returncode == 2, kind
        assert "overwrite the original" in result.stderr, kind
        assert doc.read_text(encoding="utf-8") == DOC, kind


def test_check_finds_an_id_that_was_inside_a_link(tmp_path):
    # The link rule redacts the whole URL, but a leg could still echo the bare id inside it.
    doc = write_doc(tmp_path, f"source {DRIVE_LINK}\n")
    legs = tmp_path / "legs"
    legs.mkdir()
    (legs / "codex.txt").write_text("id 1FakeDocIdAbCdEfGhIjKlMnOpQrStUvW\n", encoding="utf-8")
    result = run(str(doc), "--check", str(legs))
    assert result.returncode == 1, result.stdout
    assert "codex.txt" in result.stdout and "[drive-id]" in result.stdout


def test_check_finds_a_value_inside_an_extra(tmp_path):
    doc = write_doc(tmp_path, f"owner Fake Person {NIE}\n")
    legs = tmp_path / "legs"
    legs.mkdir()
    (legs / "gemini.txt").write_text(f"NIE {NIE}\n", encoding="utf-8")
    result = run(str(doc), "--check", str(legs), "--extra", f"Fake Person {NIE}")
    assert result.returncode == 1, result.stdout
    assert "[NIE]" in result.stdout


def test_check_finds_a_digit_free_id_from_a_drive_link(tmp_path):
    # The bare-id heuristic needs a digit; an id inside a Drive link is taken whatever its shape.
    link_id = "FakeDocIdAbCdEfGhIjKlMnOpQrStUvWx"
    doc = write_doc(tmp_path, f"source https://drive.google.com/file/d/{link_id}/view and "
                              f"https://drive.google.com/open?id={link_id}Y\n")
    legs = tmp_path / "legs"
    legs.mkdir()
    (legs / "codex.txt").write_text(f"ids {link_id} and {link_id}Y\n", encoding="utf-8")
    result = run(str(doc), "--check", str(legs))
    assert result.returncode == 1, result.stdout
    # The first id is also inside the second ("...WxY"), so it hits twice: 3 hits in all.
    assert "[drive-id]" in result.stdout and "hits=3" in result.stdout, result.stdout


def test_ordinary_lowercase_words_with_digits_are_kept(tmp_path):
    doc = write_doc(tmp_path, "see detail2024 and setup2025a here\n")
    out = tmp_path / "subject"
    result = run(str(doc), "--out", str(out))
    assert result.returncode == 0, result.stderr
    assert (out / "decision.md").read_text(encoding="utf-8") == "see detail2024 and setup2025a here\n"


def test_check_finds_a_masked_iban_written_without_the_full_stop(tmp_path):
    doc = write_doc(tmp_path, f"IBAN {IBAN_MASKED}. Next.\n")
    legs = tmp_path / "legs"
    legs.mkdir()
    (legs / "codex.txt").write_text(f"account {IBAN_MASKED} here\n", encoding="utf-8")
    result = run(str(doc), "--check", str(legs))
    assert result.returncode == 1 and "[IBAN]" in result.stdout, result.stdout


def test_check_missing_target_and_empty_patterns_are_usage_errors(tmp_path):
    doc = write_doc(tmp_path)
    result = run(str(doc), "--check", str(tmp_path / "nope"))
    assert result.returncode == 2 and "does not exist" in result.stderr
    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing\n", encoding="utf-8")
    result = run(str(doc), "--out", str(tmp_path / "subject"), "--patterns", str(empty))
    assert result.returncode == 2 and "no patterns" in result.stderr


def test_missing_input_and_patterns_files_are_usage_errors(tmp_path):
    result = run(str(tmp_path / "nope.md"), "--out", str(tmp_path / "subject"))
    assert result.returncode == 2 and "cannot read input" in result.stderr, result.stderr
    doc = write_doc(tmp_path)
    result = run(str(doc), "--out", str(tmp_path / "subject"), "--patterns", str(tmp_path / "nope.txt"))
    assert result.returncode == 2 and "cannot read --patterns" in result.stderr, result.stderr


def test_default_patterns_file_is_ascii():
    # A literal no-break space or ellipsis is invisible in review; write it as a \uXXXX escape.
    data = SCRIPT.with_name("redact_doc_patterns.txt").read_bytes()
    bad = sorted({hex(b) for b in data if b > 127})
    assert not bad, f"non-ASCII bytes in the patterns file: {bad}"


def test_default_patterns_file_ships_next_to_the_script():
    patterns = SCRIPT.with_name("redact_doc_patterns.txt")
    lines = [ln for ln in patterns.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    labels = {ln.split()[0] for ln in lines}
    assert {"[IBAN]", "[NIE]", "[NIF]", "[CIF]", "[VAT-ID]", "[email]", "[drive-link]",
            "[drive-id]", "[gmail-id]"} <= labels
