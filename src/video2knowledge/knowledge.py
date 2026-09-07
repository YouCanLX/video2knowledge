from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .ports import TextEnricher

FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
WORD_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+._-]{2,}|[\u4e00-\u9fff]{2,8}")
LEGACY_TAG_LINE = re.compile(r"(?m)^Tags:(?:\s+`[^`\n]+`)+\s*\n?")
HEX_COLOR_TAG = re.compile(r"[0-9a-f]{6}", re.IGNORECASE)
TAG_SIMILARITY_THRESHOLD = 0.9
GENERIC_TAG_SUFFIXES = (
    "介绍",
    "入门",
    "基础",
    "差异",
    "实践",
    "应用",
    "方法",
    "方式",
    "技巧",
    "指南",
    "概念",
    "analysis",
    "basics",
    "concepts",
    "guide",
    "methods",
    "practice",
)


def normalize_tag(value: str) -> str:
    """Return an Obsidian-friendly tag segment while retaining CJK text."""
    value = value.strip().strip("#").casefold()
    value = re.sub(r"[^\w\-+/\u4e00-\u9fff ]+", "", value)
    value = re.sub(r"[\s_]+", "-", value).strip("-/")
    return re.sub(r"/{2,}", "/", value)


def obsidian_tags(
    topic_tags: list[str] | None = None,
    *,
    author: str = "",
    collection: str = "",
) -> list[str]:
    tags = ["video2knowledge"]
    for prefix, values in (
        ("creator", [author]),
        ("collection", [collection]),
        ("topic", topic_tags or []),
    ):
        for value in values:
            normalized = normalize_tag(value)
            if normalized:
                tags.append(f"{prefix}/{normalized}")
    return list(dict.fromkeys(tags))


