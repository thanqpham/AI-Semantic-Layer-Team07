"""Shared access and comparison rules for approved business-value mappings."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from typing import Any

from src.services.metric_knowledge import normalized_text


def read_approved_business_mappings(mappings: Any, column_review_status: str) -> list[dict[str, Any]]:
    """Return structurally valid mappings only when their column and row are approved."""
    if column_review_status != "approved" or not isinstance(mappings, list):
        return []
    return [normalized for item in mappings if (normalized := _approved_mapping(item)) is not None]


def _approved_mapping(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict) or item.get("status") != "approved":
        return None
    db_value = item.get("db_value")
    business_value = item.get("business_value")
    if not _json_scalar(db_value) or not isinstance(business_value, str) or not business_value.strip():
        return None
    return {"db_value": db_value, "business_value": business_value, "status": "approved"}


def _json_scalar(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and math.isfinite(value)


def value_has_exact_sample(value: Any, column: dict[str, Any]) -> bool:
    """Check legacy samples with exact JSON scalar type and value."""
    key = scalar_value_key(value)
    return any(_json_scalar(sample) and scalar_value_key(sample) == key for sample in column.get("allowed_values", []))


def sample_value_candidates(value: Any, column: dict[str, Any]) -> list[Any]:
    """Resolve legacy sample strings using the pre-existing accent-insensitive rule."""
    if not isinstance(value, str):
        return [value] if value_has_exact_sample(value, column) else []
    key = normalized_text(value.strip())
    return [
        sample
        for sample in column.get("allowed_values", [])
        if isinstance(sample, str) and normalized_text(sample.strip()) == key
    ]


def normalize_business_label(value: str) -> str:
    """Normalize case, accents, punctuation, and whitespace for label matching."""
    normalized = normalized_text(unicodedata.normalize("NFKC", value).strip())
    return " ".join(re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).split())


def business_label_matches(text: str, label: str) -> bool:
    """Match one normalized label with word boundaries in user evidence."""
    normalized_label = normalize_business_label(label)
    normalized_evidence = normalize_business_label(text)
    return bool(
        normalized_label and re.search(r"(?<!\w)" + re.escape(normalized_label) + r"(?!\w)", normalized_evidence)
    )


def scalar_value_key(value: Any) -> str:
    """Encode scalar values with their JSON type to avoid bool/number/code collisions."""
    if isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, int):
        kind = "integer"
    elif isinstance(value, float):
        kind = "number"
    elif isinstance(value, str):
        kind = "string"
    else:
        kind = type(value).__name__
    return json.dumps([kind, value], ensure_ascii=False, separators=(",", ":"))


def mapping_metadata_fingerprint(mappings: Any, column_review_status: str, complete: bool) -> str:
    """Fingerprint mapping semantics without retaining mapping values in trace metadata."""
    rows = read_approved_business_mappings(mappings, column_review_status)
    payload = [
        column_review_status,
        complete,
        sorted((scalar_value_key(row["db_value"]), row["business_value"]) for row in rows),
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


_LEADING_LABEL_PREFIX = re.compile(
    r"^(?:da|dang|bi|duoc|o|tai|tren|qua|bang|thuoc|voi|kenh|khu vuc|vung|trang thai|phuong thuc|loai|nhom|danh muc)\s+"
)


def _stripped_label_key(value: str, column: dict[str, Any]) -> str:
    """Strip leading grammatical cues or the column's own name from a filter phrase."""
    key = normalize_business_label(value)
    col_prefixes = sorted(
        (
            normalize_business_label(str(column.get(field, "")).replace("_", " "))
            for field in ("column_name", "business_name")
            if column.get(field)
        ),
        key=len,
        reverse=True,
    )
    changed = True
    while changed and key:
        changed = False
        for prefix in col_prefixes:
            if prefix and key.startswith(prefix + " "):
                key = key[len(prefix) :].strip()
                changed = True
        updated = _LEADING_LABEL_PREFIX.sub("", key, count=1).strip()
        if updated and updated != key:
            key = updated
            changed = True
    return key


def approved_mapping_candidates(value: Any, column: dict[str, Any]) -> list[Any]:
    """Resolve a scalar label or DB value against approved mappings and legacy samples."""
    mappings = read_approved_business_mappings(
        column.get("_approved_mappings", column.get("allowed_value_mappings", [])),
        column.get("review_status", "approved"),
    )
    candidates: dict[str, Any] = {}
    if isinstance(value, str):
        exact_key = normalize_business_label(value)
        stripped_key = _stripped_label_key(value, column)
        for mapping in mappings:
            keys = {
                normalize_business_label(mapping[field])
                for field in ("db_value", "business_value")
                if isinstance(mapping[field], str)
            }
            if exact_key in keys:
                candidates[scalar_value_key(mapping["db_value"])] = mapping["db_value"]
        if not candidates and len(stripped_key) >= 3:
            for mapping in mappings:
                bval = mapping.get("business_value")
                m_keys = {normalize_business_label(bval)} if isinstance(bval, str) else set()
                if isinstance(bval, str) and re.match(r"^(?:da|bi|dang)\s+", normalize_business_label(bval)):
                    m_keys.add(_stripped_label_key(bval, column))
                if stripped_key in m_keys:
                    candidates[scalar_value_key(mapping["db_value"])] = mapping["db_value"]
    else:
        value_key = scalar_value_key(value)
        candidates = {
            scalar_value_key(sample): sample
            for sample in column.get("allowed_values", [])
            if _json_scalar(sample) and scalar_value_key(sample) == value_key
        }
        for mapping in mappings:
            if scalar_value_key(mapping["db_value"]) == value_key:
                candidates[value_key] = mapping["db_value"]
    return list(candidates.values())


def _status_label_variants(business_value: str) -> list[str]:
    """Generate natural-language status prefix variants for labels starting with Đã/Bị/Đang."""
    normalized = normalize_business_label(business_value)
    match = re.match(r"^(?:da|bi|dang)\s+(.+)$", normalized)
    if not match:
        return [business_value]
    stem = match.group(1).strip()
    if len(stem) < 3:
        return [business_value]
    variants = [business_value, f"da {stem}", f"bi {stem}", f"dang {stem}"]
    if " " in stem:
        variants.append(stem)
    else:
        variants.extend([f"don {stem}", f"trang thai {stem}"])
    return variants


def mentioned_business_values(column: dict[str, Any]) -> list[tuple[str, Any]]:
    """List labels and raw values usable as evidence for this catalog column."""
    pairs = [(sample, sample) for sample in column.get("allowed_values", []) if isinstance(sample, str)]
    for mapping in read_approved_business_mappings(
        column.get("_approved_mappings", column.get("allowed_value_mappings", [])),
        column.get("review_status", "approved"),
    ):
        for variant in _status_label_variants(mapping["business_value"]):
            pairs.append((variant, mapping["db_value"]))
        pairs.append((str(mapping["db_value"]), mapping["db_value"]))
        pairs.extend((sample, mapping["db_value"]) for sample in sample_value_candidates(mapping["db_value"], column))
    return pairs


def value_has_business_evidence(value: Any, column: dict[str, Any], evidence: str) -> bool:
    """Require the user's words to match the selected value's typed approved labels."""
    key = scalar_value_key(value)
    return any(
        key
        in {scalar_value_key(mapped), *(scalar_value_key(sample) for sample in sample_value_candidates(mapped, column))}
        and business_label_matches(evidence, label)
        for label, mapped in mentioned_business_values(column)
    )
