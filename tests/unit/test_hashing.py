from contextforge.common.hashing import chunk_id_for, document_id_for, sha256_bytes, sha256_file


def test_same_content_same_hash(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"hello")
    b.write_bytes(b"hello")
    assert sha256_file(a) == sha256_file(b) == sha256_bytes(b"hello")


def test_one_byte_change_changes_hash():
    assert sha256_bytes(b"hello") != sha256_bytes(b"hellp")


def test_document_id_is_stable_and_path_specific():
    first = document_id_for("t1", "fs", "a/b.md")
    assert first == document_id_for("t1", "fs", "a/b.md")
    assert first != document_id_for("t1", "fs", "a/c.md")
    assert first != document_id_for("t2", "fs", "a/b.md")


def test_chunk_ids_sort_by_index():
    ids = [chunk_id_for("doc", 1, i) for i in (2, 10, 1)]
    assert sorted(ids) == [ids[2], ids[0], ids[1]]
