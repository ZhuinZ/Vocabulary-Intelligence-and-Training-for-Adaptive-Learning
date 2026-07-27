from __future__ import annotations

from collections.abc import Iterable

ALLOWED_VOCABULARY_TAGS: tuple[str, ...] = (
    "zk",
    "gk",
    "cet4",
    "cet6",
    "ky",
    "ielts",
    "toefl",
    "gre",
)
ALLOWED_VOCABULARY_TAG_SET: frozenset[str] = frozenset(ALLOWED_VOCABULARY_TAGS)

VOCABULARY_TAG_LABELS: dict[str, str] = {
    "zk": "中考",
    "gk": "高考",
    "cet4": "大学英语四级",
    "cet6": "大学英语六级",
    "ky": "考研英语",
    "ielts": "雅思",
    "toefl": "托福",
    "gre": "GRE",
}

DEFAULT_TAG_DIFFICULTY: dict[str, float] = {
    "zk": 0.15,
    "gk": 0.25,
    "cet4": 0.35,
    "cet6": 0.50,
    "ky": 0.50,
    "ielts": 0.65,
    "toefl": 0.65,
    "gre": 0.85,
}


def vocabulary_tag_label(value: object) -> str:
    code = str(value).strip().casefold()
    return VOCABULARY_TAG_LABELS.get(code, str(value))


def validate_vocabulary_tags(tags: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in tags:
        tag = str(value).strip().casefold()
        if tag and tag not in seen:
            seen.add(tag)
            normalized.append(tag)
    disallowed = sorted(set(normalized) - ALLOWED_VOCABULARY_TAG_SET)
    if disallowed:
        raise ValueError(
            "不允许使用这些词库 tag："
            + ", ".join(disallowed)
            + "。可用 tag："
            + ", ".join(ALLOWED_VOCABULARY_TAGS)
        )
    return normalized
