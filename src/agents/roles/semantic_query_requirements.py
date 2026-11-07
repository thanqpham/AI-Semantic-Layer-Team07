"""Validate explicit user conditions before a semantic query executes."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.models.schemas import SemanticQuerySpec
from src.services.metric_knowledge import normalized_text
from src.services.semantic_value_mappings import (
    business_label_matches,
    mentioned_business_values,
    normalize_business_label,
    sample_value_candidates,
    scalar_value_key,
    value_has_business_evidence,
)

_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_QUERY_FRAME_WORDS = {
    "cho",
    "toi",
    "xem",
    "co",
    "bao",
    "nhieu",
    "la",
    "tong",
    "so",
    "luong",
    "cua",
    "cac",
    "trong",
    "voi",
    "o",
    "tai",
    "tren",
    "tu",
    "den",
    "bang",
    "ngoai",
    "khong",
    "phai",
    "hoac",
    "va",
    "da",
    "duoc",
    "ban",
    "ra",
    "theo",
    "tung",
    "moi",
    "nam",
    "thang",
    "quy",
    "tuan",
    "ngay",
    "hom",
    "nay",
    "qua",
    "truoc",
    "sau",
    "it",
    "nhat",
    "lon",
    "hon",
    "nho",
    "duoi",
    "cao",
    "giam",
    "tang",
    "chi",
    "ket",
    "hay",
    "tinh",
    "liet",
    "ke",
    "truy",
    "van",
    "xin",
    "vui",
    "long",
    "con",
    "bay",
    "gio",
    "tiep",
    "them",
    "don",
    "hang",
}


def _filter_values_have_evidence(spec: SemanticQuerySpec, catalog: dict[str, Any], evidence: str) -> bool:
    """Require categorical filters to be supported by user text or an approved mapping."""
    columns = {c["column_id"]: c for c in catalog.get("filter_columns", [])}
    for item in spec.filters:
        column = columns.get(item.column_id, {})
        if item.operator in {"is_null", "is_not_null"} or not _is_categorical(column):
            continue
        values = item.value if isinstance(item.value, list) else [item.value]
        if any(not value_has_business_evidence(value, column, evidence) for value in values):
            return False
    return True


def _requirements_covered(
    spec: SemanticQuerySpec,
    catalog: dict[str, Any],
    message: str,
    evidence: str = "",
    *,
    suggested_grouping: bool = False,
) -> bool:
    """Reject recognizable conditions omitted from the current user request."""
    metrics = {item["id"]: item for item in catalog.get("metrics", [])}
    text = normalized_text(_without_metric_names(message, spec, metrics))
    columns = {item["column_id"]: item for item in catalog.get("filter_columns", [])}
    compatible = set.intersection(*(set(metrics[mid].get("filter_column_ids", [])) for mid in spec.metric_ids))
    columns = {key: value for key, value in columns.items() if key in compatible}
    prior = evidence.rsplit("\n", 1)[0] if "\n" in evidence and _is_followup(message, spec, metrics) else ""
    if not _grouping_covered(spec, catalog, message, prior, text, suggested_grouping):
        return False
    time_text = _latest_time_text(prior, spec, metrics) if prior and not _mentions_time(text) else text
    if not _filter_requirements_covered(spec, columns, message, prior, time_text):
        return False
    return _categorical_requirements_covered(spec, columns, message, prior, metrics)


def _grouping_covered(
    spec: SemanticQuerySpec, catalog: dict[str, Any], message: str, prior: str, text: str, suggested_grouping: bool
) -> bool:
    if spec.dimensions and not suggested_grouping and not _mentions_grouping(message, prior):
        return False
    if spec.dimensions and not suggested_grouping and not _dimensions_match(spec, catalog, f"{prior}\n{message}"):
        return False
    if not suggested_grouping and not _requested_dimensions_covered(spec, catalog, message):
        return False
    if not spec.dimensions and _requests_grouping(text):
        return False
    return _ranking_covered(text, spec)


def _filter_requirements_covered(
    spec: SemanticQuerySpec, columns: dict[int, dict[str, Any]], message: str, prior: str, time_text: str
) -> bool:
    if any(_is_temporal(columns.get(item.column_id, {})) for item in spec.filters) and not _mentions_time(time_text):
        return False
    if not _time_requirements_covered(time_text, spec, columns):
        return False
    if not _numeric_values_covered(spec, columns, f"{prior}\n{message}"):
        return False
    if not _filter_operators_covered(spec, columns, f"{prior}\n{message}"):
        return False
    if not _requested_numeric_filters_covered(spec, columns, f"{prior}\n{message}"):
        return False
    return True


def _categorical_requirements_covered(
    spec: SemanticQuerySpec,
    columns: dict[int, dict[str, Any]],
    message: str,
    prior: str,
    metrics: dict[int, dict[str, Any]],
) -> bool:
    latest_text = _without_metric_names(message, spec, metrics)
    latest = _mentioned_values(latest_text, columns)
    if _has_unmapped_query_terms(latest_text, spec, columns, metrics):
        return False
    historical_text = _without_metric_names(prior, spec, metrics)
    historical = _mentioned_values(historical_text, columns)
    if prior and _has_unmapped_query_terms(historical_text, spec, columns, metrics):
        return False
    changed_columns = {column for choices in latest.values() for column, _ in choices}
    if prior and changed_columns and not _replacement_values_match(message, spec, latest, changed_columns):
        return False
    historical = {
        label: choices
        for label, choices in historical.items()
        if not changed_columns.intersection(c for c, _ in choices)
    }
    base_tables = {str(metrics[mid].get("base_entity", "")).casefold() for mid in spec.metric_ids if mid in metrics}
    return _mentioned_values_covered(message, latest, spec, columns, base_tables) and _mentioned_values_covered(
        prior, historical, spec, columns, base_tables
    )


def _has_unmapped_query_terms(
    text: str,
    spec: SemanticQuerySpec,
    columns: dict[int, dict[str, Any]],
    metrics: dict[int, dict[str, Any]],
) -> bool:
    """Detect missing mappings via column labels, mapping prefixes, or residual unfiltered conditions."""
    normalized = normalize_business_label(text)
    if not any(_is_categorical(column) for column in columns.values()):
        return False
    if any(
        _explicit_column_has_unmapped_value(normalized, column)
        for column in columns.values()
        if _is_categorical(column)
    ):
        return True
    if spec.dimensions or any(_is_categorical(columns.get(item.column_id, {})) for item in spec.filters):
        return False
    if _mentioned_values(text, columns):
        return False
    return _has_residual_condition_words(normalized, spec, columns, metrics)


def _explicit_column_has_unmapped_value(text: str, column: dict[str, Any]) -> bool:
    labels = [
        normalize_business_label(str(column.get(k, "")).replace("_", " "))
        for k in ("column_name", "business_name")
        if column.get(k)
    ]
    first_words = [
        words[0]
        for label, _ in mentioned_business_values(column)
        if len(words := normalize_business_label(label).split()) >= 2 and words[0] not in _QUERY_FRAME_WORDS
    ]
    prefixes = {word for word in first_words if first_words.count(word) >= 2}
    known = [normalize_business_label(label) for label, _ in mentioned_business_values(column)]
    if any(
        re.search(r"\b" + re.escape(label) + r"\s+(?:la|bang)\s+(?!duoc\b)", text)
        and not any(business_label_matches(text, value) for value in known)
        for label in labels
        if label
    ):
        return True
    return any(
        re.search(r"\b" + re.escape(prefix) + r"\s+\w+\b", text)
        and not any(business_label_matches(text, value) for value in known)
        for prefix in prefixes
    )


def _has_residual_condition_words(
    normalized: str,
    spec: SemanticQuerySpec,
    columns: dict[int, dict[str, Any]],
    metrics: dict[int, dict[str, Any]],
) -> bool:
    vocab = set(_QUERY_FRAME_WORDS)
    for mid in spec.metric_ids:
        for field in ("name", "business_name"):
            vocab.update(normalize_business_label(str(metrics.get(mid, {}).get(field, ""))).split())
    for column in columns.values():
        for field in ("column_name", "business_name", "table_name", "table_business_name"):
            vocab.update(normalize_business_label(str(column.get(field, "")).replace("_", " ")).split())
    residual = re.sub(r"\b\d+(?:\.\d+)?\b", " ", normalized)
    return any(len(word) > 1 and word not in vocab for word in residual.split())


def _without_metric_names(text: str, spec: SemanticQuerySpec, metrics: dict[int, dict[str, Any]]) -> str:
    for metric_id in spec.metric_ids:
        for name in (metrics[metric_id].get("name"), metrics[metric_id].get("business_name")):
            if isinstance(name, str) and name:
                text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
    return text


def _latest_time_text(prior: str, spec: SemanticQuerySpec, metrics: dict[int, dict[str, Any]]) -> str:
    for item in reversed(prior.splitlines()):
        text = normalized_text(_without_metric_names(item, spec, metrics))
        if _mentions_time(text):
            return text
    return ""


def _is_categorical(column: dict[str, Any]) -> bool:
    """Recognize SQL types whose labels can use approved mappings."""
    dtype = str(column.get("data_type", "")).upper()
    return any(kind in dtype for kind in ("CHAR", "TEXT", "ENUM"))


def _replacement_values_match(
    message: str, spec: SemanticQuerySpec, latest: dict[str, set[tuple[int, str]]], columns: set[int]
) -> bool:
    if re.match(r"^them\b", normalized_text(message.strip())):
        return False
    mentioned = {pair for choices in latest.values() for pair in choices}
    selected = {
        (item.column_id, scalar_value_key(value))
        for item in spec.filters
        if item.column_id in columns
        for value in (item.value if isinstance(item.value, list) else [item.value])
    }
    return selected <= mentioned


def _is_temporal(column: dict[str, Any]) -> bool:
    return any(part in str(column.get("data_type", "")).upper() for part in ("DATE", "TIME"))


def _numeric_values_covered(spec: SemanticQuerySpec, columns: dict[int, dict[str, Any]], text: str) -> bool:
    """Require numerical filter values to appear in the user's request."""
    for item in spec.filters:
        dtype = str(columns.get(item.column_id, {}).get("data_type", "")).upper()
        if (
            _is_temporal(columns.get(item.column_id, {}))
            or not any(kind in dtype for kind in ("INT", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL"))
            or item.operator in {"is_null", "is_not_null"}
        ):
            continue
        column = columns.get(item.column_id, {})
        names = (str(column.get("column_name", "")).replace("_", " "), str(column.get("business_name", "")))
        if not any(_contains_term(text, name) for name in names if name):
            return False
        values = item.value if isinstance(item.value, list) else [item.value]
        if any(not re.search(r"(?<![\w.])" + re.escape(str(value)) + r"(?![\w.])", text) for value in values):
            return False
    return True


def _filter_operators_covered(spec: SemanticQuerySpec, columns: dict[int, dict[str, Any]], text: str) -> bool:
    text = normalized_text(text)
    cues = {
        "gt": r"\b(tren|lon hon|nhieu hon)\b|(?<![<>=])>(?!=)",
        "gte": r"\b(tu|it nhat|lon hon hoac bang)\b|>=",
        "lt": r"\b(duoi|nho hon|it hon)\b|(?<![<>=])<(?!=)",
        "lte": r"\b(toi da|khong qua|nho hon hoac bang)\b|<=",
    }
    for item in spec.filters:
        column = columns.get(item.column_id, {})
        if item.operator in {"is_null", "is_not_null"}:
            names = (str(column.get("column_name", "")).replace("_", " "), str(column.get("business_name", "")))
            cue = (
                r"\b(null|rong|thieu|khong co|chua co)\b"
                if item.operator == "is_null"
                else r"\b(khong rong|khac null|co du lieu)\b"
            )
            if item.operator == "is_null" and re.search(r"\b(khong rong|khac null|co du lieu)\b", text):
                return False
            if not re.search(cue, text) or not any(_contains_term(text, name) for name in names if name):
                return False
        dtype = str(column.get("data_type", "")).upper()
        if not _is_temporal(column) and any(
            t in dtype for t in ("INT", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL")
        ):
            if item.operator in cues and not re.search(cues[item.operator], text):
                return False
    return True


def _requested_numeric_filters_covered(spec: SemanticQuerySpec, columns: dict[int, dict[str, Any]], text: str) -> bool:
    for clause in re.split(r"\b(?:va|hoac|and|or)\b", normalized_text(text)):
        for column_id, column in columns.items():
            dtype = str(column.get("data_type", "")).upper()
            if _is_temporal(column) or not any(
                t in dtype for t in ("INT", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL")
            ):
                continue
            names = (str(column.get("column_name", "")).replace("_", " "), str(column.get("business_name", "")))
            if not any(_contains_term(clause, name) for name in names if name):
                continue
            comparisons = {
                "gt": r"(?:\b(?:tren|lon hon|nhieu hon)\s+|(?<![<>=])>(?!=)\s*)(\d+(?:\.\d+)?)",
                "lt": r"(?:\b(?:duoi|nho hon|it hon)\s+|(?<![<>=])<(?!=)\s*)(\d+(?:\.\d+)?)",
                "gte": r"(?:\b(?:tu|it nhat|lon hon hoac bang)\s+|>=\s*)(\d+(?:\.\d+)?)",
                "lte": r"(?:\b(?:toi da|khong qua|nho hon hoac bang)\s+|<=\s*)(\d+(?:\.\d+)?)",
                "eq": r"\bbang\s+(\d+(?:\.\d+)?)",
            }
            for operator, pattern in comparisons.items():
                for match in re.findall(pattern, clause):
                    if not any(
                        f.column_id == column_id and f.operator == operator and str(f.value) == match
                        for f in spec.filters
                    ):
                        return False
            if re.search(r"\b(?:khong co|chua co|rong|null)\b", clause) and not any(
                f.column_id == column_id and f.operator == "is_null" for f in spec.filters
            ):
                return False
    return True


def _mentions_time(text: str) -> bool:
    return bool(
        re.search(
            r"(?<!\d)(?:19|20)\d{2}(?!\d)|\b(thang|tuan|nam) (?:nay|truoc)|\bhom (?:nay|qua)|\b(quy|thang)\s+\d", text
        )
    )


def _time_requirements_covered(text: str, spec: SemanticQuerySpec, columns: dict[int, dict[str, Any]]) -> bool:
    years = {int(value) for value in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text)}
    relative = re.search(r"\b((?:thang|tuan|nam) (?:nay|truoc)|hom nay|hom qua|(?:quy|thang)\s+\d+)\b", text)
    if not years and not relative:
        return True
    if years:
        bounds = _explicit_bounds(text)
        if bounds is not None:
            return _has_exact_interval(spec, columns, *bounds)
        if len(years) != 1:
            return False
        year = next(iter(years))
        month_group_columns = {
            item.column_id
            for item in spec.dimensions
            if item.time_grain == "month" and _is_temporal(columns.get(item.column_id, {}))
        }
        if re.search(r"\bthang\b", text) and month_group_columns:
            return _has_exact_interval(spec, columns, date(year, 1, 1), date(year + 1, 1, 1)) and any(
                item.column_id in month_group_columns and _is_temporal(columns.get(item.column_id, {}))
                for item in spec.filters
            )
        if re.search(r"\b(thang|quy|ngay|truoc|sau|tu|den)\b", text):
            return False
        return _has_exact_interval(spec, columns, date(year, 1, 1), date(year + 1, 1, 1))
    bounds = _relative_bounds(relative.group())
    return bool(bounds and _has_exact_interval(spec, columns, *bounds))


def _explicit_bounds(text: str) -> tuple[date, date] | None:
    month = re.search(r"\bthang\s+(\d{1,2})\s+nam\s+((?:19|20)\d{2})\b", text)
    if month and 1 <= int(month.group(1)) <= 12:
        start = date(int(month.group(2)), int(month.group(1)), 1)
        return start, (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    interval = re.search(r"\btu\s+nam\s+((?:19|20)\d{2})\s+den\s+nam\s+((?:19|20)\d{2})\b", text)
    if interval and int(interval.group(1)) <= int(interval.group(2)):
        return date(int(interval.group(1)), 1, 1), date(int(interval.group(2)) + 1, 1, 1)
    return None


def _relative_bounds(phrase: str) -> tuple[date, date] | None:
    today = datetime.now(_VN_TZ).date()
    if phrase in {"nam nay", "nam truoc"}:
        year = today.year - (1 if phrase == "nam truoc" else 0)
        return date(year, 1, 1), date(year + 1, 1, 1)
    if phrase == "hom nay":
        return today, today + timedelta(days=1)
    if phrase == "hom qua":
        return today - timedelta(days=1), today
    if phrase in {"tuan nay", "tuan truoc"}:
        start = today - timedelta(days=today.weekday() + (7 if phrase == "tuan truoc" else 0))
        return start, start + timedelta(days=7)
    if phrase in {"thang nay", "thang truoc"}:
        current = today.replace(day=1)
        next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        return (
            ((current - timedelta(days=1)).replace(day=1), current)
            if phrase == "thang truoc"
            else (current, next_month)
        )
    return None


def _has_exact_interval(spec: SemanticQuerySpec, columns: dict[int, dict[str, Any]], start: date, end: date) -> bool:
    temporal = [item for item in spec.filters if _is_temporal(columns.get(item.column_id, {}))]
    if len({item.column_id for item in temporal}) != 1:
        return False
    for column_id in {item.column_id for item in temporal}:
        filters = [item for item in temporal if item.column_id == column_id]
        expected = {("gte", start.isoformat()), ("lt", end.isoformat())}
        actual = {(item.operator, str(item.value)) for item in filters}
        if actual == expected:
            return True
    return False


def _ranking_covered(text: str, spec: SemanticQuerySpec) -> bool:
    top = re.search(r"\btop\s+(\d+)\b", text)
    if not top:
        return True
    if re.search(r"\b(thap nhat|it nhat|nho nhat)\b", text):
        return False
    return (
        spec.limit == int(top.group(1)) and spec.order_by == "metric_desc" and spec.order_metric_id in spec.metric_ids
    )


def _is_followup(message: str, spec: SemanticQuerySpec, metrics: dict[int, dict[str, Any]]) -> bool:
    text = normalized_text(message.strip())
    if re.match(r"^(chi|them|theo|bay gio|con|van|tiep|loc|phan theo)\b", text):
        return True
    return _mentions_time(text) and not any(
        normalized_text(str(metrics[mid].get(key) or "")) in text
        for mid in spec.metric_ids
        for key in ("name", "business_name")
        if metrics[mid].get(key)
    )


def _mentions_grouping(message: str, prior: str) -> bool:
    """Require an explicit grouping cue for selected dimensions."""
    text = normalized_text(f"{prior}\n{message}")
    return bool(re.search(r"\b(theo|tung|moi|nhom|phan|so sanh|top)\b", text))


def _requests_grouping(text: str) -> bool:
    """Recognize common explicit requests to break results down by a dimension."""
    return bool(
        re.search(
            r"\btop\s+\d+\b|\btheo\s+(?:tung\s+|moi\s+)?(?:khu vuc|san pham|kenh|khach hang|trang thai|chi nhanh|thang|ngay|quy)\b|\btheo\s+nam\b(?!\s+\d)",
            text,
        )
    )


def _dimensions_match(spec: SemanticQuerySpec, catalog: dict[str, Any], text: str) -> bool:
    """Require evidence for each selected dimension in the conversation."""
    columns = {item["column_id"]: item for item in catalog.get("dimensions", [])}
    grains = {"day": "ngay", "week": "tuan", "month": "thang", "quarter": "quy", "year": "nam"}
    requested = re.search(r"\btheo\s+(?:tung\s+|moi\s+)?(ngay|tuan|thang|quy|nam)\b", normalized_text(text))
    aliases = {
        "region": ("khu vuc", "vung"),
        "status": ("trang thai",),
        "channel": ("kenh",),
        "customer_id": ("khach hang",),
        "product_id": ("san pham",),
    }
    for dimension in spec.dimensions:
        column = columns.get(dimension.column_id, {})
        if requested and _is_temporal(column) and grains.get(dimension.time_grain) != requested.group(1):
            return False
        name = str(column.get("column_name", "")).lower()
        labels = [name.replace("_", " "), str(column.get("business_name", "")), *aliases.get(name, ())]
        if dimension.time_grain in grains:
            labels.append(grains[dimension.time_grain])
        if not any(_contains_term(text, label) for label in labels if label):
            return False
    return True


def _requested_dimensions_covered(spec: SemanticQuerySpec, catalog: dict[str, Any], text: str) -> bool:
    text = normalized_text(text)
    if not re.search(r"\btheo\b", text):
        return True
    grouping = re.split(r"\btheo\b", text, maxsplit=1)[1]
    selected = {item.column_id for item in spec.dimensions}
    metrics = {item["id"]: item for item in catalog.get("metrics", [])}
    compatible = set.intersection(*(set(metrics[mid].get("dimension_ids", [])) for mid in spec.metric_ids))
    aliases = {
        "region": ("khu vuc", "vung"),
        "status": ("trang thai",),
        "channel": ("kenh",),
        "customer_id": ("khach hang",),
        "product_id": ("san pham",),
    }
    for column in catalog.get("dimensions", []):
        if column["column_id"] not in compatible:
            continue
        name = str(column.get("column_name", "")).lower()
        labels = [name.replace("_", " "), str(column.get("business_name", "")), *aliases.get(name, ())]
        if any(_contains_term(grouping, label) for label in labels if label) and column["column_id"] not in selected:
            return False
    return True


def _column_value_keys(column_id: int, value: Any, column: dict[str, Any]) -> set[tuple[int, str]]:
    """Keep approved JSON scalars distinct from equivalent legacy sample values."""
    choices = {(column_id, scalar_value_key(value))}
    choices.update((column_id, scalar_value_key(sample)) for sample in sample_value_candidates(value, column))
    return choices


def _mentioned_values(text: str, columns: dict[int, dict[str, Any]]) -> dict[str, set[tuple[int, str]]]:
    """Find values mentioned through shared label normalization, preferring longest non-overlapping labels."""
    mentioned: dict[str, set[tuple[int, str]]] = {}
    for column_id, column in columns.items():
        for label, value in mentioned_business_values(column):
            if business_label_matches(text, label):
                mentioned.setdefault(normalize_business_label(label), set()).update(
                    _column_value_keys(column_id, value, column)
                )
    return _drop_subsumed_mentions(normalize_business_label(text), mentioned)


def _drop_subsumed_mentions(
    normalized_text_value: str, mentioned: dict[str, set[tuple[int, str]]]
) -> dict[str, set[tuple[int, str]]]:
    """Ignore a shorter label when every occurrence in text is part of a longer matched label."""
    keys = sorted(mentioned, key=len, reverse=True)
    kept: dict[str, set[tuple[int, str]]] = {}
    for key in keys:
        longer = [other for other in keys if len(other) > len(key) and business_label_matches(other, key)]
        residual = normalized_text_value
        for other in longer:
            residual = re.sub(r"(?<!\w)" + re.escape(other) + r"(?!\w)", " ", residual)
        if not longer or business_label_matches(residual, key):
            kept[key] = mentioned[key]
    return kept


def _narrow_column_choices(
    text: str,
    choices: set[tuple[int, str]],
    columns: dict[int, dict[str, Any]],
    base_tables: set[str],
) -> set[tuple[int, str]] | None:
    """Narrow duplicate label matches by explicit table/column mention or metric base table context."""
    explicitly_named = {
        c
        for c, _ in choices
        if any(_contains_term(text, str(columns[c].get(key, ""))) for key in ("table_name", "table_business_name"))
    }
    if len(explicitly_named) == 1:
        return {(c, v) for c, v in choices if c in explicitly_named}
    col_names = {str(columns[c].get("column_name", "")).casefold() for c, _ in choices}
    base_cols = {c for c, _ in choices if str(columns[c].get("table_name", "")).casefold() in base_tables}
    if len(col_names) == 1 and len(base_cols) == 1:
        return {(c, v) for c, v in choices if c in base_cols}
    return None


def _mentioned_values_covered(
    text: str,
    mentioned: dict[str, set[tuple[int, str]]],
    spec: SemanticQuerySpec,
    columns: dict[int, dict[str, Any]],
    base_tables: set[str] | None = None,
) -> bool:
    selected = [
        (item.column_id, scalar_value_key(value), item.operator)
        for item in spec.filters
        for value in (item.value if isinstance(item.value, list) else [item.value])
    ]
    if not _disjunction_covered(text, mentioned, spec):
        return False
    for label, choices in mentioned.items():
        if len({column for column, _ in choices}) > 1:
            narrowed = _narrow_column_choices(text, choices, columns, base_tables or set())
            if narrowed is None:
                return False
            choices = narrowed
        before = normalize_business_label(text).split(label, 1)[0]
        negative = bool(re.search(r"\b(khong|khac|tru|ngoai)(?:\s+\w+){0,3}$", before.strip()))
        operators = {"neq", "not_in"} if negative else {"eq", "in"}
        if not any((column, value) in choices and operator in operators for column, value, operator in selected):
            return False
    return True


def _disjunction_covered(text: str, mentioned: dict[str, set[tuple[int, str]]], spec: SemanticQuerySpec) -> bool:
    if len(mentioned) <= 1 or not re.search(r"\b(hoac|or)\b", normalized_text(text)):
        return True
    return any(
        item.operator == "in"
        and all(
            any((item.column_id, scalar_value_key(value)) in choices for value in item.value)
            for choices in mentioned.values()
        )
        for item in spec.filters
        if isinstance(item.value, list)
    )


def _contains_term(text: str, value: str) -> bool:
    return business_label_matches(text, value)
