from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

HISTORY_HEADERS = [
    "单词",
    "熟练程度",
    "学习次数",
    "最近第一次评分",
    "最近第二次评分",
    "首次学习时间",
    "最近学习时间",
]
EVENT_HEADERS = [
    "会话ID",
    "词库ID",
    "单词",
    "第一次评分",
    "第二次评分",
    "最终熟练程度",
    "完成时间",
    "第一轮顺序",
    "第二轮顺序",
]


@dataclass
class HistoryRecord:
    word: str
    mastery_level: int
    study_count: int = 1
    last_first_score: int | None = None
    last_second_score: int | None = None
    first_studied_at: datetime | None = None
    last_studied_at: datetime | None = None


@dataclass(frozen=True)
class LearningEvent:
    word_key: str
    word: str
    first_score: int
    second_score: int
    final_mastery: int
    completed_at: datetime
    display_order: int
    second_display_order: int
    session_id: str
    vocabulary_id: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return as_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def format_datetime(value: datetime | None) -> str:
    return as_utc(value).isoformat() if value else ""


def _bounded_score(value: object, default: int = 1) -> int:
    try:
        score = int(str(value).strip())
    except (TypeError, ValueError):
        score = default
    return min(5, max(1, score))


def _nonnegative_int(value: object, default: int = 0) -> int:
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return default


def ensure_history_file(history_path: Path) -> None:
    if history_path.exists():
        return
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("w", encoding="utf-8-sig", newline="") as file:
        csv.DictWriter(file, fieldnames=HISTORY_HEADERS).writeheader()


def ensure_events_file(events_path: Path) -> None:
    if events_path.exists():
        return
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("w", encoding="utf-8-sig", newline="") as file:
        csv.DictWriter(file, fieldnames=EVENT_HEADERS).writeheader()


def _row_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def load_history_records(history_path: Path) -> dict[str, HistoryRecord]:
    ensure_history_file(history_path)
    records: dict[str, HistoryRecord] = {}
    fallback_time = datetime.fromtimestamp(history_path.stat().st_mtime, timezone.utc)
    with history_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            return records
        aliases = set(reader.fieldnames)
        if not ({"单词", "word"} & aliases):
            raise ValueError(f"{history_path.name} 必须包含“单词”或 word 列。")
        if not ({"熟练程度", "mastery_level"} & aliases):
            raise ValueError(
                f"{history_path.name} 必须包含“熟练程度”或 mastery_level 列。"
            )
        for row in reader:
            word = _row_value(row, "单词", "word").strip()
            if not word:
                continue
            mastery = _bounded_score(_row_value(row, "熟练程度", "mastery_level"))
            study_count = max(
                1,
                _nonnegative_int(_row_value(row, "学习次数", "study_count"), 1),
            )
            first = _row_value(row, "最近第一次评分", "last_first_score")
            second = _row_value(row, "最近第二次评分", "last_second_score")
            first_at = parse_datetime(
                _row_value(row, "首次学习时间", "first_studied_at")
            )
            last_at = parse_datetime(
                _row_value(row, "最近学习时间", "last_studied_at")
            )
            records[word.casefold()] = HistoryRecord(
                word=word,
                mastery_level=mastery,
                study_count=study_count,
                last_first_score=_bounded_score(first, mastery) if first else mastery,
                last_second_score=_bounded_score(second, mastery) if second else mastery,
                first_studied_at=first_at or fallback_time,
                last_studied_at=last_at or fallback_time,
            )
    return records


def load_learning_events(events_path: Path) -> list[LearningEvent]:
    if not events_path.exists():
        return []
    result: list[LearningEvent] = []
    with events_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            return []
        for row in reader:
            word = _row_value(row, "单词", "word").strip()
            completed = parse_datetime(_row_value(row, "完成时间", "completed_at"))
            if not word or completed is None:
                continue
            first = _bounded_score(_row_value(row, "第一次评分", "first_score"))
            second = _bounded_score(_row_value(row, "第二次评分", "second_score"))
            final = _bounded_score(
                _row_value(row, "最终熟练程度", "final_mastery"), second
            )
            result.append(
                LearningEvent(
                    word_key=word.casefold(),
                    word=word,
                    first_score=first,
                    second_score=second,
                    final_mastery=final,
                    completed_at=completed,
                    display_order=_nonnegative_int(
                        _row_value(row, "第一轮顺序", "display_order"), 0
                    ),
                    second_display_order=_nonnegative_int(
                        _row_value(row, "第二轮顺序", "second_display_order"), 0
                    ),
                    session_id=_row_value(row, "会话ID", "session_id").strip(),
                    vocabulary_id=_row_value(row, "词库ID", "vocabulary_id").strip(),
                )
            )
    result.sort(key=lambda item: (item.completed_at, item.display_order))
    return result


