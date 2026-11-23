from contextforge.common.models import ParsedDocument, ParsedSection
from contextforge.normalization.normalize import normalize_document, normalize_text


def test_whitespace_and_unicode_are_normalized():
    assert normalize_text("a\u00a0 b\t\tc\r\n\r\n\r\n\r\nd\u200b") == "a b c\n\nd"


def test_hyphenated_line_break_is_joined_but_real_hyphens_survive():
    assert normalize_text("infra-\nstructure and state-of-the-art") == "infrastructure and state-of-the-art"


def test_reflow_joins_wrapped_lines_inside_paragraphs_only():
    assert normalize_text("one\ntwo\n\nthree", reflow=True) == "one two\n\nthree"


def _pdf_like(pages):
    sections = []
    for n in range(1, pages + 1):
        sections.append(
            ParsedSection("Body", 1, f"Acme Internal\nreal content {n}\nPage {n} of {pages}", n)
        )
    return ParsedDocument("t", sections, page_count=pages)


def test_repeated_headers_and_page_numbers_are_removed_from_pdfs():
    doc = normalize_document(_pdf_like(4), "pdf")
    assert [s.text for s in doc.sections] == [f"real content {n}" for n in range(1, 5)]
    assert [s.page_number for s in doc.sections] == [1, 2, 3, 4]


def test_repeated_lines_are_kept_for_non_pdf_formats():
    doc = ParsedDocument("t", [ParsedSection(None, 1, "Acme Internal\nbody", None)])
    assert normalize_document(doc, "markdown").sections[0].text == "Acme Internal\nbody"


def test_sections_that_become_empty_are_dropped():
    doc = ParsedDocument("t", [ParsedSection(None, 1, " \n\u200b ", None)])
    assert normalize_document(doc, "txt").sections == []
