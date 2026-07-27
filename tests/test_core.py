from __future__ import annotations

import ast
import csv
import json
import os
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config_manager import load_config
from learning_history import (
    EVENT_HEADERS,
    HistoryRecord,
    LearningEvent,
    load_learning_state,
)
from retrieve import export_vocabulary_by_tags
from vital_ranker import (
    CATEGORY_UNSEEN,
    RankerSettings,
    article_target_word_count,
    build_selection_plan,
)
from vocabulary_store import (
    activate_profile,
    create_profile,
    delete_profile,
    ensure_registry,
    get_active_profile,
)


class ConfigMigrationTests(unittest.TestCase):
    def test_old_exact_default_20_10_migrates_to_20_3(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps({"words_per_round": 20, "new_words_per_round": 10}),
                encoding="utf-8",
            )
            config = load_config(tmp)
            self.assertEqual(config["words_per_round"], 20)
            self.assertEqual(config["new_words_per_round"], 3)
            self.assertEqual(config["config_version"], 2)

    def test_zero_new_words_is_preserved_as_custom_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps({"words_per_round": 20, "new_words_per_round": 0}),
                encoding="utf-8",
            )
            config = load_config(tmp)
            self.assertEqual(config["new_words_per_round"], 0)

    def test_custom_old_values_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps({"words_per_round": 30, "new_words_per_round": 7}),
                encoding="utf-8",
            )
            config = load_config(tmp)
            self.assertEqual(config["words_per_round"], 30)
            self.assertEqual(config["new_words_per_round"], 7)

    def test_malformed_numeric_values_fall_back_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "config_version": "broken",
                        "words_per_round": "many",
                        "new_words_per_round": None,
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(tmp)
            self.assertEqual(config["words_per_round"], 20)
            self.assertEqual(config["new_words_per_round"], 3)


class VocabularyExportTests(unittest.TestCase):
    def _write_source(self, path: Path) -> None:
        rows = [
            {"word": "Alpha", "tag": "gk", "translation": "甲-旧"},
            {"word": "alpha", "tag": "gre cet6", "translation": "甲-新"},
            {"word": "Beta", "tag": "gk", "translation": "乙"},
            {"word": "Gamma", "tag": "ielts", "translation": "丙"},
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["word", "tag", "translation"])
            writer.writeheader()
            writer.writerows(rows)

    def test_any_and_all_match_server_tag_union_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "stardict.csv"
            self._write_source(source)

            any_path = base / "any.csv"
            result_any = export_vocabulary_by_tags(
                source, any_path, ["gk", "gre"], match_all=False
            )
            self.assertEqual(result_any["exported_rows"], 2)

            all_path = base / "all.csv"
            result_all = export_vocabulary_by_tags(
                source, all_path, ["gk", "gre"], match_all=True
            )
            self.assertEqual(result_all["exported_rows"], 1)
            with all_path.open("r", encoding="utf-8-sig", newline="") as file:
                row = next(csv.DictReader(file))
            self.assertEqual(row["word"], "Alpha")
            self.assertEqual(row["translation"], "甲-新")
            self.assertEqual(set(row["tag"].split()), {"gk", "gre", "cet6"})

    def test_disallowed_tag_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "stardict.csv"
            self._write_source(source)
            with self.assertRaises(ValueError):
                export_vocabulary_by_tags(source, base / "bad.csv", ["unknown"])


