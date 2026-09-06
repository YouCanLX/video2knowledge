from video2knowledge.knowledge import KnowledgeLibrary, normalize_tag, obsidian_tags


def test_obsidian_tags_are_structured_and_normalized():
    assert normalize_tag(" Machine Learning ") == "machine-learning"
    assert obsidian_tags(
        ["AI", "Machine Learning"], author="Example Creator", collection="Starter/Course"
    ) == [
        "video2knowledge",
        "creator/example-creator",
        "collection/starter/course",
        "topic/ai",
        "topic/machine-learning",
    ]


def test_knowledge_library_groups_markdown_and_builds_tag_tree(tmp_path):
    collection = tmp_path / "Creator" / "Python Course"
    first = collection / "First"
    second = collection / "Second"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "one.md").write_text(
        "---\ntitle: Intro to Python\nauthor: Teacher\n---\n"
        "# Intro to Python\n\n## Functions\nReusable functions.",
        encoding="utf-8",
    )
    (second / "two.md").write_text(
        "# Advanced Python\n\n## Functions\nDecorators and functions.", encoding="utf-8"
    )

    payload = KnowledgeLibrary(tmp_path).build(write_tags=True)

    assert payload["summary"]["documents"] == 2
    assert payload["summary"]["collections"] == 1
    assert payload["summary"]["updated"] == 2
    grouped = payload["collections"][0]
    assert grouped["name"] == "Python Course"
    assert grouped["document_count"] == 2
    assert {document["title"] for document in grouped["documents"]} == {
        "Intro to Python",
        "Advanced Python",
    }
    tags = {tag for document in grouped["documents"] for tag in document["tags"]}
    assert "collection/python-course" in tags
    assert "creator/teacher" in tags
    assert "topic/functions" in tags
    assert any(node["name"] == "collection" for node in payload["tag_tree"])
    assert payload["graph"]["edges"]
    assert '  - "collection/python-course"' in (first / "one.md").read_text(encoding="utf-8")


def test_reindex_preserves_frontmatter_and_is_idempotent(tmp_path):
    path = tmp_path / "Notes" / "note.md"
    path.parent.mkdir()
    path.write_text(
        "---\ntitle: Kept title\ntags: [manual]\ncustom: yes\n---\n# Note\n\n#inline-tag",
        encoding="utf-8",
    )
    library = KnowledgeLibrary(tmp_path)

    first = library.build(write_tags=True)
    content = path.read_text(encoding="utf-8")
    second = library.build(write_tags=True)

    assert first["summary"]["updated"] == 1
    assert second["summary"]["updated"] == 0
    assert "custom: yes" in content
    assert '  - "manual"' in content
    assert '  - "inline-tag"' in content
    assert path.read_text(encoding="utf-8") == content
