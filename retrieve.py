from __future__ import annotations

import argparse
import csv
import re
from collections.abc import Iterable
from pathlib import Path

from vocabulary_tags import (
    ALLOWED_VOCABULARY_TAGS,
    validate_vocabulary_tags,
)

DEFAULT_INPUT_FILE = Path("stardict.csv")
DEFAULT_OUTPUT_FILE = Path("vocabulary.csv")
_TAG_SPLIT_PATTERN = re.compile(r"[\s,，;；]+")


def parse_tags(value: str | Iterable[str]) -> list[str]:
    """Normalize tag text while preserving the first-seen order."""
    if isinstance(value, str):
        raw_tags = _TAG_SPLIT_PATTERN.split(value.strip())
    else:
        raw_tags: list[str] = []
        for item in value:
            raw_tags.extend(_TAG_SPLIT_PATTERN.split(str(item).strip()))

    result: list[str] = []
    seen: set[str] = set()
    for raw_tag in raw_tags:
        tag = raw_tag.strip().casefold()
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def _read_fieldnames(source_path: Path) -> list[str]:
    with source_path.open(
        "r", encoding="utf-8-sig", newline="", errors="replace"
    ) as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError("stardict.csv 没有有效的表头。")
        if "word" not in reader.fieldnames or "tag" not in reader.fieldnames:
            raise ValueError(
                "CSV 必须包含 word 和 tag 字段。\n"
                f"实际字段：{reader.fieldnames}"
            )
        return [field for field in reader.fieldnames if field]


def export_vocabulary_by_tags(
    input_file: Path | str,
    output_file: Path | str,
    target_tags: str | Iterable[str],
    *,
    match_all: bool = False,
) -> dict[str, object]:
    """Export an ECDICT vocabulary using the same tag semantics as the server.

    The server first merges every tag belonging to the same case-insensitive word,
    then applies ``any``/``all`` matching. This desktop implementation performs two
    streaming passes so duplicate rows can contribute tags without loading the full
    ECDICT database into memory. The generated file keeps the source ``tag`` column
    because VITAL Ranker uses tag breadth and tag difficulty.
    """
    source_path = Path(input_file).expanduser().resolve()
    output_path = Path(output_file).expanduser().resolve()
    tags = validate_vocabulary_tags(parse_tags(target_tags))
    if not tags:
        raise ValueError(
            "请至少选择一个考试范围：" + ", ".join(ALLOWED_VOCABULARY_TAGS)
        )
    if not source_path.is_file():
        raise FileNotFoundError(f"找不到文件：{source_path}")
    if source_path == output_path:
        raise ValueError("源文件和输出文件不能是同一个文件。")

    fieldnames = _read_fieldnames(source_path)
    requested = set(tags)
    requested_seen_by_word: dict[str, set[str]] = {}
    display_word_by_key: dict[str, str] = {}
    total_rows = 0

    # Pass 1: union the requested exam tags across duplicate rows.
    with source_path.open(
        "r", encoding="utf-8-sig", newline="", errors="replace"
    ) as source:
        reader = csv.DictReader(source)
        for row in reader:
            total_rows += 1
            word = (row.get("word") or "").strip()
            if not word:
                continue
            row_tags = set(parse_tags(row.get("tag") or ""))
            relevant = requested & row_tags
            if not relevant:
                continue
            key = word.casefold()
            display_word_by_key.setdefault(key, word)
            requested_seen_by_word.setdefault(key, set()).update(relevant)

    if match_all:
        selected_keys = {
            key
            for key, seen_tags in requested_seen_by_word.items()
            if requested.issubset(seen_tags)
        }
    else:
        selected_keys = set(requested_seen_by_word)
    if not selected_keys:
        raise ValueError(
            "没有找到符合条件的词条。请检查考试范围，或切换“任一范围/全部范围”。"
        )

    # Pass 2: merge all source tags and retain the latest field values for selected words.
    rows_by_key: dict[str, dict[str, str]] = {}
    tags_by_key: dict[str, set[str]] = {key: set() for key in selected_keys}
    with source_path.open(
        "r", encoding="utf-8-sig", newline="", errors="replace"
    ) as source:
        reader = csv.DictReader(source)
        for row in reader:
            word = (row.get("word") or "").strip()
            key = word.casefold()
            if not word or key not in selected_keys:
                continue
            normalized = {
                field: str(row.get(field, "") or "") for field in fieldnames
            }
            normalized["word"] = display_word_by_key.get(key, word)
            rows_by_key[key] = normalized
            tags_by_key[key].update(parse_tags(row.get("tag") or ""))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.name + ".tmp")
    try:
        with temp_path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for key in sorted(rows_by_key, key=lambda item: rows_by_key[item]["word"].casefold()):
                row = rows_by_key[key]
                row["tag"] = " ".join(sorted(tags_by_key[key]))
                writer.writerow(row)
        temp_path.replace(output_path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return {
        "input_file": str(source_path),
        "output_file": str(output_path),
        "tags": tags,
        "match_mode": "all" if match_all else "any",
        "total_rows": total_rows,
        "exported_rows": len(rows_by_key),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从 ECDICT 的 stardict.csv 中按考试 tag 生成 VITAL 词库。"
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT_FILE), help="源 stardict.csv")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_FILE), help="输出 CSV")
    parser.add_argument(
        "--tags",
        default="gre",
        help=(
            "一个或多个考试 tag，以空格、英文/中文逗号或分号分隔。可用："
            + ", ".join(ALLOWED_VOCABULARY_TAGS)
        ),
    )
    parser.add_argument(
        "--match-all",
        action="store_true",
        help="要求词条同时具有全部 tag；默认匹配任意一个 tag",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        result = export_vocabulary_by_tags(
            args.input,
            args.output,
            args.tags,
            match_all=args.match_all,
        )
    except (FileNotFoundError, ValueError, OSError, csv.Error) as error:
        print(f"导出失败：{error}")
        return 1

    print(f"扫描词条数：{result['total_rows']}")
    print(f"导出词条数：{result['exported_rows']}")
    print(f"使用 tag：{', '.join(result['tags'])}")
    print(f"匹配方式：{result['match_mode']}")
    print(f"输出文件：{result['output_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
