"""Unit tests for the document-pdf scripts (pure functions; no poppler needed),
plus an end-to-end build+verify that runs only when a PDF engine and poppler exist."""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
SKILL = os.path.dirname(SCRIPTS)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


v = load("verify_pdf")
b = load("build_pdf")


class VerifyFunctions(unittest.TestCase):
    def test_expect_matches_across_line_wrap(self):
        text = "the Contractor releases the\nCompany   from all claims"
        self.assertEqual(v.find_missing(text, ["releases the Company from all claims"]), [])
        self.assertEqual(v.find_missing(text, ["AUD 5,000"]), ["AUD 5,000"])

    def test_forbidden_uppercase_is_whole_word_and_case_sensitive(self):
        self.assertEqual(v.find_forbidden("This is a DRAFT for review", ["DRAFT"]), ["DRAFT"])
        self.assertEqual(v.find_forbidden("the parties may draft a variation", ["DRAFT"]), [])
        self.assertEqual(v.find_forbidden("DRAFTING note", ["DRAFT"]), [])
        self.assertEqual(v.find_forbidden("the parties confirm", ["CONFIRM"]), [])

    def test_marker_word_cases(self):
        self.assertEqual(v.find_forbidden("Draft Deed of Release", ["DRAFT"]), ["DRAFT"])
        self.assertEqual(v.find_forbidden("Settlement date tbc. Todo: check", ["TODO", "TBC"]), ["TODO", "TBC"])
        self.assertEqual(v.find_forbidden("internal policy; the parties confirm", ["CONFIRM", "INTERNAL"]), [])
        self.assertEqual(v.find_forbidden("Todo el contrato es válido; todo pago", ["TODO"]), [])
        self.assertEqual(v.find_forbidden("todo: fix the date", ["TODO"]), ["TODO"])
        self.assertEqual(v.find_forbidden("TODO: fix the date", ["TODO"]), ["TODO"])
        self.assertEqual(v.find_forbidden("Amount: TODO", ["TODO"]), ["TODO"])
        self.assertEqual(v.find_forbidden("TODO check with client", ["TODO"]), ["TODO"])
        # an all-caps Spanish heading needs the --allow TODO waiver (covered below)
        self.assertEqual(v.find_forbidden("TODO EL CONTRATO", ["TODO"]), ["TODO"])

    def test_allow_waives_a_builtin_marker(self):
        a = v.parser().parse_args(["x.pdf", "--allow", "TODO", "--allow", "DRAFT"])
        self.assertEqual(a.allow, ["TODO", "DRAFT"])
        with self.assertRaises(SystemExit):
            v.parser().parse_args(["x.pdf", "--allow", "anything"])

    def test_citations_are_not_placeholders(self):
        text = "see [1] and [2019] EWCA Civ 1 and [2018] 1 WLR 5, it was wrong [sic], pay [amount]"
        self.assertEqual(v.open_placeholders(text), ["[amount]"])

    def test_bracketed_numbers_are_open_terms_when_signing(self):
        text = "payment within [30] days, dated [2026] by the parties"
        self.assertEqual(v.open_placeholders(text, "signing"), ["[2026]", "[30]"])
        self.assertEqual(v.open_placeholders(text, "general"), ["[2026]"])
        self.assertEqual(v.open_placeholders("see [1]", "signing"), ["[1]"])

    def test_citation_shape(self):
        for cite in ("[2019] Ch 123", "[2020] Fam 12", "[2019] 2 All ER 1", "[2019] EWCA Civ 1",
                     "[2018] 1 Lloyd's Rep 5", "[2023] UKSC 5"):
            self.assertEqual(v.open_placeholders(cite, "signing"), [], cite)
        for open_term in ("THIS DEED is dated [2026]\nBETWEEN:", "dated [2026] BETWEEN the parties",
                          "dated [2026]\nPARTIES"):
            self.assertEqual(v.open_placeholders(open_term, "signing"), ["[2026]"], open_term)

    def test_sender_only_valid_for_text_merge(self):
        self.assertEqual(v.open_placeholders("[sig|req|sender]"), ["[sig|req|sender]"])
        self.assertEqual(v.open_placeholders("[text-merge|req|sender|Company|co]"), [])

    def test_expect_and_forbid_repeat(self):
        a = v.parser().parse_args(["x.pdf", "--expect", "A", "--expect", "B", "C", "--forbid", "P1", "--forbid", "P2"])
        self.assertEqual(a.expect, ["A", "B", "C"])
        self.assertEqual(a.forbid, ["P1", "P2"])

    def test_profiles(self):
        self.assertNotIn("DRAFT", v.PROFILES["general"])
        self.assertIn("DRAFT", v.PROFILES["signing"])
        self.assertTrue(set(v.PROFILES["general"]) <= set(v.PROFILES["signing"]))

    def test_forbidden_phrase_is_case_insensitive(self):
        self.assertEqual(v.find_forbidden("This is Not Legal\nAdvice.", ["not legal advice"]), ["not legal advice"])

    def test_esign_tags_are_not_placeholders(self):
        text = "[sig|req|signer1] Signature [date|req|signer1] Date [Insert address]"
        self.assertEqual(v.open_placeholders(text), ["[Insert address]"])

    def test_esign_tags_do_not_trip_forbidden_words(self):
        self.assertEqual(v.find_forbidden("[text|req|signer1|DRAFT]", ["DRAFT"]), [])

    def test_signer_gap_detected(self):
        nums, missing, invalid = v.signer_gaps("[sig|req|signer1] [sig|req|signer3]")
        self.assertEqual((nums, missing, invalid), ([1, 3], [2], []))
        self.assertEqual(v.signer_gaps("no tags"), ([], [], []))

    def test_signer_zero_is_invalid(self):
        self.assertEqual(v.signer_gaps("[sig|req|signer0]")[2], [0])
        self.assertEqual(v.signer_gaps("[text-merge|req|signer0|Company|co]")[2], [0])

    def test_text_merge_signers_count(self):
        self.assertEqual(v.signer_gaps("[sig|req|signer1] [text-merge|req|signer3|X|x]")[1], [2])
        self.assertEqual(v.signer_gaps("[sig|req|signer1] [text-merge|req|signer2|X|x] [sig|req|signer3]")[1], [])

    def test_malformed_tag_is_a_placeholder(self):
        self.assertEqual(v.open_placeholders("[sig|req|signer1TYPO]"), ["[sig|req|signer1TYPO]"])
        self.assertEqual(v.signer_gaps("[sig|req|signer1TYPO]"), ([], [], []))

    def test_tag_with_label_and_text_merge_are_tags(self):
        text = "[text|req|signer1|Full name|name1] [text-merge|noreq|sender|Company|co]"
        self.assertEqual(v.open_placeholders(text), [])

    def test_wrapped_and_empty_placeholders_caught(self):
        self.assertEqual(v.open_placeholders("pay [insert\nthe amount] now"), ["[insert the amount]"])
        self.assertEqual(v.open_placeholders("blank [] here"), ["[]"])

    def test_redaction_notes_are_not_placeholders(self):
        self.assertEqual(v.open_placeholders("PIN: [PIN redacted] see [long link removed]"), [])

    def test_explicit_forbid_checks_inside_tags(self):
        self.assertEqual(v.find_forbidden("[text|req|signer1|SECRET123]", ["SECRET123"], strip_tags=False), ["SECRET123"])

    def test_orphaned_execution_page(self):
        self.assertTrue(v.orphaned_execution_page("Execution\nSignature\nDate"))
        long_page = "clause text " * 40 + " Signature"
        self.assertFalse(v.orphaned_execution_page(long_page))

    def test_page_size_names(self):
        self.assertEqual(v.page_size_name(595.28, 841.89), "A4")
        self.assertEqual(v.page_size_name(612, 792), "Letter")
        self.assertEqual(v.page_size_name(841.89, 595.28), "A4")  # landscape


