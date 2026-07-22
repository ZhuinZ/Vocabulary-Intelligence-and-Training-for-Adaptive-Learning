from __future__ import annotations

import csv
import math
import random
from pathlib import Path
from typing import Any

from article_study import run_article_study
from config_manager import get_missing_ai_settings, load_config
from word_study import run_word_study

HISTORY_HEADERS = ["单词", "熟练程度"]
REVIEW_WEIGHTS = {2: 20, 3: 10, 4: 5, 5: 1}


class LearningDataError(RuntimeError):
    pass


def ensure_history_file(history_path: Path) -> None:
    if history_path.exists():
        return
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=HISTORY_HEADERS)
        writer.writeheader()


def load_history(history_path: Path) -> dict[str, int]:
    ensure_history_file(history_path)
    history: dict[str, int] = {}
    try:
        with history_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames is None or not set(HISTORY_HEADERS).issubset(reader.fieldnames):
                raise LearningDataError(
                    f"{history_path.name} 必须包含“单词”和“熟练程度”两列。"
                )
            for row in reader:
                word = (row.get("单词") or "").strip()
                if not word:
                    continue
                try:
                    level = int(row.get("熟练程度", "1"))
                except ValueError:
                    level = 1
                history[word] = min(5, max(1, level))
    except UnicodeDecodeError as exc:
        raise LearningDataError(
            f"无法以 UTF-8 读取 {history_path.name}，请将文件保存为 UTF-8 CSV。"
        ) from exc
    return history


def save_history(history_path: Path, history: dict[str, int]) -> None:
    temp_path = history_path.with_suffix(".csv.tmp")
    with temp_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=HISTORY_HEADERS)
        writer.writeheader()
        for word in sorted(history, key=str.casefold):
            writer.writerow({"单词": word, "熟练程度": history[word]})
    temp_path.replace(history_path)


def load_vocabulary(vocabulary_path: Path) -> list[dict[str, str]]:
    if not vocabulary_path.exists():
        raise LearningDataError(
            f"未找到 {vocabulary_path.name}。请把它放在主程序所在目录。"
        )

    encodings = ("utf-8-sig", "utf-8")
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            with vocabulary_path.open("r", encoding=encoding, newline="") as file:
                reader = csv.DictReader(file)
                if not reader.fieldnames or "word" not in reader.fieldnames:
                    raise LearningDataError(
                        f"{vocabulary_path.name} 必须包含 word 列。"
                    )
                result: list[dict[str, str]] = []
                seen: set[str] = set()
                for row in reader:
                    word = (row.get("word") or "").strip()
                    if not word or word in seen:
                        continue
                    seen.add(word)
                    normalized = {key: (value or "") for key, value in row.items() if key is not None}
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


def _build_review_candidate_pool(
    review_groups: dict[int, list[str]], needed: int
) -> list[str]:
    """Build a capped 20:10:5:1 candidate pool, then sample uniformly later.

    Each quota round adds at most 20 level-2, 10 level-3, 5 level-4 and
    1 level-5 word.  Extra rounds are used only when shortages leave the
    candidate pool smaller than the number of review words required.
    """
    remaining = {level: words[:] for level, words in review_groups.items()}
    for words in remaining.values():
        random.shuffle(words)

    candidate_pool: list[str] = []
    while len(candidate_pool) < needed and any(remaining.values()):
        added_this_round = 0
        for level, quota in REVIEW_WEIGHTS.items():
            group = remaining.get(level, [])
            take = min(quota, len(group))
            if take:
                candidate_pool.extend(group[:take])
                del group[:take]
                added_this_round += take
        if added_this_round == 0:
            break

    return candidate_pool


def _priority_new_word_pool(
    all_words: list[str], history: dict[str, int], excluded: set[str] | None = None
) -> list[str]:
    """Return level-1 history words first, followed by truly unseen words."""
    excluded = excluded or set()
    known_level_one = [
        word
        for word in all_words
        if word not in excluded and word in history and history[word] == 1
    ]
    unseen = [
        word for word in all_words if word not in excluded and word not in history
    ]
    random.shuffle(known_level_one)
    random.shuffle(unseen)
    return known_level_one + unseen


def select_words(
    vocabulary: list[dict[str, str]],
    history: dict[str, int],
    total_count: int,
    new_count: int,
) -> list[dict[str, str]]:
    """Select unique words using priority-new and capped review-group quotas."""
    by_word = {item["word"]: item for item in vocabulary}
    all_words = list(by_word)
    total_count = min(max(1, total_count), len(all_words))
    new_count = min(max(0, new_count), total_count)

    # "New-learning" slots prioritize words already seen but still rated 1.
    # Only after those are exhausted do truly unseen words enter these slots.
    priority_new = _priority_new_word_pool(all_words, history)
    selected: list[str] = priority_new[:new_count]
    selected_set = set(selected)

    review_needed = total_count - len(selected)
    review_groups: dict[int, list[str]] = {level: [] for level in REVIEW_WEIGHTS}
    for word, level in history.items():
        if (
            level in review_groups
            and word in by_word
            and word not in selected_set
        ):
            review_groups[level].append(word)

    candidate_pool = _build_review_candidate_pool(review_groups, review_needed)
    review_take = min(review_needed, len(candidate_pool))
    review_words = (
        random.sample(candidate_pool, k=review_take) if review_take else []
    )
    selected.extend(review_words)
    selected_set.update(review_words)

    # If review words are insufficient, fill with remaining level-1 words first
    # and then unseen words, preserving the same new-word priority.
    needed = total_count - len(selected)
    if needed:
        remaining_new = _priority_new_word_pool(all_words, history, selected_set)
        selected.extend(remaining_new[:needed])
        selected_set.update(remaining_new[:needed])

    # Final safeguard for unusually small or inconsistent data files.
    if len(selected) < total_count:
        remaining_any = [word for word in all_words if word not in selected_set]
        random.shuffle(remaining_any)
        selected.extend(remaining_any[: total_count - len(selected)])

    random.shuffle(selected)
    return [by_word[word] for word in selected]


def _merge_scores(first_score: int, second_score: int) -> int:
    return max(1, min(5, math.floor((first_score + 2 * second_score) / 3)))


def run_learning_round(parent: Any, base_dir: Path | str) -> dict[str, Any] | None:
    base = Path(base_dir)
    vocabulary_path = base / "vocabulary.csv"
    history_path = base / "learningHistory.csv"

    config = load_config(base)
    missing_ai = get_missing_ai_settings(config)
    if missing_ai:
        raise LearningDataError(
            "请先在设置中填写完整的 AI 信息：" + "、".join(missing_ai)
        )

    ensure_history_file(history_path)
    vocabulary = load_vocabulary(vocabulary_path)
    history = load_history(history_path)

    selected = select_words(
        vocabulary,
        history,
        int(config["words_per_round"]),
        int(config["new_words_per_round"]),
    )
    if not selected:
        raise LearningDataError("没有可供学习的词汇。")

    first_scores = run_word_study(parent, selected, config, "第一次词义学习")
    if first_scores is None:
        return None

    if not run_article_study(parent, selected, config):
        return None

    second_scores = run_word_study(parent, selected, config, "第二次词义学习")
    if second_scores is None:
        return None

    updated: dict[str, int] = {}
    for item in selected:
        word = item["word"]
        first = first_scores.get(word, 1)
        second = second_scores.get(word, 1)
        final_score = _merge_scores(first, second)
        history[word] = final_score
        updated[word] = final_score

    save_history(history_path, history)
    return {
        "word_count": len(selected),
        "updated_scores": updated,
        "selected_words": [item["word"] for item in selected],
    }
