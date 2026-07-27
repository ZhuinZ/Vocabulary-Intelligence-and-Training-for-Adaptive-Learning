from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from learning_history import vocabulary_ids_used_in_history
from vocabulary_tags import (
    ALLOWED_VOCABULARY_TAGS,
    ALLOWED_VOCABULARY_TAG_SET,
    vocabulary_tag_label,
)

REGISTRY_VERSION = 1
REGISTRY_FILENAME = "vocabularies.json"
SNAPSHOT_DIRECTORY = "vocabularies"
ACTIVE_VOCABULARY_FILENAME = "vocabulary.csv"
PREVIOUS_VOCABULARY_FILENAME = "vocabulary.previous.csv"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registry_path(base_dir: Path | str) -> Path:
    return Path(base_dir) / REGISTRY_FILENAME


def _snapshot_dir(base_dir: Path | str) -> Path:
    return Path(base_dir) / SNAPSHOT_DIRECTORY


def _safe_nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _empty_registry() -> dict[str, Any]:
    return {
        "version": REGISTRY_VERSION,
        "active_id": None,
        "last_source_file": "",
        "profiles": [],
    }


def load_registry(base_dir: Path | str) -> dict[str, Any]:
    path = _registry_path(base_dir)
    if not path.exists():
        registry = _empty_registry()
        save_registry(base_dir, registry)
        return registry
    try:
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
        if not isinstance(raw, dict):
            raise ValueError("词库注册表根元素必须是对象。")
    except (OSError, json.JSONDecodeError, ValueError):
        backup = path.with_suffix(".json.invalid")
        try:
            path.replace(backup)
        except OSError:
            pass
        registry = _empty_registry()
        save_registry(base_dir, registry)
        return registry

    profiles: list[dict[str, Any]] = []
    for item in raw.get("profiles", []):
        if not isinstance(item, dict):
            continue
        profile_id = str(item.get("id", "")).strip()
        filename = str(item.get("filename", "")).strip()
        name = str(item.get("name", "")).strip()
        if not profile_id or not filename or not name:
            continue
        tags = [
            str(tag).strip().casefold()
            for tag in item.get("tags", [])
            if str(tag).strip()
        ]
        profiles.append(
            {
                "id": profile_id,
                "name": name,
                "tags": list(dict.fromkeys(tags)),
                "match_mode": str(item.get("match_mode", "legacy")),
                "word_count": _safe_nonnegative_int(item.get("word_count", 0)),
                "filename": filename,
                "created_at": str(item.get("created_at", "")) or _now_iso(),
                "is_legacy": bool(item.get("is_legacy", False)),
            }
        )
    active_id = str(raw.get("active_id") or "").strip() or None
    if active_id and not any(item["id"] == active_id for item in profiles):
        active_id = None
    normalized = {
        "version": REGISTRY_VERSION,
        "active_id": active_id,
        "last_source_file": str(raw.get("last_source_file", "")),
        "profiles": profiles,
    }
    if normalized != raw:
        save_registry(base_dir, normalized)
    return normalized


def save_registry(base_dir: Path | str, registry: dict[str, Any]) -> None:
    path = _registry_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(registry, file, ensure_ascii=False, indent=2)
    temp_path.replace(path)


def inspect_vocabulary(path: Path) -> tuple[int, list[str]]:
    if not path.is_file():
        return 0, []
    word_count = 0
    tags: set[str] = set()
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as file:
        reader = csv.DictReader(file)
        for row in reader:
            word = (row.get("word") or "").strip()
            key = word.casefold()
            if not word or key in seen:
                continue
            seen.add(key)
            word_count += 1
            for tag in str(row.get("tag") or "").replace(",", " ").split():
                code = tag.strip().casefold()
                if code in ALLOWED_VOCABULARY_TAG_SET:
                    tags.add(code)
    ordered = [tag for tag in ALLOWED_VOCABULARY_TAGS if tag in tags]
    return word_count, ordered


def ensure_registry(base_dir: Path | str) -> dict[str, Any]:
    base = Path(base_dir)
    registry = load_registry(base)
    snapshot_dir = _snapshot_dir(base)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    active_path = base / ACTIVE_VOCABULARY_FILENAME

    # Upgrade a pre-registry desktop installation without changing the legacy
    # vocabulary.csv path that old versions expect.
    if active_path.is_file() and not registry["profiles"]:
        profile_id = "legacy-" + uuid4().hex
        filename = f"{profile_id}.csv"
        snapshot_path = snapshot_dir / filename
        shutil.copy2(active_path, snapshot_path)
        word_count, tags = inspect_vocabulary(active_path)
        registry["profiles"].append(
            {
                "id": profile_id,
                "name": "旧版当前词库",
                "tags": tags,
                "match_mode": "legacy",
                "word_count": word_count,
                "filename": filename,
                "created_at": _now_iso(),
                "is_legacy": True,
            }
        )
        registry["active_id"] = profile_id
        save_registry(base, registry)
        return registry

    # Repair the legacy active copy from the selected snapshot when needed.
    active = get_profile(registry, registry.get("active_id"))
    if active:
        snapshot_path = snapshot_dir / active["filename"]
        if snapshot_path.is_file() and not active_path.is_file():
            shutil.copy2(snapshot_path, active_path)
    return registry


