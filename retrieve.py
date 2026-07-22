from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Iterable

DEFAULT_INPUT_FILE = Path("stardict.csv")
DEFAULT_OUTPUT_FILE = Path("vocabulary.csv")
_TAG_SPLIT_PATTERN = re.compile(r"[\s,，;；]+")


def parse_tags(value: str | Iterable[str]) -> list[str]:
    """Normalize tag text while preserving the user's first-seen order."""
    if isinstance(value, str):
        raw_tags = _TAG_SPLIT_PATTERN.split(value.strip())
    else:
        raw_tags = []
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


def export_vocabulary_by_tags(
    input_file: Path | str,
    output_file: Path | str,
    target_tags: str | Iterable[str],
    *,
    match_all: bool = False,
) -> dict[str, object]:
    """Export ECDICT rows matching one or more tags.

    By default, a word is included when it has any requested tag.  Set
    ``match_all=True`` to require every requested tag.  The source ``tag``
    column is intentionally omitted from the generated learning vocabulary,
    matching the original retrieval script's output format.
    """
    source_path = Path(input_file).expanduser().resolve()
    output_path = Path(output_file).expanduser().resolve()
    tags = parse_tags(target_tags)
    if not tags:
        raise ValueError("请至少输入一个 tag，例如 gre、cet6 或 ielts。")
    if not source_path.is_file():
        raise FileNotFoundError(f"找不到文件：{source_path}")
    if source_path == output_path:
        raise ValueError("源文件和输出文件不能是同一个文件。")

    requested = set(tags)
    total_rows = 0
    exported_rows = 0
    seen_words: set[str] = set()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.name + ".tmp")

    try:
        with (
            source_path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
                errors="replace",
            ) as source,
            temp_path.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as output,
        ):
            reader = csv.DictReader(source)
            if not reader.fieldnames:
                raise ValueError("stardict.csv 没有有效的表头。")
            if "word" not in reader.fieldnames or "tag" not in reader.fieldnames:
                raise ValueError(
                    "CSV 必须包含 word 和 tag 字段。\n"
                    f"实际字段：{reader.fieldnames}"
                )

            fieldnames = [
                field
                for field in reader.fieldnames
                if field and field.strip().casefold() != "tag"
            ]
            writer = csv.DictWriter(
                output,
                fieldnames=fieldnames,
                extrasaction="ignore",
            )
            writer.writeheader()

            for row in reader:
                total_rows += 1
                word = (row.get("word") or "").strip()
                row_tags = set(parse_tags(row.get("tag") or ""))
                matched = requested.issubset(row_tags) if match_all else bool(requested & row_tags)
                if not word or not matched:
                    continue

                word_key = word.casefold()
                if word_key in seen_words:
                    continue
                seen_words.add(word_key)
                writer.writerow({field: row.get(field, "") or "" for field in fieldnames})
                exported_rows += 1

        if exported_rows == 0:
            raise ValueError(
                "没有找到符合条件的词条。请检查 tag 拼写，或切换“任一标签/全部标签”。"
            )
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
        "exported_rows": exported_rows,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从 ECDICT 的 stardict.csv 中按 tag 生成 vocabulary.csv。"
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT_FILE), help="源 stardict.csv")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_FILE), help="输出 CSV")
    parser.add_argument(
        "--tags",
        default="gre",
        help="一个或多个 tag，以空格、英文/中文逗号或分号分隔",
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
    print(f"输出文件：{result['output_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