def load_learning_state(
    base_dir: Path | str,
) -> tuple[
    dict[str, HistoryRecord],
    dict[str, list[LearningEvent]],
    list[datetime],
]:
    base = Path(base_dir)
    history_path = base / "learningHistory.csv"
    events_path = base / "learningEvents.csv"
    records = load_history_records(history_path)
    events = load_learning_events(events_path)
    events_by_word: dict[str, list[LearningEvent]] = {}
    session_dates_by_id: dict[str, datetime] = {}
    for event in events:
        events_by_word.setdefault(event.word_key, []).append(event)
        session_key = event.session_id or event.completed_at.isoformat()
        previous = session_dates_by_id.get(session_key)
        if previous is None or event.completed_at > previous:
            session_dates_by_id[session_key] = event.completed_at

    # Event rows are the authoritative detailed log. They also repair summary data
    # if an older desktop version has overwritten learningHistory.csv with two columns.
    for word_key, word_events in events_by_word.items():
        latest = word_events[-1]
        first_time = word_events[0].completed_at
        existing = records.get(word_key)
        if existing is None or (
            existing.last_studied_at is None
            or latest.completed_at >= existing.last_studied_at
        ):
            records[word_key] = HistoryRecord(
                word=latest.word,
                mastery_level=latest.final_mastery,
                study_count=max(len(word_events), existing.study_count if existing else 0),
                last_first_score=latest.first_score,
                last_second_score=latest.second_score,
                first_studied_at=(
                    min(first_time, existing.first_studied_at)
                    if existing and existing.first_studied_at
                    else first_time
                ),
                last_studied_at=latest.completed_at,
            )
    session_dates = sorted(session_dates_by_id.values(), reverse=True)
    return records, events_by_word, session_dates


def save_history_records(history_path: Path, records: dict[str, HistoryRecord]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = history_path.with_suffix(".csv.tmp")
    with temp_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=HISTORY_HEADERS)
        writer.writeheader()
        for key in sorted(records, key=str.casefold):
            record = records[key]
            writer.writerow(
                {
                    "单词": record.word,
                    "熟练程度": record.mastery_level,
                    "学习次数": max(1, record.study_count),
                    "最近第一次评分": record.last_first_score or "",
                    "最近第二次评分": record.last_second_score or "",
                    "首次学习时间": format_datetime(record.first_studied_at),
                    "最近学习时间": format_datetime(record.last_studied_at),
                }
            )
    temp_path.replace(history_path)


def _write_events(events_path: Path, events: Iterable[LearningEvent]) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = events_path.with_suffix(".csv.tmp")
    with temp_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=EVENT_HEADERS)
        writer.writeheader()
        for event in events:
            writer.writerow(
                {
                    "会话ID": event.session_id,
                    "词库ID": event.vocabulary_id,
                    "单词": event.word,
                    "第一次评分": event.first_score,
                    "第二次评分": event.second_score,
                    "最终熟练程度": event.final_mastery,
                    "完成时间": format_datetime(event.completed_at),
                    "第一轮顺序": event.display_order,
                    "第二轮顺序": event.second_display_order,
                }
            )
    temp_path.replace(events_path)


def record_completed_session(
    base_dir: Path | str,
    *,
    vocabulary_id: str,
    selected: Iterable[object],
    first_scores: dict[str, int],
    second_scores: dict[str, int],
    merge_score: Callable[[int, int], int],
) -> tuple[str, dict[str, HistoryRecord]]:
    base = Path(base_dir)
    history_path = base / "learningHistory.csv"
    events_path = base / "learningEvents.csv"
    records, _events_by_word, _session_dates = load_learning_state(base)
    existing_events = load_learning_events(events_path)
    completed_at = utc_now()
    session_id = uuid4().hex
    new_events: list[LearningEvent] = []

    for item in selected:
        word = str(getattr(item, "spelling", "")).strip()
        if not word:
            continue
        first = _bounded_score(first_scores.get(word, 1))
        second = _bounded_score(second_scores.get(word, 1))
        final = _bounded_score(merge_score(first, second))
        key = word.casefold()
        previous = records.get(key)
        records[key] = HistoryRecord(
            word=word,
            mastery_level=final,
            study_count=(previous.study_count + 1) if previous else 1,
            last_first_score=first,
            last_second_score=second,
            first_studied_at=(
                previous.first_studied_at
                if previous and previous.first_studied_at
                else completed_at
            ),
            last_studied_at=completed_at,
        )
        new_events.append(
            LearningEvent(
                word_key=key,
                word=word,
                first_score=first,
                second_score=second,
                final_mastery=final,
                completed_at=completed_at,
                display_order=int(getattr(item, "display_order", 0) or 0),
                second_display_order=int(
                    getattr(item, "second_display_order", 0) or 0
                ),
                session_id=session_id,
                vocabulary_id=vocabulary_id,
            )
        )

    save_history_records(history_path, records)
    _write_events(events_path, [*existing_events, *new_events])
    return session_id, records


def clear_learning_history(base_dir: Path | str) -> None:
    base = Path(base_dir)
    history_path = base / "learningHistory.csv"
    events_path = base / "learningEvents.csv"
    save_history_records(history_path, {})
    _write_events(events_path, [])


def vocabulary_ids_used_in_history(base_dir: Path | str) -> set[str]:
    return {
        event.vocabulary_id
        for event in load_learning_events(Path(base_dir) / "learningEvents.csv")
        if event.vocabulary_id
    }
