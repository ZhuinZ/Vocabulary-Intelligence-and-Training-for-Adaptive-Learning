from __future__ import annotations

import math
import random
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from typing import Any

from learning_history import HistoryRecord, LearningEvent, as_utc
from retrieve import parse_tags
from vocabulary_tags import DEFAULT_TAG_DIFFICULTY

SECONDS_PER_DAY = 86_400.0
CATEGORY_UNSEEN = "unseen"
CATEGORY_WEAK = "weak"
CATEGORY_STUCK = "stuck"
CATEGORY_DUE = "due_review"
CATEGORY_MAINTENANCE = "maintenance"
CATEGORY_ORDER = (
    CATEGORY_UNSEEN,
    CATEGORY_WEAK,
    CATEGORY_DUE,
    CATEGORY_MAINTENANCE,
)
CATEGORY_LABELS = {
    CATEGORY_UNSEEN: "绝对新词",
    CATEGORY_WEAK: "薄弱复习",
    CATEGORY_STUCK: "卡住词",
    CATEGORY_DUE: "到期复习",
    CATEGORY_MAINTENANCE: "巩固复习",
}


@dataclass(frozen=True)
class RankerSettings:
    policy_version: str = "rule-v0.2.1"
    history_decay: float = 0.80
    gain_window: int = 8
    cooldown_hours: float = 12.0
    exploration_rate: float = 0.10
    softmax_temperature: float = 0.15
    mmr_lambda: float = 0.80

    weak_ratio: float = 0.25
    maintenance_ratio: float = 0.10
    stuck_max_ratio: float = 0.10
    hard_new_max_ratio_normal: float = 0.40
    hard_new_max_ratio_moderate: float = 0.25
    hard_new_max_ratio_late: float = 0.15

    half_life_score_1_days: float = 0.5
    half_life_score_2_days: float = 1.5
    half_life_score_3_days: float = 4.0
    half_life_score_4_days: float = 12.0
    half_life_score_5_days: float = 35.0
    half_life_prior_strength: float = 3.0
    half_life_min_days: float = 0.5
    half_life_max_days: float = 365.0

    gain_prior_mean: float = 0.35
    gain_prior_strength: float = 3.0
    gain_raw_weight: float = 0.50
    gain_headroom_weight: float = 0.50

    review_weight_forgetting: float = 0.45
    review_weight_gain: float = 0.25
    review_weight_difficulty: float = 0.20
    review_weight_uncertainty: float = 0.10
    target_memory: float = 0.45
    target_memory_width: float = 0.22
    drop_penalty_weight: float = 0.10
    stuck_penalty_weight: float = 0.20
    weak_memory_threshold: float = 0.20
    due_memory_threshold: float = 0.60

    stuck_window: int = 3
    stuck_gain_threshold: float = 0.10
    stuck_second_score_threshold: float = 2.0

    new_weight_importance: float = 0.40
    new_weight_difficulty_match: float = 0.35
    new_weight_scaffold: float = 0.15
    new_weight_coverage: float = 0.10
    new_challenge_offset: float = 0.10
    new_difficulty_width: float = 0.20

    tag_count_weight: float = 0.20
    tag_count_saturation: int = 6
    tag_difficulty: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_TAG_DIFFICULTY)
    )

    adaptive_session_window: int = 20
    adaptive_min_sessions: int = 3
    adaptive_recent_transition_window: int = 50
    adaptive_gap_exponent: float = 0.25
    adaptive_gap_min_multiplier: float = 0.70
    adaptive_gap_max_multiplier: float = 1.20
    adaptive_retention_baseline: float = 0.60
    adaptive_performance_slope: float = 0.60
    adaptive_performance_min_multiplier: float = 0.75
    adaptive_performance_max_multiplier: float = 1.20
    adaptive_new_max_ratio: float = 0.25

    article_base_words: int = 180
    article_words_per_unseen: int = 35
    article_words_per_review: int = 18

    @property
    def half_life_days(self) -> dict[int, float]:
        return {
            1: self.half_life_score_1_days,
            2: self.half_life_score_2_days,
            3: self.half_life_score_3_days,
            4: self.half_life_score_4_days,
            5: self.half_life_score_5_days,
        }


@dataclass
class RankedCandidate:
    word_key: str
    spelling: str
    row: dict[str, str]
    category: str
    score: float
    features: dict[str, Any]
    reasons: list[str]
    tags: set[str] = field(default_factory=set)
    family_key: str = ""
    cooldown: bool = False
    selected_by: str = "exploit"
    selection_probability: float = 1.0
    display_order: int | None = None
    second_display_order: int | None = None


