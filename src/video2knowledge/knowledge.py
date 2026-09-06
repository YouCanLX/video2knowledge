from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
TAG_TOKEN = re.compile(r"(?<![\w/])#([\w\-/\u4e00-\u9fff]+)")
WORD_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+._-]{2,}|[\u4e00-\u9fff]{2,8}")
STOP_WORDS = {
    "about",
    "actionable",
    "after",
    "also",
    "and",
    "core",
    "explore",
    "from",
    "full",
    "further",
    "insights",
    "into",
    "questions",
    "suggestions",
    "summary",
    "that",
    "the",
    "this",
    "timeline",
    "transcript",
    "video",
    "with",
    "your",
    "一个",
    "这个",
    "我们",
    "可以",
    "以及",
    "进行",
    "内容",
    "视频",
    "知识",
}


def normalize_tag(value: str) -> str:
    """Return an Obsidian-friendly tag segment while retaining CJK text."""
    value = value.strip().strip("#").casefold()
    value = re.sub(r"[^\w\-+/\u4e00-\u9fff ]+", "", value)
    value = re.sub(r"[\s_]+", "-", value).strip("-/")
    return re.sub(r"/{2,}", "/", value)


def obsidian_tags(
    source_tags: list[str] | None = None,
    *,
    author: str = "",
    collection: str = "",
    keywords: list[str] | None = None,
) -> list[str]:
    tags = ["video2knowledge"]
    for prefix, values in (
        ("creator", [author]),
        ("collection", [collection]),
        ("topic", [*(source_tags or []), *(keywords or [])]),
    ):
        for value in values:
            normalized = normalize_tag(value)
            if normalized:
                tags.append(f"{prefix}/{normalized}")
    return list(dict.fromkeys(tags))


def _frontmatter_values(markdown: str) -> dict[str, Any]:
    match = FRONTMATTER.match(markdown)
    if not match:
        return {}
    lines = match.group(1).splitlines()
    values: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        field = re.match(r"^([\w-]+):\s*(.*)$", line)
        if not field:
            index += 1
            continue
        key, raw = field.groups()
        if key == "tags" and not raw:
            items: list[str] = []
            index += 1
            while index < len(lines) and (item := re.match(r"^\s+-\s+(.+)$", lines[index])):
                items.append(item.group(1).strip().strip("\"'"))
                index += 1
            values[key] = items
            continue
        if key == "tags" and raw.startswith("[") and raw.endswith("]"):
            values[key] = [part.strip().strip("\"'") for part in raw[1:-1].split(",")]
        else:
            values[key] = raw.strip().strip("\"'")
        index += 1
    return values


def _write_tags(markdown: str, tags: list[str]) -> str:
    tag_lines = ["tags:", *(f'  - "{tag}"' for tag in tags)]
    match = FRONTMATTER.match(markdown)
    if not match:
        return "---\n" + "\n".join(tag_lines) + "\n---\n\n" + markdown.lstrip()
    lines = match.group(1).splitlines()
    output: list[str] = []
    index = 0
    inserted = False
    while index < len(lines):
        if re.match(r"^tags:\s*", lines[index]):
            output.extend(tag_lines)
            inserted = True
            index += 1
            while index < len(lines) and re.match(r"^\s+-\s+", lines[index]):
                index += 1
            continue
        output.append(lines[index])
        index += 1
    if not inserted:
        output.extend(tag_lines)
    return "---\n" + "\n".join(output) + "\n---\n" + markdown[match.end() :]


def _metadata_for(path: Path) -> dict[str, Any]:
    candidates = list((path.parent / "assets").glob("*.metadata.json"))
    for candidate in candidates:
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def _keywords(markdown: str, title: str, limit: int = 4) -> list[str]:
    body = FRONTMATTER.sub("", markdown, count=1)
    headings = " ".join(re.findall(r"^#{1,3}\s+(.+)$", body, re.MULTILINE))
    tokens = [normalize_tag(token) for token in WORD_TOKEN.findall(f"{title} {headings}")]
    counts = Counter(token for token in tokens if token and token not in STOP_WORDS)
    return [token for token, _ in counts.most_common(limit)]


def _collection_for(
    path: Path, root: Path, metadata: dict[str, Any], fields: dict[str, Any]
) -> str:
    video = metadata.get("video") or {}
    explicit = str(fields.get("collection") or video.get("collection_title") or "").strip()
    if explicit:
        return explicit
    if video:
        return "Unfiled"
    relative = path.relative_to(root)
    if len(relative.parts) >= 3:
        return relative.parts[-3]
    if len(relative.parts) >= 2:
        return relative.parts[0]
    return "Unfiled"


