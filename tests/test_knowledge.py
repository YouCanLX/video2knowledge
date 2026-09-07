import asyncio

from video2knowledge.knowledge import (
    KNOWLEDGE_GRAPH_PATH,
    KnowledgeLibrary,
    merge_similar_tags,
    normalize_tag,
    obsidian_tags,
)


class FakeTagger:
    async def generate_tags(self, title, text, language):
        assert text
        assert language == "zh-CN"
        return ["Python", "Functions", "Programming"]


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


def test_similar_topic_tags_merge_to_shorter_canonical_terms():
    assert merge_similar_tags(
        [
            "交易入门",
            "交易入门",
            "交易入门方法",
            "交易思维",
            "交易思维差异",
            "交易心态",
        ]
    ) == {
        "交易入门方法": "交易入门",
        "交易思维差异": "交易思维",
    }


def test_similar_topic_tags_keep_related_but_distinct_concepts():
    assert (
        merge_similar_tags(
            ["交易策略", "交易心态", "最佳突破交易策略", "最佳交易量策略", "fair", "unfair"]
        )
        == {}
    )


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

    payload = asyncio.run(KnowledgeLibrary(tmp_path).retag(FakeTagger()))

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


def test_llm_retag_replaces_old_tags_preserves_frontmatter_and_is_idempotent(tmp_path):
    path = tmp_path / "Notes" / "note.md"
    path.parent.mkdir()
    path.write_text(
        "---\ntitle: Kept title\ntags: [manual]\ncustom: yes\n---\n"
        "# Note\n\nTags: `old-source-tag`\n\n#inline-tag",
        encoding="utf-8",
    )
    library = KnowledgeLibrary(tmp_path)

    first = asyncio.run(library.retag(FakeTagger()))
    content = path.read_text(encoding="utf-8")
    second = asyncio.run(library.retag(FakeTagger()))

    assert first["summary"]["updated"] == 1
    assert second["summary"]["updated"] == 0
    assert "custom: yes" in content
    assert "manual" not in content
    assert '  - "inline-tag"' not in content
    assert "old-source-tag" not in content
    assert '  - "topic/python"' in content
    assert '  - "topic/functions"' in content
    assert path.read_text(encoding="utf-8") == content


def test_llm_failure_keeps_original_tags_and_markdown(tmp_path):
    class FailingTagger:
        async def generate_tags(self, title, text, language):
            raise RuntimeError("LLM unavailable")

    path = tmp_path / "Notes" / "note.md"
    path.parent.mkdir()
    original = "---\ntags: [keep-me]\n---\n# Important note\n"
    path.write_text(original, encoding="utf-8")

    payload = asyncio.run(KnowledgeLibrary(tmp_path).retag(FailingTagger()))

    assert payload["summary"]["updated"] == 0
    assert payload["summary"]["failed"] == 1
    assert path.read_text(encoding="utf-8") == original


def test_retag_merges_similar_topics_across_documents(tmp_path):
    class SimilarTagger:
        async def generate_tags(self, title, text, language):
            if title == "First":
                return ["交易入门", "风险管理", "交易心理"]
            return ["交易入门方法", "仓位管理", "执行纪律"]

    first = tmp_path / "Course" / "First.md"
    second = tmp_path / "Course" / "Second.md"
    first.parent.mkdir()
    first.write_text("---\ntitle: First\n---\n# First\n\nBody", encoding="utf-8")
    second.write_text("---\ntitle: Second\n---\n# Second\n\nBody", encoding="utf-8")

    payload = asyncio.run(KnowledgeLibrary(tmp_path).retag(SimilarTagger()))

    assert payload["summary"]["updated"] == 2
    assert payload["summary"]["merged_tags"] == 1
    assert '  - "topic/交易入门"' in first.read_text(encoding="utf-8")
    second_content = second.read_text(encoding="utf-8")
    assert '  - "topic/交易入门"' in second_content
    assert "交易入门方法" not in second_content


def test_retag_drops_color_and_numeric_artifacts(tmp_path):
    class NoisyTagger:
        async def generate_tags(self, title, text, language):
            return [
                "风险管理",
                "交易心理",
                "执行纪律",
                "fff7d6",
                "x27",
                "交易市场的",
            ]

    path = tmp_path / "note.md"
    path.write_text("# Note\n\nBody", encoding="utf-8")

    payload = asyncio.run(KnowledgeLibrary(tmp_path).retag(NoisyTagger()))
    content = path.read_text(encoding="utf-8")

    assert payload["summary"]["updated"] == 1
    assert payload["summary"]["failed"] == 0
    assert "fff7d6" not in content
    assert "x27" not in content
    assert "交易市场的" not in content


