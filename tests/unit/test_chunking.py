import pytest

from contextforge.chunking import (
    ChunkingConfig,
    DocumentContext,
    chunk_document,
    fixed_size_chunks,
    structure_aware_chunks,
)
from contextforge.chunking.splitting import window_spans
from contextforge.common.models import ParsedDocument, ParsedSection

CTX = DocumentContext("doc1", 3, "eng/spec.md", "acme", "owner1", ("engineering", "administrator"))


def words(n, prefix="w"):
    return " ".join(f"{prefix}{i}." if i % 9 == 8 else f"{prefix}{i}" for i in range(n))


def test_fixed_chunks_respect_size_and_overlap():
    doc = ParsedDocument("t", [ParsedSection("S", 1, words(600), None)])
    chunks = fixed_size_chunks(doc, CTX, ChunkingConfig("fixed", 500, 100))
    assert len(chunks) > 3
    assert all(len(c.text) <= 500 for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.text.split()[0] in prev.text  # overlap carries context forward


def test_window_spans_validates_parameters():
    with pytest.raises(ValueError):
        window_spans("abc", 100, 100)


def test_metadata_is_preserved_on_every_chunk():
    doc = ParsedDocument("t", [ParsedSection("Intro", 1, words(300), 4)])
    for strategy in ("fixed", "structure"):
        chunks = chunk_document(doc, CTX, ChunkingConfig(strategy, 400, 50))
        assert chunks
        for i, c in enumerate(chunks):
            assert (c.document_id, c.document_version, c.chunk_index) == ("doc1", 3, i)
            assert (c.source_path, c.tenant_id, c.owner_id) == ("eng/spec.md", "acme", "owner1")
            assert c.allowed_groups == ["engineering", "administrator"]
            assert c.page_number == 4 and c.section_title == "Intro"
            assert c.chunk_id == f"doc1:v3:{i:05d}"


def test_structure_chunks_never_merge_large_sections():
    doc = ParsedDocument("t", [
        ParsedSection("Alpha", 1, words(120, "a"), 1),
        ParsedSection("Beta", 1, words(120, "b"), 1),
    ])
    chunks = structure_aware_chunks(doc, CTX, ChunkingConfig("structure", 2000, 100, 200))
    assert [c.section_title for c in chunks] == ["Alpha", "Beta"]
    assert not any("a1 " in c.text and "b1 " in c.text for c in chunks)


def test_small_section_is_folded_into_next_with_its_heading():
    doc = ParsedDocument("t", [
        ParsedSection("Tiny", 1, "short", 1),
        ParsedSection("Real", 1, words(80), 1),
    ])
    chunks = structure_aware_chunks(doc, CTX, ChunkingConfig("structure", 2000, 100, 200))
    assert len(chunks) == 1
    assert chunks[0].section_title == "Tiny" and "Real\n" in chunks[0].text


def test_structure_chunks_do_not_cross_pages():
    doc = ParsedDocument("t", [ParsedSection("S", 1, "tiny", 1), ParsedSection("S", 1, words(60), 2)])
    chunks = structure_aware_chunks(doc, CTX, ChunkingConfig("structure", 2000, 100, 200))
    assert [c.page_number for c in chunks] == [1, 2]


def test_oversized_section_is_split_on_paragraphs():
    paragraphs = "\n\n".join(words(40, f"p{i}x") for i in range(10))
    doc = ParsedDocument("t", [ParsedSection("Long", 1, paragraphs, None)])
    chunks = structure_aware_chunks(doc, CTX, ChunkingConfig("structure", 600, 50, 100))
    assert len(chunks) > 2 and all(len(c.text) <= 600 for c in chunks)
    assert all(c.section_title == "Long" for c in chunks)


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError):
        chunk_document(ParsedDocument("t", []), CTX, ChunkingConfig("magic"))


def test_embedding_text_includes_section_title():
    doc = ParsedDocument("t", [ParsedSection("Rollback", 1, "run the tool", None)])
    chunk = chunk_document(doc, CTX, ChunkingConfig())[0]
    assert chunk.embedding_text.startswith("Rollback\n")
