from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from article_study import run_article_study
from config_manager import get_missing_ai_settings, load_config
from learning_history import (
    HistoryRecord,
    ensure_history_file as _ensure_history_file,
    load_history_records,
    load_learning_state,
    save_history_records,
    record_completed_session,
    utc_now,
)
from vital_ranker import (
    CATEGORY_LABELS,
    CATEGORY_UNSEEN,
    RankerSettings,
    SelectionPlan,
    article_target_word_count,
    build_selection_plan,
)
from vocabulary_store import ensure_registry, get_active_profile
from word_study import run_word_study


class LearningDataError(RuntimeError):
    pass


def ensure_history_file(history_path: Path) -> None:
    """Backward-compatible wrapper for the pre-v1.4 desktop API."""
    _ensure_history_file(history_path)


def load_history(history_path: Path) -> dict[str, int]:
    """Load legacy ``word -> mastery`` data from either history format."""
    try:
        records = load_history_records(history_path)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise LearningDataError(str(exc)) from exc
    return {record.word: record.mastery_level for record in records.values()}


def save_history(history_path: Path, history: dict[str, int]) -> None:
    """Preserve the old public helper while writing the extended summary format."""
    try:
        existing = load_history_records(history_path)
    except (OSError, ValueError, UnicodeDecodeError):
        existing = {}
    now = utc_now()
    records: dict[str, HistoryRecord] = {}
    for word, raw_level in history.items():
        clean_word = str(word).strip()
        if not clean_word:
            continue
        try:
            level = max(1, min(5, int(raw_level)))
        except (TypeError, ValueError):
            level = 1
        previous = existing.get(clean_word.casefold())
        records[clean_word.casefold()] = HistoryRecord(
            word=clean_word,
            mastery_level=level,
            study_count=previous.study_count if previous else 1,
            last_first_score=previous.last_first_score if previous else level,
            last_second_score=previous.last_second_score if previous else level,
            first_studied_at=previous.first_studied_at if previous else now,
            last_studied_at=previous.last_studied_at if previous else now,
        )
    save_history_records(history_path, records)


def load_vocabulary(vocabulary_path: Path) -> list[dict[str, str]]:
    if not vocabulary_path.exists():
        raise LearningDataError(
            f"未找到 {vocabulary_path.name}。请先在“管理词库与学习历史”中创建并启用词库。"
        )
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            with vocabulary_path.open("r", encoding=encoding, newline="") as file:
                reader = csv.DictReader(file)
                if not reader.fieldnames or "word" not in reader.fieldnames:
                    raise LearningDataError(f"{vocabulary_path.name} 必须包含 word 列。")
                result: list[dict[str, str]] = []
                seen: set[str] = set()
                for row in reader:
                    word = (row.get("word") or "").strip()
                    key = word.casefold()
                    if not word or key in seen:
                        continue
                    seen.add(key)
                    normalized = {
                        str(field): str(value or "")
                        for field, value in row.items()
                        if field is not None
                    }
                    normalized["word"] = word
                    result.append(normalized)
                if not result:
                    raise LearningDataError(f"{vocabulary_path.name} 中没有可用单词。")
                return result
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    raise LearningDataError(
        f"无法读取 {vocabulary_path.name}，请将它保存为 UTF-8 CSV。"
    ) from last_error


def _merge_scores(first_score: int, second_score: int) -> int:
    return max(1, min(5, math.floor((first_score + 2 * second_score) / 3)))


def _serialize_plan(plan: SelectionPlan, vocabulary_id: str) -> dict[str, Any]:
    return {
        "vocabulary_id": vocabulary_id,
        "policy_version": plan.policy_version,
        "summary": plan.summary,
        "selected": [
            {
                "word": item.spelling,
                "category": item.category,
                "category_label": CATEGORY_LABELS.get(item.category, item.category),
                "score": round(item.score, 8),
                "selected_by": item.selected_by,
                "selection_probability": item.selection_probability,
                "display_order": item.display_order,
                "second_display_order": item.second_display_order,
                "features": item.features,
                "reasons": item.reasons,
            }
            for item in plan.selected
        ],
    }