class BuildFunctions(unittest.TestCase):
    def test_title_is_escaped_and_base_points_at_source(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "a b.md")
            with open(src, "w") as f:
                f.write("# Hi\n")
            if not (shutil.which("pandoc") or importlib.util.find_spec("markdown")):
                self.skipTest("no Markdown converter")
            out = b.md_to_html(src, [b.HOUSE_CSS], "A &copy; <B>")
            self.assertIn("<title>A &amp;copy; &lt;B&gt;</title>", out)
            self.assertIn('<base href="file://', out)

    @unittest.skipUnless(importlib.util.find_spec("markdown"), "python-markdown not installed")
    def test_python_markdown_parses_inside_div(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "x.md")
            with open(src, "w") as f:
                f.write('<div class="keep">\n\n## Execution\n\n</div>\n')
            saved = b.shutil.which
            b.shutil.which = lambda name: None if name == "pandoc" else saved(name)
            try:
                body = b.md_body(src)
            finally:
                b.shutil.which = saved
            self.assertIn("<h2>Execution</h2>", body)
            self.assertNotIn("## Execution", body)

    def test_html_blocks_marked_but_not_inside_code(self):
        src = '<div class="keep">\n\n```\n<div class="keep">\n```\n\nUse `<div class="x">` inline.\n'
        out = b.mark_html_blocks(src)
        self.assertTrue(out.startswith('<div markdown="1" class="keep">'))
        self.assertIn('```\n<div class="keep">\n```', out)
        self.assertIn('`<div class="x">`', out)

    def test_indented_code_and_long_fences_left_alone(self):
        src = ('    <div class="example">\n\n'
               '````\n```\n<div class="inner">\n```\n````\n\n'
               '<div class="keep">\n')
        out = b.mark_html_blocks(src)
        self.assertIn('    <div class="example">', out)
        self.assertIn('```\n<div class="inner">\n```', out)
        self.assertIn('<div markdown="1" class="keep">', out)

    def test_css_is_linked_by_file_uri(self):
        if not (shutil.which("pandoc") or importlib.util.find_spec("markdown")):
            self.skipTest("no Markdown converter")
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "x.md")
            with open(src, "w") as f:
                f.write("# Hi\n")
            out = b.md_to_html(src, [b.HOUSE_CSS], "x")
            self.assertIn('<link rel="stylesheet" href="file://', out)

    def test_failed_build_removes_stale_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "x.md")
            with open(src, "w") as f:
                f.write("# Hi\n")
            out = os.path.join(d, "x.pdf")
            with open(out, "wb") as f:
                f.write(b"%PDF-old")
            with self.assertRaises(SystemExit):
                b.main([src, out, "--css", os.path.join(d, "missing.css")])
            self.assertFalse(os.path.exists(out))
            self.assertTrue(os.path.exists(src))

    def test_output_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "x.md")
            with open(src, "w") as f:
                f.write("# Hi\n")
            for out in (src, os.path.join(d, "x.txt")):
                with self.assertRaises(SystemExit):
                    b.main([src, out])
            self.assertTrue(os.path.exists(src))

    def test_is_pdf_rejects_junk(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.pdf")
            with open(p, "wb") as f:
                f.write(b"not a pdf")
            self.assertFalse(b.is_pdf(p))


HAVE_POPPLER = all(shutil.which(t) for t in ("pdfinfo", "pdftotext", "pdftoppm"))
HAVE_ENGINE = bool(b.have_weasyprint() or b.find_chrome())
HAVE_MD = bool(shutil.which("pandoc") or importlib.util.find_spec("markdown"))


@unittest.skipUnless(HAVE_POPPLER and HAVE_ENGINE and HAVE_MD, "needs poppler, a PDF engine and a Markdown converter")
class EndToEnd(unittest.TestCase):
    def test_signing_example_builds_and_passes(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "deed.pdf")
            b.main([os.path.join(SKILL, "assets", "example-deed.md"), out])
            self.assertEqual(v.main([out, "--profile", "signing", "--expect", "AUD 5,000", "s127(1)(c)",
                                     "--size", "A4"]), 0)

    def test_general_example_allows_draft_but_signing_does_not(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "memo.pdf")
            b.main([os.path.join(SKILL, "assets", "example-memo.md"), out])
            self.assertEqual(v.main([out, "--expect", "AUD 11,400", "--size", "A4"]), 0)
            self.assertEqual(v.main([out, "--profile", "signing"]), 1)

    def test_placeholder_and_signer_gap_fail_in_general_profile(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "bad.md")
            with open(src, "w") as f:
                f.write("# Agreement\n\nPay [amount] by [date].\n\n[sig|req|signer2]\n")
            out = os.path.join(d, "bad.pdf")
            b.main([src, out])
            self.assertEqual(v.main([out]), 1)

    def test_bad_engine_exit_fails_the_build(self):
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, "fake-chrome")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\nfor a in \"$@\"; do case $a in --print-to-pdf=*) printf '%%PDF-1.4 valid header' > \"${a#--print-to-pdf=}\";; esac; done\nexit 17\n")
            os.chmod(fake, 0o755)
            saved = b.find_chrome
            b.find_chrome = lambda: fake
            try:
                with self.assertRaises(SystemExit):
                    b.main(["--engine", "chrome", os.path.join(SKILL, "assets", "example-deed.md"), os.path.join(d, "o.pdf")])
            finally:
                b.find_chrome = saved


if __name__ == "__main__":
    unittest.main()