@dataclass
class SelectionPlan:
    selected: list[RankedCandidate]
    policy_version: str
    summary: dict[str, Any]

    @property
    def rows_first_order(self) -> list[dict[str, str]]:
        return [candidate.row for candidate in sorted(
            self.selected, key=lambda item: item.display_order or 0
        )]

    @property
    def rows_second_order(self) -> list[dict[str, str]]:
        return [candidate.row for candidate in sorted(
            self.selected, key=lambda item: item.second_display_order or 0
        )]


def _clip(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _days_between(later: datetime, earlier: datetime) -> float:
    return max(0.0, (as_utc(later) - as_utc(earlier)).total_seconds() / SECONDS_PER_DAY)


def _weighted_mean(values: Sequence[float], decay: float) -> float | None:
    if not values:
        return None
    weights = [decay ** (len(values) - index - 1) for index in range(len(values))]
    return sum(value * weight for value, weight in zip(values, weights)) / sum(weights)


def _gain(first_score: int, second_score: int, settings: RankerSettings) -> float:
    raw = max(0, second_score - first_score) / 4.0
    headroom = max(0, second_score - first_score) / max(1, 5 - first_score)
    weight_sum = settings.gain_raw_weight + settings.gain_headroom_weight
    if weight_sum <= 0:
        return 0.0
    return _clip(
        (
            settings.gain_raw_weight * raw
            + settings.gain_headroom_weight * headroom
        )
        / weight_sum,
        0.0,
        1.0,
    )


def _family_key(spelling: str) -> str:
    letters = re.sub(r"[^a-z]", "", spelling.casefold())
    if len(letters) <= 5:
        return letters
    for suffix in (
        "ization",
        "isation",
        "fulness",
        "ousness",
        "iveness",
        "ation",
        "ition",
        "ment",
        "ness",
        "ingly",
        "edly",
        "able",
        "ible",
        "ally",
        "ing",
        "ed",
        "es",
        "s",
    ):
        if letters.endswith(suffix) and len(letters) - len(suffix) >= 5:
            letters = letters[: -len(suffix)]
            break
    return letters[:7]


def _similarity(left: RankedCandidate, right: RankedCandidate) -> float:
    if left.word_key == right.word_key:
        return 1.0
    if left.family_key and left.family_key == right.family_key:
        return 0.90
    if left.tags and right.tags:
        overlap = len(left.tags & right.tags)
        union = len(left.tags | right.tags)
        if union:
            return 0.50 * overlap / union
    return 0.0


def _softmax_probabilities(
    candidates: Sequence[RankedCandidate],
    selected: Sequence[RankedCandidate],
    settings: RankerSettings,
) -> list[float]:
    if not candidates:
        return []
    adjusted: list[float] = []
    for candidate in candidates:
        max_similarity = max(
            (_similarity(candidate, previous) for previous in selected),
            default=0.0,
        )
        value = (
            settings.mmr_lambda * candidate.score
            - (1.0 - settings.mmr_lambda) * max_similarity
        )
        adjusted.append(value)
    maximum = max(adjusted)
    exponents = [
        math.exp((value - maximum) / settings.softmax_temperature)
        for value in adjusted
    ]
    total = sum(exponents)
    return [value / total for value in exponents]


def _weighted_choice(
    candidates: Sequence[RankedCandidate],
    probabilities: Sequence[float],
    rng: random.Random,
) -> RankedCandidate:
    threshold = rng.random()
    cumulative = 0.0
    for candidate, probability in zip(candidates, probabilities):
        cumulative += probability
        if threshold <= cumulative:
            return candidate
    return candidates[-1]


def _parse_positive_number(data: dict[str, str], *keys: str) -> float | None:
    for key in keys:
        raw = data.get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(str(raw).strip())
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def _word_tags(row: dict[str, str]) -> set[str]:
    return set(parse_tags(row.get("tag", "")))


def _frequency_importance(words: Sequence[dict[str, str]]) -> dict[str, float]:
    ranked: list[tuple[str, float]] = []
    fallback: dict[str, float] = {}
    for row in words:
        key = row["word"].casefold()
        rank = _parse_positive_number(row, "frq", "bnc", "frequency", "rank")
        if rank is not None:
            ranked.append((key, rank))
        else:
            collins = _parse_positive_number(row, "collins")
            fallback[key] = _clip((collins or 2.5) / 5.0, 0.0, 1.0)
    ranked.sort(key=lambda item: item[1])
    result = dict(fallback)
    if len(ranked) == 1:
        result[ranked[0][0]] = 1.0
    elif ranked:
        denominator = len(ranked) - 1
        for index, (word_key, _rank) in enumerate(ranked):
            result[word_key] = 1.0 - index / denominator
    return result


def _sense_count(row: dict[str, str]) -> int:
    text = "\n".join(str(row.get(key) or "") for key in ("translation", "definition"))
    parts = [part.strip() for part in re.split(r"[\n;/；]+", text) if part.strip()]
    return max(1, min(6, len(parts) or 1))


def _tag_count_priority(row: dict[str, str], settings: RankerSettings) -> float:
    tag_count = len(_word_tags(row))
    if tag_count <= 0:
        return 0.0
    saturation = max(1, settings.tag_count_saturation)
    return _clip(math.log1p(tag_count) / math.log1p(saturation), 0.0, 1.0)


def _importance(
    row: dict[str, str], frequency_importance: float, settings: RankerSettings
) -> tuple[float, float]:
    base_importance = _clip(
        0.50 * 1.0 + 0.35 * frequency_importance + 0.15 * 0.50,
        0.0,
        1.0,
    )
    tag_priority = _tag_count_priority(row, settings)
    importance = _clip(
        (1.0 - settings.tag_count_weight) * base_importance
        + settings.tag_count_weight * tag_priority,
        0.0,
        1.0,
    )
    return importance, tag_priority


def _word_difficulty(
    row: dict[str, str],
    frequency_importance: float,
    settings: RankerSettings,
) -> tuple[float, dict[str, float]]:
    rarity = 1.0 - frequency_importance
    length = _clip((len(re.sub(r"[^A-Za-z]", "", row["word"])) - 4) / 8.0, 0.0, 1.0)
    sense = _clip((_sense_count(row) - 1) / 5.0, 0.0, 1.0)
    tag_values = [
        _clip(settings.tag_difficulty.get(tag, 0.50), 0.0, 1.0)
        for tag in _word_tags(row)
    ]
    if tag_values:
        tag_difficulty = 0.70 * max(tag_values) + 0.30 * sum(tag_values) / len(tag_values)
    else:
        tag_difficulty = 0.50
    difficulty = _clip(
        0.60 * rarity + 0.20 * length + 0.10 * sense + 0.10 * tag_difficulty,
        0.0,
        1.0,
    )
    return difficulty, {
        "rarity": rarity,
        "length_difficulty": length,
        "sense_difficulty": sense,
        "tag_difficulty": tag_difficulty,
    }


def _observed_half_life(
    events: Sequence[LearningEvent], settings: RankerSettings
) -> tuple[list[float], list[float]]:
    observations: list[float] = []
    weights: list[float] = []
    transitions = list(zip(events, events[1:]))
    for index, (previous, current) in enumerate(transitions):
        if previous.second_score <= 1:
            continue
        elapsed = _days_between(current.completed_at, previous.completed_at)
        if elapsed <= 0:
            continue
        retention = _clip(
            (current.first_score - 1) / max(1, previous.second_score - 1),
            0.05,
            0.99,
        )
        half_life = elapsed / -math.log2(retention)
        half_life = _clip(
            half_life,
            settings.half_life_min_days,
            settings.half_life_max_days,
        )
        observations.append(half_life)
        weights.append(settings.history_decay ** (len(transitions) - index - 1))
    return observations, weights


def _review_candidate(
    row: dict[str, str],
    record: HistoryRecord,
    events: Sequence[LearningEvent],
    now: datetime,
    frequency_importance: float,
    settings: RankerSettings,
) -> RankedCandidate:
    last_first = record.last_first_score or record.mastery_level
    last_second = record.last_second_score or record.mastery_level
    last_studied_at = as_utc(record.last_studied_at or now)
    days_since = _days_between(now, last_studied_at)
    study_count = max(record.study_count, len(events), 1)

    base_half_life = settings.half_life_days.get(last_second, 4.0)
    prior_half_life = base_half_life * (1.0 + 0.20 * math.log1p(study_count))
    observations, observation_weights = _observed_half_life(events, settings)
    numerator = settings.half_life_prior_strength * math.log(prior_half_life)
    denominator = settings.half_life_prior_strength
    for observation, weight in zip(observations, observation_weights):
        numerator += weight * math.log(observation)
        denominator += weight
    half_life = math.exp(numerator / denominator) if denominator else prior_half_life
    half_life = _clip(half_life, settings.half_life_min_days, settings.half_life_max_days)

    initial_memory = (last_second - 1) / 4.0
    predicted_memory = _clip(initial_memory * 2 ** (-days_since / half_life), 0.0, 1.0)
    forgetting_risk = 1.0 - predicted_memory
    desirable_difficulty = math.exp(
        -((predicted_memory - settings.target_memory) ** 2)
        / (2.0 * settings.target_memory_width**2)
    )

    recent_events = list(events[-settings.gain_window :])
    gains = [_gain(event.first_score, event.second_score, settings) for event in recent_events]
    gain_weights = [
        settings.history_decay ** (len(gains) - index - 1)
        for index in range(len(gains))
    ]
    gain_numerator = settings.gain_prior_strength * settings.gain_prior_mean
    gain_denominator = settings.gain_prior_strength
    for gain, weight in zip(gains, gain_weights):
        gain_numerator += weight * gain
        gain_denominator += weight
    expected_gain = gain_numerator / gain_denominator if gain_denominator else 0.0

    drops = [max(0, event.first_score - event.second_score) / 4.0 for event in recent_events]
    drop_penalty = _weighted_mean(drops, settings.history_decay) or 0.0
    uncertainty = 1.0 / math.sqrt(1.0 + study_count)
    importance, tag_count_priority = _importance(row, frequency_importance, settings)
    tags = _word_tags(row)
    tag_count = len(tags)

    stuck = False
    if len(events) >= settings.stuck_window:
        stuck_events = list(events[-settings.stuck_window :])
        stuck_gain = sum(
            _gain(event.first_score, event.second_score, settings)
            for event in stuck_events
        ) / len(stuck_events)
        stuck_second = sum(event.second_score for event in stuck_events) / len(stuck_events)
        stuck = (
            stuck_gain < settings.stuck_gain_threshold
            and stuck_second <= settings.stuck_second_score_threshold
        )

    if stuck:
        category = CATEGORY_STUCK
    elif (
        last_second <= 2
        or last_first == 1
        or predicted_memory <= settings.weak_memory_threshold
    ):
        category = CATEGORY_WEAK
    elif predicted_memory < settings.due_memory_threshold:
        category = CATEGORY_DUE
    else:
        category = CATEGORY_MAINTENANCE

    review_weight_sum = (
        settings.review_weight_forgetting
        + settings.review_weight_gain
        + settings.review_weight_difficulty
        + settings.review_weight_uncertainty
    )
    if review_weight_sum <= 0:
        base_score = 0.0
    else:
        base_score = (
            settings.review_weight_forgetting * forgetting_risk
            + settings.review_weight_gain * expected_gain
            + settings.review_weight_difficulty * desirable_difficulty
            + settings.review_weight_uncertainty * uncertainty
        ) / review_weight_sum
    importance_adjusted = base_score * (0.65 + 0.35 * importance)
    score = _clip(
        importance_adjusted
        - settings.drop_penalty_weight * drop_penalty
        - settings.stuck_penalty_weight * float(stuck),
        0.0,
        1.0,
    )

    cooldown = days_since * 24.0 < settings.cooldown_hours and last_second > 2
    reasons: list[str] = []
    if forgetting_risk >= 0.50:
        reasons.append("due_for_review")
    if desirable_difficulty >= 0.70:
        reasons.append("desirable_difficulty")
    if expected_gain >= 0.50:
        reasons.append("historically_learnable")
    if category == CATEGORY_WEAK:
        reasons.append("weak_memory")
    if category == CATEGORY_STUCK:
        reasons.append("stuck_word")
    if importance >= 0.75:
        reasons.append("important_word")
    if tag_count >= 2:
        reasons.append("broad_exam_coverage")
    if uncertainty >= 0.50:
        reasons.append("uncertain_estimate")
    if cooldown:
        reasons.append("cooldown")

    return RankedCandidate(
        word_key=row["word"].casefold(),
        spelling=row["word"],
        row=row,
        category=category,
        score=score,
        features={
            "study_count": study_count,
            "last_first_score": last_first,
            "last_second_score": last_second,
            "days_since_last_study": round(days_since, 6),
            "half_life_days": round(half_life, 6),
            "half_life_observation_count": len(observations),
            "predicted_memory": round(predicted_memory, 6),
            "forgetting_risk": round(forgetting_risk, 6),
            "desirable_difficulty": round(desirable_difficulty, 6),
            "expected_gain": round(expected_gain, 6),
            "uncertainty": round(uncertainty, 6),
            "importance": round(importance, 6),
            "frequency_importance": round(frequency_importance, 6),
            "tag_count": tag_count,
            "tag_count_priority": round(tag_count_priority, 6),
            "drop_penalty": round(drop_penalty, 6),
            "stuck_penalty": 1.0 if stuck else 0.0,
            "cooldown": cooldown,
        },
        reasons=reasons,
        tags=tags,
        family_key=_family_key(row["word"]),
        cooldown=cooldown,
    )


def _scaffold_score(
    row: dict[str, str], mastered_spellings: Sequence[str], mastered_tags: set[str]
) -> float:
    family = _family_key(row["word"])
    if family and any(_family_key(spelling) == family for spelling in mastered_spellings):
        return 0.85
    if _word_tags(row) & mastered_tags:
        return 0.70
    return 0.50


def _new_candidate(
    row: dict[str, str],
    ability: float,
    frequency_importance: float,
    scaffold: float,
    coverage: float,
    settings: RankerSettings,
) -> RankedCandidate:
    difficulty, difficulty_parts = _word_difficulty(row, frequency_importance, settings)
    target_difficulty = _clip(ability + settings.new_challenge_offset, 0.0, 1.0)
    difficulty_match = math.exp(
        -((difficulty - target_difficulty) ** 2)
        / (2.0 * settings.new_difficulty_width**2)
    )
    importance, tag_count_priority = _importance(row, frequency_importance, settings)
    tags = _word_tags(row)
    tag_count = len(tags)
    weight_sum = (
        settings.new_weight_importance
        + settings.new_weight_difficulty_match
        + settings.new_weight_scaffold
        + settings.new_weight_coverage
    )
    if weight_sum <= 0:
        score = 0.0
    else:
        score = _clip(
            (
                settings.new_weight_importance * importance
                + settings.new_weight_difficulty_match * difficulty_match
                + settings.new_weight_scaffold * scaffold
                + settings.new_weight_coverage * coverage
            )
            / weight_sum,
            0.0,
            1.0,
        )
    reasons: list[str] = ["absolutely_unseen"]
    if importance >= 0.75:
        reasons.append("important_word")
    if tag_count >= 2:
        reasons.append("broad_exam_coverage")
    if difficulty_match >= 0.70:
        reasons.append("difficulty_matched")
    if scaffold >= 0.70:
        reasons.append("knowledge_scaffold")
    if coverage >= 0.60:
        reasons.append("coverage_gap")
    return RankedCandidate(
        word_key=row["word"].casefold(),
        spelling=row["word"],
        row=row,
        category=CATEGORY_UNSEEN,
        score=score,
        features={
            "ability": round(ability, 6),
            "difficulty": round(difficulty, 6),
            "target_difficulty": round(target_difficulty, 6),
            "difficulty_match": round(difficulty_match, 6),
            "importance": round(importance, 6),
            "frequency_importance": round(frequency_importance, 6),
            "tag_count": tag_count,
            "tag_count_priority": round(tag_count_priority, 6),
            "scaffold": round(scaffold, 6),
            "coverage_gap": round(coverage, 6),
            **{key: round(value, 6) for key, value in difficulty_parts.items()},
        },
        reasons=reasons,
        tags=tags,
        family_key=_family_key(row["word"]),
    )


def _ability(events_by_word: dict[str, list[LearningEvent]], settings: RankerSettings) -> float:
    events = sorted(
        (event for events in events_by_word.values() for event in events),
        key=lambda event: event.completed_at,
    )[-50:]
    if not events:
        return 0.35
    normalized = [(event.first_score - 1) / 4.0 for event in events]
    average_score = _weighted_mean(normalized, settings.history_decay) or 0.0
    mastery_rate = sum(event.first_score >= 4 for event in events) / len(events)
    return _clip(0.70 * average_score + 0.30 * mastery_rate, 0.0, 1.0)


def _recent_retention(
    events_by_word: dict[str, list[LearningEvent]], settings: RankerSettings
) -> tuple[float, int]:
    transitions: list[tuple[datetime, float]] = []
    for events in events_by_word.values():
        for previous, current in zip(events, events[1:]):
            retention = _clip(
                (current.first_score - 1) / max(1, previous.second_score - 1),
                0.0,
                1.0,
            )
            transitions.append((current.completed_at, retention))
    transitions.sort(key=lambda item: item[0])
    values = [
        value
        for _date, value in transitions[-settings.adaptive_recent_transition_window :]
    ]
    if not values:
        return settings.adaptive_retention_baseline, 0
    return _weighted_mean(values, settings.history_decay) or 0.0, len(values)


def _adaptive_new_count(
    base_count: int,
    total_count: int,
    mode: str,
    session_dates_desc: Sequence[datetime],
    events_by_word: dict[str, list[LearningEvent]],
    now: datetime,
    settings: RankerSettings,
) -> tuple[int, dict[str, Any]]:
    base_count = min(max(base_count, 0), total_count)
    summary: dict[str, Any] = {
        "mode": mode,
        "base_unseen_count": base_count,
        "typical_session_gap_days": None,
        "current_session_gap_days": None,
        "session_gap_ratio": None,
        "gap_multiplier": 1.0,
        "recent_retention": settings.adaptive_retention_baseline,
        "retention_transition_count": 0,
        "performance_multiplier": 1.0,
    }
    if mode != "adaptive" or len(session_dates_desc) < settings.adaptive_min_sessions:
        return base_count, summary

    dates = sorted(session_dates_desc[: settings.adaptive_session_window])
    gaps = [
        _days_between(current, previous)
        for previous, current in zip(dates, dates[1:])
        if _days_between(current, previous) > 1.0 / 1440.0
    ]
    if not gaps:
        return base_count, summary
    typical_gap = median(gaps)
    current_gap = _days_between(now, max(dates))
    ratio = max(0.01, current_gap / typical_gap) if typical_gap > 0 else 1.0
    gap_multiplier = _clip(
        ratio ** (-settings.adaptive_gap_exponent),
        settings.adaptive_gap_min_multiplier,
        settings.adaptive_gap_max_multiplier,
    )
    retention, transition_count = _recent_retention(events_by_word, settings)
    performance_multiplier = _clip(
        1.0
        + settings.adaptive_performance_slope
        * (retention - settings.adaptive_retention_baseline),
        settings.adaptive_performance_min_multiplier,
        settings.adaptive_performance_max_multiplier,
    )
    maximum = min(total_count, math.ceil(total_count * settings.adaptive_new_max_ratio))
    effective = int(round(base_count * gap_multiplier * performance_multiplier))
    effective = min(max(effective, 0), maximum)
    summary.update(
        {
            "typical_session_gap_days": round(typical_gap, 6),
            "current_session_gap_days": round(current_gap, 6),
            "session_gap_ratio": round(ratio, 6),
            "gap_multiplier": round(gap_multiplier, 6),
            "recent_retention": round(retention, 6),
            "retention_transition_count": transition_count,
            "performance_multiplier": round(performance_multiplier, 6),
        }
    )
    return effective, summary


def _category_quotas(
    total_count: int, unseen_count: int, settings: RankerSettings
) -> dict[str, int]:
    remaining = max(0, total_count - unseen_count)
    weak = min(remaining, int(round(total_count * settings.weak_ratio)))
    maintenance = min(
        remaining - weak,
        int(round(total_count * settings.maintenance_ratio)),
    )
    due = max(0, remaining - weak - maintenance)
    return {
        CATEGORY_UNSEEN: unseen_count,
        CATEGORY_WEAK: weak,
        CATEGORY_DUE: due,
        CATEGORY_MAINTENANCE: maintenance,
    }


def _balanced_slots(quotas: dict[str, int]) -> list[str]:
    remaining = dict(quotas)
    slots: list[str] = []
    while any(count > 0 for count in remaining.values()):
        for category in CATEGORY_ORDER:
            if remaining.get(category, 0) > 0:
                slots.append(category)
                remaining[category] -= 1
    return slots


def _eligible_for_slot(
    candidates: Sequence[RankedCandidate],
    slot_category: str,
    selected_ids: set[str],
    selected_families: set[str],
    stuck_count: int,
    stuck_limit: int,
    hard_new_count: int,
    hard_new_limit: int,
    *,
    allow_cooldown: bool,
    relax_family: bool,
    relax_hard_new: bool,
) -> list[RankedCandidate]:
    result: list[RankedCandidate] = []
    for candidate in candidates:
        if candidate.word_key in selected_ids:
            continue
        if candidate.cooldown and not allow_cooldown:
            continue
        if slot_category == CATEGORY_WEAK:
            if candidate.category not in {CATEGORY_WEAK, CATEGORY_STUCK}:
                continue
        elif candidate.category != slot_category:
            continue
        if candidate.category == CATEGORY_STUCK and stuck_count >= stuck_limit:
            continue
        if (
            slot_category == CATEGORY_UNSEEN
            and float(candidate.features.get("difficulty", 0.0)) >= 0.75
            and hard_new_count >= hard_new_limit
            and not relax_hard_new
        ):
            continue
        if (
            candidate.family_key
            and candidate.family_key in selected_families
            and not relax_family
        ):
            continue
        result.append(candidate)
    return result


def _pick_candidate(
    pool: Sequence[RankedCandidate],
    selected: Sequence[RankedCandidate],
    explore: bool,
    rng: random.Random,
    settings: RankerSettings,
) -> RankedCandidate:
    probabilities = _softmax_probabilities(pool, selected, settings)
    if explore:
        chosen = _weighted_choice(pool, probabilities, rng)
        chosen.selected_by = "explore"
        probability = settings.exploration_rate * probabilities[pool.index(chosen)]
    else:
        adjusted: list[float] = []
        for candidate in pool:
            max_similarity = max(
                (_similarity(candidate, previous) for previous in selected),
                default=0.0,
            )
            adjusted.append(
                settings.mmr_lambda * candidate.score
                - (1.0 - settings.mmr_lambda) * max_similarity
            )
        chosen = pool[max(range(len(pool)), key=lambda index: adjusted[index])]
        chosen.selected_by = "exploit"
        probability = (
            1.0
            - settings.exploration_rate
            + settings.exploration_rate * probabilities[pool.index(chosen)]
        )
    chosen.selection_probability = round(_clip(probability, 0.0, 1.0), 8)
    return chosen


def _assign_second_order(selected: list[RankedCandidate], rng: random.Random) -> None:
    count = len(selected)
    if count <= 1:
        if selected:
            selected[0].second_display_order = 0
        return
    indices = list(range(count))
    for _ in range(50):
        rng.shuffle(indices)
        if all(indices[position] != position for position in range(count)):
            break
    else:
        offset = rng.randint(1, count - 1)
        indices = [(position + offset) % count for position in range(count)]
    for second_position, first_position in enumerate(indices):
        selected[first_position].second_display_order = second_position


def build_selection_plan(
    vocabulary: Sequence[dict[str, str]],
    records: dict[str, HistoryRecord],
    events_by_word: dict[str, list[LearningEvent]],
    session_dates: Sequence[datetime],
    total_count: int,
    base_unseen_count: int,
    *,
    new_word_mode: str = "fixed",
    rng: random.Random | None = None,
    now: datetime | None = None,
    settings: RankerSettings | None = None,
) -> SelectionPlan:
    settings = settings or RankerSettings()
    rng = rng or random.Random()
    now = as_utc(now or datetime.now(timezone.utc))

    words: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in vocabulary:
        word = str(raw.get("word", "")).strip()
        key = word.casefold()
        if not word or key in seen:
            continue
        seen.add(key)
        row = {str(field): str(value or "") for field, value in raw.items() if field is not None}
        row["word"] = word
        words.append(row)
    if not words:
        return SelectionPlan([], settings.policy_version, {"reason": "empty_vocabulary"})

    total_count = min(max(1, total_count), len(words))
    base_unseen_count = min(max(0, base_unseen_count), total_count)
    frequency = _frequency_importance(words)
    ability = _ability(events_by_word, settings)
    effective_unseen, adaptive_summary = _adaptive_new_count(
        base_unseen_count,
        total_count,
        new_word_mode,
        session_dates,
        events_by_word,
        now,
        settings,
    )

    mastered_keys = {
        key for key, record in records.items() if record.mastery_level >= 4
    }
    words_by_key = {row["word"].casefold(): row for row in words}
    mastered_words = [words_by_key[key] for key in mastered_keys if key in words_by_key]
    mastered_spellings = [row["word"] for row in mastered_words]
    mastered_tags = {tag for row in mastered_words for tag in _word_tags(row)}
    tag_totals: dict[str, int] = defaultdict(int)
    tag_mastered: dict[str, int] = defaultdict(int)
    for row in words:
        key = row["word"].casefold()
        for tag in _word_tags(row):
            tag_totals[tag] += 1
            if key in mastered_keys:
                tag_mastered[tag] += 1

    candidates: list[RankedCandidate] = []
    for row in words:
        key = row["word"].casefold()
        frequency_importance = frequency.get(key, 0.50)
        record = records.get(key)
        if record is None or record.study_count <= 0:
            row_tags = _word_tags(row)
            tag_coverage = [
                1.0 - tag_mastered[tag] / max(1, tag_totals[tag])
                for tag in row_tags
            ]
            coverage = sum(tag_coverage) / len(tag_coverage) if tag_coverage else 0.50
            candidates.append(
                _new_candidate(
                    row,
                    ability,
                    frequency_importance,
                    _scaffold_score(row, mastered_spellings, mastered_tags),
                    coverage,
                    settings,
                )
            )
        else:
            candidates.append(
                _review_candidate(
                    row,
                    record,
                    events_by_word.get(key, []),
                    now,
                    frequency_importance,
                    settings,
                )
            )

    quotas = _category_quotas(total_count, effective_unseen, settings)
    slots = _balanced_slots(quotas)
    exploration_count = (
        min(total_count, max(1, int(round(total_count * settings.exploration_rate))))
        if settings.exploration_rate > 0
        else 0
    )
    explore_slots = set(rng.sample(range(len(slots)), k=min(exploration_count, len(slots))))

    ratio = adaptive_summary.get("session_gap_ratio")
    hard_new_ratio = settings.hard_new_max_ratio_normal
    if isinstance(ratio, (float, int)) and ratio > 2.0:
        hard_new_ratio = settings.hard_new_max_ratio_late
    elif isinstance(ratio, (float, int)) and ratio > 1.0:
        hard_new_ratio = min(
            settings.hard_new_max_ratio_moderate,
            settings.hard_new_max_ratio_normal,
        )
    hard_new_limit = max(0, math.ceil(max(1, effective_unseen) * hard_new_ratio))
    stuck_limit = max(1, math.floor(total_count * settings.stuck_max_ratio))

    selected: list[RankedCandidate] = []
    selected_ids: set[str] = set()
    selected_families: set[str] = set()
    stuck_count = 0
    hard_new_count = 0
    fallback_count = 0

    for slot_index, slot_category in enumerate(slots):
        pool: list[RankedCandidate] = []
        for allow_cooldown, relax_family, relax_hard_new in (
            (False, False, False),
            (False, True, False),
            (False, True, True),
            (True, True, True),
        ):
            pool = _eligible_for_slot(
                candidates,
                slot_category,
                selected_ids,
                selected_families,
                stuck_count,
                stuck_limit,
                hard_new_count,
                hard_new_limit,
                allow_cooldown=allow_cooldown,
                relax_family=relax_family,
                relax_hard_new=relax_hard_new,
            )
            if pool:
                break
        if not pool:
            fallback_priority = {
                CATEGORY_UNSEEN: (CATEGORY_WEAK, CATEGORY_DUE, CATEGORY_MAINTENANCE),
                CATEGORY_WEAK: (CATEGORY_DUE, CATEGORY_MAINTENANCE, CATEGORY_UNSEEN),
                CATEGORY_DUE: (CATEGORY_WEAK, CATEGORY_MAINTENANCE, CATEGORY_UNSEEN),
                CATEGORY_MAINTENANCE: (CATEGORY_DUE, CATEGORY_WEAK, CATEGORY_UNSEEN),
            }
            for fallback_category in fallback_priority[slot_category]:
                pool = _eligible_for_slot(
                    candidates,
                    fallback_category,
                    selected_ids,
                    selected_families,
                    stuck_count,
                    stuck_limit,
                    hard_new_count,
                    hard_new_limit,
                    allow_cooldown=True,
                    relax_family=True,
                    relax_hard_new=True,
                )
                if pool:
                    break
            if not pool:
                pool = [
                    candidate
                    for candidate in candidates
                    if candidate.word_key not in selected_ids
                ]
            if not pool:
                break
            chosen = max(pool, key=lambda candidate: candidate.score)
            chosen.selected_by = "fallback"
            chosen.selection_probability = round(1.0 / len(pool), 8)
            if "quota_fallback" not in chosen.reasons:
                chosen.reasons.append("quota_fallback")
            fallback_count += 1
        else:
            chosen = _pick_candidate(
                pool,
                selected,
                slot_index in explore_slots,
                rng,
                settings,
            )
        chosen.display_order = len(selected)
        selected.append(chosen)
        selected_ids.add(chosen.word_key)
        if chosen.family_key:
            selected_families.add(chosen.family_key)
        if chosen.category == CATEGORY_STUCK:
            stuck_count += 1
        if (
            chosen.category == CATEGORY_UNSEEN
            and float(chosen.features.get("difficulty", 0.0)) >= 0.75
        ):
            hard_new_count += 1

    if len(selected) < total_count:
        remaining = [
            candidate for candidate in candidates if candidate.word_key not in selected_ids
        ]
        remaining.sort(key=lambda candidate: candidate.score, reverse=True)
        for candidate in remaining[: total_count - len(selected)]:
            candidate.selected_by = "fallback"
            candidate.selection_probability = round(1.0 / max(1, len(remaining)), 8)
            candidate.display_order = len(selected)
            if "final_fallback" not in candidate.reasons:
                candidate.reasons.append("final_fallback")
            selected.append(candidate)
            fallback_count += 1

    _assign_second_order(selected, rng)
    actual_counts: dict[str, int] = defaultdict(int)
    for candidate in selected:
        actual_counts[candidate.category] += 1
    summary = {
        "policy_version": settings.policy_version,
        "generated_at": now.isoformat(),
        "requested_total_count": total_count,
        "requested_base_unseen_count": base_unseen_count,
        "effective_unseen_count": effective_unseen,
        "new_word_mode": new_word_mode,
        "requested_quotas": quotas,
        "actual_category_counts": dict(actual_counts),
        "candidate_category_counts": {
            category: sum(candidate.category == category for candidate in candidates)
            for category in (
                CATEGORY_UNSEEN,
                CATEGORY_WEAK,
                CATEGORY_STUCK,
                CATEGORY_DUE,
                CATEGORY_MAINTENANCE,
            )
        },
        "exploration_target_count": exploration_count,
        "exploration_actual_count": sum(
            candidate.selected_by == "explore" for candidate in selected
        ),
        "fallback_count": fallback_count,
        "stuck_limit": stuck_limit,
        "hard_new_limit": hard_new_limit,
        "ability": round(ability, 6),
        "adaptive": adaptive_summary,
        "parameters": {
            "history_decay": settings.history_decay,
            "cooldown_hours": settings.cooldown_hours,
            "exploration_rate": settings.exploration_rate,
            "softmax_temperature": settings.softmax_temperature,
            "mmr_lambda": settings.mmr_lambda,
            "target_memory": settings.target_memory,
            "target_memory_width": settings.target_memory_width,
            "weak_ratio": settings.weak_ratio,
            "maintenance_ratio": settings.maintenance_ratio,
            "stuck_max_ratio": settings.stuck_max_ratio,
            "tag_count_weight": settings.tag_count_weight,
            "tag_count_saturation": settings.tag_count_saturation,
        },
    }
    return SelectionPlan(selected, settings.policy_version, summary)


def article_target_word_count(
    plan: SelectionPlan, settings: RankerSettings | None = None
) -> int:
    settings = settings or RankerSettings()
    unseen_count = sum(item.category == CATEGORY_UNSEEN for item in plan.selected)
    review_count = len(plan.selected) - unseen_count
    return (
        settings.article_base_words
        + settings.article_words_per_unseen * unseen_count
        + settings.article_words_per_review * review_count
    )