def _append_selection_audit(
    base_dir: Path, plan: SelectionPlan, vocabulary_id: str
) -> None:
    path = base_dir / "selectionAudit.jsonl"
    payload = _serialize_plan(plan, vocabulary_id)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def select_words(
    vocabulary: list[dict[str, str]],
    history: dict[str, int],
    total_count: int,
    new_count: int,
) -> list[dict[str, str]]:
    """Compatibility helper for older imports.

    Unlike the old implementation, mastery level 1 is still a review word. Only
    words absent from ``history`` count as new. Detailed desktop sessions use
    :func:`build_selection_plan` with timestamps and two-score history.
    """
    records = {
        word.casefold(): HistoryRecord(
            word=word,
            mastery_level=max(1, min(5, int(level))),
            study_count=1,
            last_first_score=max(1, min(5, int(level))),
            last_second_score=max(1, min(5, int(level))),
        )
        for word, level in history.items()
    }
    plan = build_selection_plan(
        vocabulary,
        records,
        {},
        [],
        total_count,
        new_count,
        new_word_mode="fixed",
    )
    return plan.rows_first_order


def run_learning_round(parent: Any, base_dir: Path | str) -> dict[str, Any] | None:
    base = Path(base_dir)
    vocabulary_path = base / "vocabulary.csv"
    config = load_config(base)
    missing_ai = get_missing_ai_settings(config)
    if missing_ai:
        raise LearningDataError(
            "请先在设置中填写完整的 AI 信息：" + "、".join(missing_ai)
        )

    registry = ensure_registry(base)
    active_profile = get_active_profile(base)
    if active_profile is None or not registry.get("active_id"):
        raise LearningDataError("尚未启用词库，请先创建或选择当前词库。")

    vocabulary = load_vocabulary(vocabulary_path)
    records, events_by_word, session_dates = load_learning_state(base)
    plan = build_selection_plan(
        vocabulary,
        records,
        events_by_word,
        session_dates,
        int(config["words_per_round"]),
        int(config["new_words_per_round"]),
        new_word_mode=str(config.get("new_word_mode", "fixed")),
    )
    if not plan.selected:
        raise LearningDataError("没有可供学习的词汇。")

    try:
        _append_selection_audit(base, plan, str(active_profile["id"]))
    except OSError:
        # Audit failure must not block the core learning flow.
        pass

    first_rows = plan.rows_first_order
    second_rows = plan.rows_second_order
    first_scores = run_word_study(parent, first_rows, config, "第一次词义学习")
    if first_scores is None:
        return None

    target_word_count = article_target_word_count(plan, RankerSettings())
    if not run_article_study(
        parent,
        first_rows,
        config,
        target_word_count=target_word_count,
    ):
        return None

    second_scores = run_word_study(parent, second_rows, config, "第二次词义学习")
    if second_scores is None:
        return None

    session_id, _records = record_completed_session(
        base,
        vocabulary_id=str(active_profile["id"]),
        selected=plan.selected,
        first_scores=first_scores,
        second_scores=second_scores,
        merge_score=_merge_scores,
    )
    updated: dict[str, int] = {}
    for item in plan.selected:
        first = first_scores.get(item.spelling, 1)
        second = second_scores.get(item.spelling, 1)
        updated[item.spelling] = _merge_scores(first, second)

    actual_counts = dict(plan.summary.get("actual_category_counts", {}))
    unseen_count = int(actual_counts.get(CATEGORY_UNSEEN, 0))
    return {
        "session_id": session_id,
        "word_count": len(plan.selected),
        "new_word_count": unseen_count,
        "review_word_count": len(plan.selected) - unseen_count,
        "updated_scores": updated,
        "selected_words": [item.spelling for item in plan.selected],
        "article_target_word_count": target_word_count,
        "new_word_mode": plan.summary.get("new_word_mode", "fixed"),
        "effective_unseen_count": plan.summary.get("effective_unseen_count", unseen_count),
    }