def get_profile(
    registry: dict[str, Any], profile_id: str | None
) -> dict[str, Any] | None:
    if not profile_id:
        return None
    return next(
        (item for item in registry.get("profiles", []) if item.get("id") == profile_id),
        None,
    )


def get_active_profile(base_dir: Path | str) -> dict[str, Any] | None:
    registry = ensure_registry(base_dir)
    return get_profile(registry, registry.get("active_id"))


def profile_snapshot_path(base_dir: Path | str, profile: dict[str, Any]) -> Path:
    return _snapshot_dir(base_dir) / str(profile["filename"])


def create_profile(
    base_dir: Path | str,
    *,
    name: str,
    tags: list[str],
    match_mode: str,
    generated_file: Path,
    word_count: int,
    source_file: str = "",
    activate: bool = True,
) -> dict[str, Any]:
    base = Path(base_dir)
    registry = ensure_registry(base)
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("词库名称不能为空。")
    if len(clean_name) > 120:
        raise ValueError("词库名称不能超过 120 个字符。")
    profile_id = uuid4().hex
    filename = f"{profile_id}.csv"
    snapshot_path = _snapshot_dir(base) / filename
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    generated_file.replace(snapshot_path)
    profile = {
        "id": profile_id,
        "name": clean_name,
        "tags": list(tags),
        "match_mode": match_mode,
        "word_count": int(word_count),
        "filename": filename,
        "created_at": _now_iso(),
        "is_legacy": False,
    }
    registry["profiles"].insert(0, profile)
    if source_file:
        registry["last_source_file"] = source_file
    save_registry(base, registry)
    if activate:
        activate_profile(base, profile_id)
    return profile


def activate_profile(base_dir: Path | str, profile_id: str) -> dict[str, Any]:
    base = Path(base_dir)
    registry = ensure_registry(base)
    profile = get_profile(registry, profile_id)
    if profile is None:
        raise ValueError("词库配置不存在。")
    snapshot_path = profile_snapshot_path(base, profile)
    if not snapshot_path.is_file():
        raise FileNotFoundError(f"词库快照不存在：{snapshot_path}")
    active_path = base / ACTIVE_VOCABULARY_FILENAME
    backup_path = base / PREVIOUS_VOCABULARY_FILENAME
    if active_path.is_file():
        shutil.copy2(active_path, backup_path)
    temp_path = active_path.with_suffix(".csv.tmp")
    shutil.copy2(snapshot_path, temp_path)
    temp_path.replace(active_path)
    registry["active_id"] = profile_id
    save_registry(base, registry)
    return profile


def delete_profile(base_dir: Path | str, profile_id: str) -> None:
    base = Path(base_dir)
    registry = ensure_registry(base)
    profile = get_profile(registry, profile_id)
    if profile is None:
        raise ValueError("词库配置不存在。")
    if profile_id in vocabulary_ids_used_in_history(base):
        raise ValueError("该词库已有学习记录，不能删除；可以保留并切换到其他词库。")
    snapshot_path = profile_snapshot_path(base, profile)
    registry["profiles"] = [
        item for item in registry["profiles"] if item.get("id") != profile_id
    ]
    was_active = registry.get("active_id") == profile_id
    if was_active:
        registry["active_id"] = None
    save_registry(base, registry)
    try:
        snapshot_path.unlink(missing_ok=True)
    except OSError:
        pass
    if was_active:
        try:
            (base / ACTIVE_VOCABULARY_FILENAME).unlink(missing_ok=True)
        except OSError:
            pass


def active_profile_summary(base_dir: Path | str) -> str:
    profile = get_active_profile(base_dir)
    if profile is None:
        return "尚未选择词库"
    tags = profile.get("tags") or []
    tag_text = "、".join(vocabulary_tag_label(tag) for tag in tags) if tags else "旧版/自定义"
    mode = {
        "any": "任一范围",
        "all": "全部范围",
        "legacy": "旧版导入",
    }.get(str(profile.get("match_mode")), str(profile.get("match_mode")))
    return f"{profile['name']} · {profile['word_count']} 词 · {tag_text} · {mode}"
