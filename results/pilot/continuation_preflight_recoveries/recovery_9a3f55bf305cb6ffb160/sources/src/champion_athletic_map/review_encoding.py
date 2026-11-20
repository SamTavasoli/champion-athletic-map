"""Represent complete coded findings with reversible column defaults and fields."""

from collections import Counter
from copy import deepcopy
import json


ENCODING_VERSION = "complete-check-columns-1"
ENCODING_NOTICE = (
    "check_results column data uses values, a default with [row,value] exceptions, "
    "or pool values selected by indexes. "
    "Each shared_fields entry [rows,fields] restores fields into those row objects. "
    "Rebuild findings in row order using columns; fields holds the other original report fields. "
    "All findings and values are retained."
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _size(value):
    return len(_json(value).encode("utf-8"))


def _column(values, cost=_size):
    plain = {"values": deepcopy(values)}
    if not values:
        return plain
    identities = [_json(value) for value in values]
    most, _ = Counter(identities).most_common(1)[0]
    default = values[identities.index(most)]
    factored = {"default": deepcopy(default), "exceptions": [[i, deepcopy(value)]
        for i, value in enumerate(values) if identities[i] != most]}
    pool, indexes, seen = [], [], {}
    for identity, value in zip(identities, values):
        if identity not in seen:
            seen[identity] = len(pool)
            pool.append(deepcopy(value))
        indexes.append(seen[identity])
    pooled = {"pool": pool, "indexes": indexes}
    return min((plain, factored, pooled), key=cost)


def _encode_column(values, cost=_size):
    best = _column(values, cost)
    objects = [(i, value) for i, value in enumerate(values) if type(value) is dict]
    seen = set()
    for first, (_, a) in enumerate(objects):
        for _, b in objects[first + 1:]:
            common = {key: deepcopy(value) for key, value in a.items()
                if key in b and _json(value) == _json(b[key])}
            identity = _json(common)
            if not common or identity in seen:
                continue
            seen.add(identity)
            indexes = [i for i, value in objects
                if all(key in value and _json(value[key]) == _json(item) for key, item in common.items())]
            variants = deepcopy(values)
            for i in indexes:
                variants[i] = {key: value for key, value in variants[i].items() if key not in common}
            candidate = {**_column(variants, cost), "shared_fields": [[indexes, common]]}
            if cost(candidate) < cost(best):
                best = candidate
    return best


def encode_checks(report, count_tokens=None):
    """Retain unrecognized report shapes rather than guessing their structure."""
    if (type(report) is not dict or type(report.get("columns")) is not list
            or type(report.get("findings")) is not list
            or any(type(key) is not str for key in report["columns"])
            or len(set(report["columns"])) != len(report["columns"])
            or any(type(row) is not list or len(row) != len(report["columns"]) for row in report["findings"])):
        return deepcopy(report)
    def cost(value):
        if count_tokens is None:
            return _size(value)
        tokens = count_tokens(_json(value))
        if type(tokens) is not int or tokens < 0:
            raise ValueError("The review token counter must return a nonnegative integer.")
        return tokens
    result = {"encoding": ENCODING_VERSION,
        "fields": {key: deepcopy(value) for key, value in report.items() if key not in ("columns", "findings")},
        "columns": deepcopy(report["columns"]), "row_count": len(report["findings"]),
        "data": [_encode_column([row[i] for row in report["findings"]], cost) for i in range(len(report["columns"]))]}
    return result if cost(result) < cost(report) else deepcopy(report)


def _indexes(rows, count):
    if (type(rows) is not list or any(type(i) is not int or not 0 <= i < count for i in rows)
            or len(rows) != len(set(rows))):
        raise ValueError("Encoded check row indexes are invalid.")
    return rows


def decode_checks(report):
    if type(report) is not dict or "findings" in report or report.get("encoding") != ENCODING_VERSION:
        return deepcopy(report)
    if (set(report) != {"encoding", "fields", "columns", "row_count", "data"}
            or type(report["fields"]) is not dict or {"columns", "findings"} & set(report["fields"])
            or type(report["columns"]) is not list or any(type(key) is not str for key in report["columns"])
            or len(report["columns"]) != len(set(report["columns"]))
            or type(report["row_count"]) is not int or report["row_count"] < 0
            or type(report["data"]) is not list or len(report["data"]) != len(report["columns"])):
        raise ValueError("The encoded check report has invalid metadata.")
    count, columns = report["row_count"], []
    for column in report["data"]:
        if type(column) is not dict:
            raise ValueError("An encoded check column is invalid.")
        content = set(column) - {"shared_fields"}
        if content == {"values"} and type(column["values"]) is list and len(column["values"]) == count:
            values = deepcopy(column["values"])
        elif content == {"default", "exceptions"} and type(column["exceptions"]) is list:
            values = [deepcopy(column["default"]) for _ in range(count)]
            exceptions = column["exceptions"]
            if any(type(row) is not list or len(row) != 2 for row in exceptions):
                raise ValueError("An encoded check exception is invalid.")
            _indexes([row[0] for row in exceptions], count)
            for i, value in exceptions:
                values[i] = deepcopy(value)
        elif (content == {"pool", "indexes"} and type(column["pool"]) is list
                and type(column["indexes"]) is list and len(column["indexes"]) == count
                and all(type(i) is int and 0 <= i < len(column["pool"]) for i in column["indexes"])):
            values = [deepcopy(column["pool"][i]) for i in column["indexes"]]
        else:
            raise ValueError("An encoded check column has invalid fields or length.")
        groups, touched = column.get("shared_fields", []), set()
        if type(groups) is not list:
            raise ValueError("Encoded shared check fields are invalid.")
        for group in groups:
            if type(group) is not list or len(group) != 2 or type(group[1]) is not dict:
                raise ValueError("Encoded shared check fields are invalid.")
            indexes, fields = _indexes(group[0], count), group[1]
            for i in indexes:
                if i in touched or type(values[i]) is not dict or set(values[i]) & set(fields):
                    raise ValueError("Shared check fields overlap or do not describe an object.")
                touched.add(i)
                values[i] = {**deepcopy(fields), **values[i]}
        columns.append(values)
    return {**deepcopy(report["fields"]), "columns": deepcopy(report["columns"]),
        "findings": [[deepcopy(column[i]) for column in columns] for i in range(count)]}


def encode_view(view):
    result = deepcopy(view)
    if type(result) is dict and "check_results" in result:
        result["check_results"] = encode_checks(result["check_results"])
    return result


def decode_view(view):
    result = deepcopy(view)
    if type(result) is dict and "check_results" in result:
        result["check_results"] = decode_checks(result["check_results"])
    return result


encode_review = encode_view
decode_review = decode_view