def _excerpt(markdown: str, limit: int = 220) -> str:
    body = FRONTMATTER.sub("", markdown, count=1)
    body = re.sub(r"<[^>]+>|[#>*`_[\]()~-]", " ", body)
    return re.sub(r"\s+", " ", body).strip()[:limit]


class KnowledgeLibrary:
    """Scan and enrich the Markdown library without introducing another source of truth."""

    def __init__(self, root: Path):
        self.root = root

    def build(self, *, write_tags: bool = False) -> dict[str, Any]:
        documents: list[dict[str, Any]] = []
        updated = 0
        for path in sorted(self.root.rglob("*.md")) if self.root.exists() else []:
            if any(
                part.startswith(".") or part == "assets"
                for part in path.relative_to(self.root).parts
            ):
                continue
            try:
                markdown = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            fields = _frontmatter_values(markdown)
            metadata = _metadata_for(path)
            video = metadata.get("video") or {}
            heading = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
            title = str(
                fields.get("title")
                or video.get("title")
                or (heading.group(1) if heading else path.stem)
            )
            author = str(fields.get("author") or video.get("author") or "")
            collection = _collection_for(path, self.root, metadata, fields)
            existing = fields.get("tags") or []
            if isinstance(existing, str):
                existing = [existing]
            inline = TAG_TOKEN.findall(FRONTMATTER.sub("", markdown, count=1))
            generated = obsidian_tags(
                author=author,
                collection=collection,
                keywords=_keywords(markdown, title),
            )
            tags = list(
                dict.fromkeys(normalize_tag(tag) for tag in [*existing, *inline, *generated])
            )
            tags = [tag for tag in tags if tag]
            if write_tags and tags != list(existing):
                path.write_text(_write_tags(markdown, tags), encoding="utf-8")
                updated += 1
            body = FRONTMATTER.sub("", markdown, count=1)
            documents.append(
                {
                    "id": path.relative_to(self.root).as_posix(),
                    "title": title,
                    "author": author,
                    "collection": collection,
                    "tags": tags,
                    "word_count": len(WORD_TOKEN.findall(body)),
                    "excerpt": _excerpt(markdown),
                    "headings": re.findall(r"^#{2,3}\s+(.+)$", body, re.MULTILINE)[:8],
                }
            )
        return self._payload(documents, updated)

    @staticmethod
    def _payload(documents: list[dict[str, Any]], updated: int) -> dict[str, Any]:
        tag_counts = Counter(tag for document in documents for tag in document["tags"])
        grouped: dict[str, list[dict[str, Any]]] = {}
        for document in documents:
            grouped.setdefault(document["collection"], []).append(document)
        collections = []
        for name, members in sorted(grouped.items(), key=lambda item: item[0].casefold()):
            counts = Counter(tag for member in members for tag in member["tags"])
            collections.append(
                {
                    "name": name,
                    "document_count": len(members),
                    "word_count": sum(member["word_count"] for member in members),
                    "top_tags": [tag for tag, _ in counts.most_common(8)],
                    "documents": members,
                }
            )
        tree: dict[str, Any] = {}
        for tag, count in sorted(tag_counts.items()):
            branch = tree
            parts = tag.split("/")
            for index, part in enumerate(parts):
                node = branch.setdefault(
                    part,
                    {
                        "name": part,
                        "path": "/".join(parts[: index + 1]),
                        "count": 0,
                        "children": {},
                    },
                )
                node["count"] += count
                branch = node["children"]

        def tree_list(branch: dict[str, Any]) -> list[dict[str, Any]]:
            return [
                {**node, "children": tree_list(node["children"])}
                for node in sorted(branch.values(), key=lambda item: (-item["count"], item["name"]))
            ]

        nodes = [
            {"id": f"document:{doc['id']}", "label": doc["title"], "kind": "document"}
            for doc in documents
        ]
        nodes += [
            {"id": f"tag:{tag}", "label": tag, "kind": "tag", "count": count}
            for tag, count in tag_counts.most_common(40)
        ]
        visible_tags = {node["label"] for node in nodes if node["kind"] == "tag"}
        edges = [
            {"source": f"document:{doc['id']}", "target": f"tag:{tag}"}
            for doc in documents
            for tag in doc["tags"]
            if tag in visible_tags
        ]
        return {
            "summary": {
                "documents": len(documents),
                "collections": len(collections),
                "tags": len(tag_counts),
                "words": sum(document["word_count"] for document in documents),
                "updated": updated,
            },
            "collections": collections,
            "tag_tree": tree_list(tree),
            "graph": {"nodes": nodes, "edges": edges},
        }