def _tag_fingerprint(tag: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", tag).casefold().replace("的", "")


def _useful_topic_tag(tag: str) -> bool:
    return (
        not HEX_COLOR_TAG.fullmatch(tag)
        and tag != "x27"
        and not tag.isdecimal()
        and not tag.startswith(("的", "和", "与", "或"))
        and not tag.endswith(("的", "和", "与", "或"))
    )


def _similar_tags(left: str, right: str) -> bool:
    left_key, right_key = _tag_fingerprint(left), _tag_fingerprint(right)
    if left_key == right_key:
        return True
    shorter, longer = sorted((left_key, right_key), key=len)
    if len(shorter) < 4:
        return False
    if longer.startswith(shorter) and longer.removeprefix(shorter) in GENERIC_TAG_SUFFIXES:
        return True
    return (
        left_key[0] == right_key[0]
        and SequenceMatcher(None, left_key, right_key).ratio() >= TAG_SIMILARITY_THRESHOLD
    )


def merge_similar_tags(tags: list[str]) -> dict[str, str]:
    """Map near-duplicate topic tags to a concise canonical spelling."""
    counts = Counter(tags)
    ordered = sorted(counts, key=lambda tag: (len(_tag_fingerprint(tag)), -counts[tag], tag))
    canonical: list[str] = []
    aliases: dict[str, str] = {}
    for tag in ordered:
        match = next((candidate for candidate in canonical if _similar_tags(tag, candidate)), None)
        if match is None:
            canonical.append(tag)
        elif tag != match:
            aliases[tag] = match
    return aliases


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


def _remove_legacy_tag_line(markdown: str) -> str:
    return LEGACY_TAG_LINE.sub("", markdown, count=1)


def _metadata_for(path: Path) -> dict[str, Any]:
    candidates = list((path.parent / "assets").glob("*.metadata.json"))
    for candidate in candidates:
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


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

    def build(self) -> dict[str, Any]:
        documents: list[dict[str, Any]] = []
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
            tags = list(dict.fromkeys(normalize_tag(tag) for tag in existing))
            tags = [tag for tag in tags if tag]
            body = FRONTMATTER.sub("", markdown, count=1)
            documents.append(
                {
                    "id": path.relative_to(self.root).as_posix(),
                    "title": title,
                    "author": author,
                    "collection": collection,
                    "language": str(fields.get("language") or metadata.get("language") or "zh-CN"),
                    "tags": tags,
                    "word_count": len(WORD_TOKEN.findall(body)),
                    "excerpt": _excerpt(markdown),
                    "headings": re.findall(r"^#{2,3}\s+(.+)$", body, re.MULTILINE)[:8],
                }
            )
        return self._payload(documents, 0, [])

    async def retag(
        self, tagger: TextEnricher, collections: set[str] | None = None
    ) -> dict[str, Any]:
        """Replace prior tags only after successful LLM classification of each document."""
        documents = [
            document
            for collection in self.build()["collections"]
            for document in collection["documents"]
            if collections is None or document["collection"] in collections
        ]
        updated = 0
        failures: list[dict[str, str]] = []
        generated: dict[str, list[str]] = {}
        semaphore = asyncio.Semaphore(3)

        async def classify(document: dict[str, Any]) -> None:
            try:
                path = self.root / document["id"]
                markdown = await asyncio.to_thread(path.read_text, encoding="utf-8")
                markdown_without_legacy_tags = _remove_legacy_tag_line(markdown)
                body = FRONTMATTER.sub("", markdown_without_legacy_tags, count=1)
                async with semaphore:
                    topics = await tagger.generate_tags(
                        document["title"], body, document["language"]
                    )
                normalized_topics = list(
                    dict.fromkeys(
                        tag
                        for topic in topics
                        if (tag := normalize_tag(topic)) and _useful_topic_tag(tag)
                    )
                )
                if not 3 <= len(normalized_topics) <= 6:
                    raise ValueError("The LLM must return 3-6 distinct tags")
                generated[document["id"]] = normalized_topics
            except Exception as exc:  # noqa: BLE001 - preserve the original Markdown and tags
                failures.append({"id": document["id"], "error": str(exc)})

        await asyncio.gather(*(classify(document) for document in documents))
        aliases = merge_similar_tags([tag for topics in generated.values() for tag in topics])
        for document in documents:
            topics = generated.get(document["id"])
            if topics is None:
                continue
            path = self.root / document["id"]
            try:
                markdown = await asyncio.to_thread(path.read_text, encoding="utf-8")
                markdown_without_legacy_tags = _remove_legacy_tag_line(markdown)
                merged_topics = list(dict.fromkeys(aliases.get(tag, tag) for tag in topics))
                if len(merged_topics) < 3:
                    raise ValueError("Similar-tag merging left fewer than 3 distinct tags")
                tags = obsidian_tags(
                    merged_topics,
                    author=document["author"],
                    collection=document["collection"],
                )
                rewritten = _write_tags(markdown_without_legacy_tags, tags)
                if rewritten != markdown:
                    await asyncio.to_thread(path.write_text, rewritten, encoding="utf-8")
                    updated += 1
            except Exception as exc:  # noqa: BLE001 - preserve the original Markdown and tags
                failures.append({"id": document["id"], "error": str(exc)})
        refreshed = self.build()
        refreshed["summary"]["updated"] = updated
        refreshed["summary"]["merged_tags"] = len(aliases)
        refreshed["summary"]["failed"] = len(failures)
        refreshed["summary"]["selected_collections"] = len(
            {document["collection"] for document in documents}
        )
        refreshed["summary"]["selected_documents"] = len(documents)
        refreshed["failures"] = failures
        return refreshed

    @staticmethod
    def _payload(
        documents: list[dict[str, Any]], updated: int, failures: list[dict[str, str]]
    ) -> dict[str, Any]:
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
                "failed": len(failures),
            },
            "collections": collections,
            "tag_tree": tree_list(tree),
            "graph": {"nodes": nodes, "edges": edges},
            "failures": failures,
        }
