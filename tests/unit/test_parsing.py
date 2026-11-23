import io

import pytest
from docx import Document

from contextforge.devtools.minipdf import build_pdf
from contextforge.parsing import ParsingError, parse_document


def test_markdown_headings_become_sections():
    doc = parse_document(b"# Title\n\nintro\n\n## Part A\n\ntext a\n\n## Part B\n\ntext b", "markdown")
    assert doc.title == "Title"
    assert [(s.title, s.level) for s in doc.sections] == [("Title", 1), ("Part A", 2), ("Part B", 2)]
    assert doc.sections[1].text == "text a"


def test_markdown_table_content_is_extracted():
    doc = parse_document(b"# T\n\n| Code | Meaning |\n|---|---|\n| ERR-1 | boom |\n", "markdown")
    assert "ERR-1" in doc.sections[0].text and "boom" in doc.sections[0].text


def test_html_removes_scripts_nav_and_keeps_structure():
    html = (b"<html><head><title>T</title><script>evil()</script></head><body><nav>menu</nav>"
            b"<h1>Top</h1><p>alpha</p><h2>Sub</h2><ul><li>one</li></ul>"
            b"<table><tr><td>a</td><td>b</td></tr></table></body></html>")
    doc = parse_document(html, "html")
    text = " ".join(s.text for s in doc.sections)
    assert "evil" not in text and "menu" not in text
    assert [s.title for s in doc.sections] == ["Top", "Sub"]
    assert "- one" in text and "a | b" in text


def test_plain_text_detects_caps_and_underlined_headings():
    doc = parse_document(b"INTRO\n\nbody one\n\nDetails\n=======\nbody two\n", "txt")
    assert [s.title for s in doc.sections] == ["Intro", "Details"]


def test_text_decoding_falls_back_for_non_utf8():
    doc = parse_document("caf\u00e9 price".encode("cp1252"), "txt")
    assert "café" in doc.sections[0].text


def test_docx_headings_lists_and_tables():
    d = Document()
    d.add_heading("Doc Title", level=0)
    d.add_heading("Section", level=1)
    d.add_paragraph("body text")
    d.add_paragraph("item", style="List Bullet")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "k", "v"
    buf = io.BytesIO()
    d.save(buf)
    doc = parse_document(buf.getvalue(), "docx")
    assert doc.title == "Doc Title"
    assert doc.sections[0].title == "Section"
    assert "body text" in doc.sections[0].text and "- item" in doc.sections[0].text
    assert "k | v" in doc.sections[0].text


def test_corrupted_docx_raises_parsing_error_with_detail():
    with pytest.raises(ParsingError) as exc:
        parse_document(b"this is not a zip file", "docx")
    assert exc.value.parser == "docx" and exc.value.detail


def test_zero_byte_file_is_an_empty_document():
    assert parse_document(b"", "txt").is_empty


def test_pdf_pages_and_headings_are_preserved():
    pytest.importorskip("fitz")
    pages = [[("h1", "Report"), ("h2", "Alpha"), ("p", "first page body text " * 5)],
             [("h2", "Beta"), ("p", "second page body text " * 5)]]
    doc = parse_document(build_pdf(pages, header="Hdr"), "pdf")
    assert doc.page_count == 2
    by_title = {(s.title, s.page_number) for s in doc.sections}
    assert ("Alpha", 1) in by_title and ("Beta", 2) in by_title


def test_corrupted_pdf_raises_parsing_error():
    pytest.importorskip("fitz")
    with pytest.raises(ParsingError):
        parse_document(b"%PDF-1.4 garbage that is not a pdf", "pdf")