class RankerCompatibilityTests(unittest.TestCase):
    @staticmethod
    def _vocabulary(count: int = 12) -> list[dict[str, str]]:
        return [
            {
                "word": f"word{i}",
                "tag": "gk gre" if i % 3 == 0 else "gk",
                "translation": f"释义{i}",
                "collins": str((i % 5) + 1),
                "frq": str(i + 1),
            }
            for i in range(count)
        ]

    def test_old_two_column_history_is_loaded_and_level_one_is_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with (base / "learningHistory.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as file:
                writer = csv.DictWriter(file, fieldnames=["单词", "熟练程度"])
                writer.writeheader()
                writer.writerows(
                    [
                        {"单词": "word0", "熟练程度": 1},
                        {"单词": "word1", "熟练程度": 1},
                    ]
                )
            records, events_by_word, session_dates = load_learning_state(base)
            plan = build_selection_plan(
                self._vocabulary(10),
                records,
                events_by_word,
                session_dates,
                total_count=4,
                base_unseen_count=2,
                rng=random.Random(9),
                settings=RankerSettings(exploration_rate=0),
            )
            unseen = [item for item in plan.selected if item.category == CATEGORY_UNSEEN]
            self.assertEqual(len(unseen), 2)
            self.assertTrue({item.spelling for item in unseen}.isdisjoint({"word0", "word1"}))
            self.assertTrue(
                any(item.spelling in {"word0", "word1"} for item in plan.selected)
            )

    def test_new_user_backfills_review_slots_with_unseen(self) -> None:
        plan = build_selection_plan(
            self._vocabulary(10),
            {},
            {},
            [],
            total_count=6,
            base_unseen_count=2,
            rng=random.Random(3),
            settings=RankerSettings(exploration_rate=0),
        )
        self.assertEqual(len(plan.selected), 6)
        self.assertEqual({item.category for item in plan.selected}, {CATEGORY_UNSEEN})
        self.assertEqual(plan.summary["fallback_count"], 4)

    def test_second_pass_order_is_deranged(self) -> None:
        plan = build_selection_plan(
            self._vocabulary(10),
            {},
            {},
            [],
            total_count=6,
            base_unseen_count=6,
            rng=random.Random(12),
            settings=RankerSettings(exploration_rate=0),
        )
        self.assertEqual(
            sorted(item.second_display_order for item in plan.selected), list(range(6))
        )
        self.assertTrue(
            all(item.display_order != item.second_display_order for item in plan.selected)
        )

    def test_adaptive_mode_reduces_new_quota_after_poor_retention(self) -> None:
        now = datetime(2026, 7, 28, tzinfo=timezone.utc)
        events = []
        for index, days_ago in enumerate((3, 2, 1)):
            events.append(
                LearningEvent(
                    word_key="word0",
                    word="word0",
                    first_score=1,
                    second_score=2,
                    final_mastery=1,
                    completed_at=now - timedelta(days=days_ago),
                    display_order=0,
                    second_display_order=0,
                    session_id=f"s{index}",
                    vocabulary_id="v1",
                )
            )
        records = {
            "word0": HistoryRecord(
                word="word0",
                mastery_level=1,
                study_count=3,
                last_first_score=1,
                last_second_score=2,
                first_studied_at=now - timedelta(days=3),
                last_studied_at=now - timedelta(days=1),
            )
        }
        plan = build_selection_plan(
            self._vocabulary(12),
            records,
            {"word0": events},
            [event.completed_at for event in reversed(events)],
            total_count=6,
            base_unseen_count=3,
            new_word_mode="adaptive",
            rng=random.Random(5),
            now=now,
            settings=RankerSettings(
                exploration_rate=0,
                adaptive_new_max_ratio=1,
            ),
        )
        self.assertLess(plan.summary["effective_unseen_count"], 3)
        self.assertLess(plan.summary["adaptive"]["performance_multiplier"], 1)

    def test_article_length_matches_server_formula(self) -> None:
        plan = build_selection_plan(
            self._vocabulary(10),
            {},
            {},
            [],
            total_count=4,
            base_unseen_count=2,
            rng=random.Random(1),
            settings=RankerSettings(exploration_rate=0),
        )
        unseen = sum(item.category == CATEGORY_UNSEEN for item in plan.selected)
        review = len(plan.selected) - unseen
        self.assertEqual(article_target_word_count(plan), 180 + 35 * unseen + 18 * review)


class VocabularyStoreTests(unittest.TestCase):
    @staticmethod
    def _write_vocab(path: Path, words: list[tuple[str, str]]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["word", "tag", "translation"])
            writer.writeheader()
            for word, tag in words:
                writer.writerow({"word": word, "tag": tag, "translation": word})

    def test_existing_legacy_vocabulary_is_registered_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_vocab(base / "vocabulary.csv", [("alpha", "gk"), ("beta", "gre")])
            registry = ensure_registry(base)
            self.assertEqual(len(registry["profiles"]), 1)
            self.assertEqual(registry["profiles"][0]["name"], "旧版当前词库")
            self.assertEqual(registry["profiles"][0]["word_count"], 2)
            self.assertTrue((base / "vocabulary.csv").is_file())
            self.assertTrue((base / "vocabularies" / registry["profiles"][0]["filename"]).is_file())

    def test_create_activate_and_protect_used_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_vocab(base / "vocabulary.csv", [("legacy", "gk")])
            ensure_registry(base)
            generated = base / "generated.csv"
            self._write_vocab(generated, [("gamma", "gre"), ("delta", "gre")])
            profile = create_profile(
                base,
                name="GRE",
                tags=["gre"],
                match_mode="any",
                generated_file=generated,
                word_count=2,
                activate=True,
            )
            self.assertEqual(get_active_profile(base)["id"], profile["id"])
            self.assertTrue((base / "vocabulary.previous.csv").is_file())

            with (base / "learningEvents.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as file:
                writer = csv.DictWriter(file, fieldnames=EVENT_HEADERS)
                writer.writeheader()
                writer.writerow(
                    {
                        "会话ID": "session",
                        "词库ID": profile["id"],
                        "单词": "gamma",
                        "第一次评分": 1,
                        "第二次评分": 3,
                        "最终熟练程度": 2,
                        "完成时间": datetime.now(timezone.utc).isoformat(),
                        "第一轮顺序": 0,
                        "第二轮顺序": 0,
                    }
                )
            with self.assertRaises(ValueError):
                delete_profile(base, profile["id"])


class PackagingConstraintTests(unittest.TestCase):
    def test_project_uses_only_standard_library_or_local_modules(self) -> None:
        root = Path(__file__).resolve().parents[1]
        local_modules = {path.stem for path in root.glob("*.py")}
        allowed = set(getattr(__import__("sys"), "stdlib_module_names", ())) | local_modules
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        self.assertIn(top, allowed, f"{path.name} imports non-core {top}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top = node.module.split(".")[0]
                    self.assertIn(top, allowed, f"{path.name} imports non-core {top}")

    def test_desktop_tree_contains_no_bat_or_ps1_launchers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launchers = [
            path
            for path in root.rglob("*")
            if path.suffix.casefold() in {".bat", ".ps1"}
            and (not path.relative_to(root).parts or path.relative_to(root).parts[0] != "server")
        ]
        self.assertEqual(launchers, [])


if __name__ == "__main__":
    unittest.main()