def test_retag_limits_generation_to_selected_collections(tmp_path):
    class RecordingTagger:
        def __init__(self):
            self.titles = []

        async def generate_tags(self, title, text, language):
            self.titles.append(title)
            return ["风险管理", "交易心理", "执行纪律"]

    selected = tmp_path / "Creator" / "Selected" / "One" / "one.md"
    skipped = tmp_path / "Creator" / "Skipped" / "Two" / "two.md"
    selected.parent.mkdir(parents=True)
    skipped.parent.mkdir(parents=True)
    selected.write_text("---\ntitle: One\n---\n# One\n\nBody", encoding="utf-8")
    skipped.write_text("---\ntitle: Two\n---\n# Two\n\nBody", encoding="utf-8")
    tagger = RecordingTagger()

    payload = asyncio.run(KnowledgeLibrary(tmp_path).retag(tagger, {"Selected"}))

    assert tagger.titles == ["One"]
    assert payload["summary"]["updated"] == 1
    assert payload["summary"]["selected_collections"] == 1
    assert payload["summary"]["selected_documents"] == 1
    assert '  - "topic/风险管理"' in selected.read_text(encoding="utf-8")
    assert skipped.read_text(encoding="utf-8") == "---\ntitle: Two\n---\n# Two\n\nBody"


def test_llm_knowledge_graph_syncs_hierarchy_and_linked_documents(tmp_path):
    class GraphTagger:
        async def generate_knowledge_graph(self, tags, language):
            assert language == "zh-CN"
            assert tags == [
                {"tag": "交易系统", "count": 2},
                {"tag": "因子分析", "count": 1},
                {"tag": "交易策略", "count": 1},
            ]
            return {
                "domains": [
                    {
                        "name": "量化交易",
                        "directions": [
                            {"name": "系统设计", "tags": ["交易系统", "交易策略"]},
                            {"name": "研究方法", "tags": ["因子分析"]},
                        ],
                    }
                ]
            }

    first = tmp_path / "Course" / "one.md"
    second = tmp_path / "Course" / "two.md"
    first.parent.mkdir()
    first.write_text(
        '---\ntitle: One\ntags:\n  - "topic/交易系统"\n  - "topic/因子分析"\n'
        '  - "knowledge/旧领域/旧方向/交易系统"\n---\n# One',
        encoding="utf-8",
    )
    second.write_text(
        "---\ntitle: Two\ntags: [topic/交易系统, topic/交易策略]\n---\n# Two",
        encoding="utf-8",
    )

    payload = asyncio.run(KnowledgeLibrary(tmp_path).generate_knowledge_graph(GraphTagger()))

    assert payload["summary"]["graph_source_tags"] == 3
    assert payload["summary"]["graph_documents_updated"] == 2
    graph = payload["knowledge_graph"]
    assert graph["generated"] is True
    assert graph["source_tag_count"] == 3
    assert graph["associated_documents"] == 2
    assert graph["domains"][0]["name"] == "量化交易"
    assert graph["domains"][0]["directions"][0]["document_count"] == 2
    assert len(graph["domains"][0]["directions"][0]["tags"][0]["documents"]) == 2
    assert '  - "knowledge/量化交易/系统设计/交易系统"' in first.read_text(encoding="utf-8")
    assert "knowledge/旧领域" not in first.read_text(encoding="utf-8")
    assert (tmp_path / KNOWLEDGE_GRAPH_PATH).is_file()


def test_knowledge_graph_uses_only_top_100_topic_tags(tmp_path):
    class RecordingGraphTagger:
        def __init__(self):
            self.tags = []

        async def generate_knowledge_graph(self, tags, language):
            self.tags = tags
            return {
                "domains": [
                    {
                        "name": "Domain",
                        "directions": [
                            {"name": "Direction", "tags": [item["tag"] for item in tags]}
                        ],
                    }
                ]
            }

    path = tmp_path / "note.md"
    tags = [f"topic/tag-{index:03d}" for index in range(105)]
    path.write_text(
        "---\nlanguage: en\ntags:\n" + "\n".join(f'  - "{tag}"' for tag in tags) + "\n---\n# Note",
        encoding="utf-8",
    )
    tagger = RecordingGraphTagger()

    payload = asyncio.run(KnowledgeLibrary(tmp_path).generate_knowledge_graph(tagger))

    assert len(tagger.tags) == 100
    assert tagger.tags[0] == {"tag": "tag-000", "count": 1}
    assert tagger.tags[-1] == {"tag": "tag-099", "count": 1}
    assert payload["knowledge_graph"]["source_tag_count"] == 100
