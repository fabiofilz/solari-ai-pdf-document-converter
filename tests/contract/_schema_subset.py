"""A minimal JSON-Schema 2020-12 **subset** validator for the contract tests.

The project deliberately avoids the ``jsonschema`` runtime dependency (research §7 — the
committed ``contracts/*.schema.json`` are *generated from* the pydantic models, not
hand-synced against a validator). The Phase 4A contract tests still need to assert that a
model-built instance conforms to the committed contract, so this module implements just the
keywords the committed schemas actually use:

``type`` (incl. a list of types), ``const``, ``enum``, ``required``, ``properties``,
``additionalProperties: false``, ``items``, ``minItems`` / ``maxItems``, ``minLength``,
``minimum`` / ``maximum``, ``pattern``, ``$ref`` to ``#/$defs/<name>``, and ``oneOf`` /
``anyOf`` (first branch that validates wins).

It is intentionally strict and small — not a general validator. ``validate()`` returns a
list of human-readable error strings; an empty list means the instance conforms.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["validate", "assert_valid"]

_JSON_TYPE = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return isinstance(value, _JSON_TYPE[expected])


def _resolve(schema: dict, root: dict) -> dict:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/$defs/"):
        raise ValueError(f"unsupported $ref {ref!r}")
    return root["$defs"][ref.removeprefix("#/$defs/")]


def _validate(value: Any, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    schema = _resolve(schema, root)

    if "oneOf" in schema or "anyOf" in schema:
        branches = schema.get("oneOf") or schema.get("anyOf")
        if not any(not _collect(value, b, root, path) for b in branches):
            errors.append(f"{path}: matched none of {len(branches)} oneOf/anyOf branches")
        return

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: {value!r} != const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']!r}")

    types = schema.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else types
        if not any(_type_ok(value, t) for t in types):
            errors.append(f"{path}: {type(value).__name__} not in type {types}")
            return

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: string shorter than minLength {schema['minLength']}")
        pat = schema.get("pattern")
        if pat is not None and re.search(pat, value) is None:
            errors.append(f"{path}: {value!r} does not match pattern {pat!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > maximum {schema['maximum']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: {len(value)} items < minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: {len(value)} items > maxItems {schema['maxItems']}")
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(value):
                _validate(item, item_schema, root, f"{path}[{i}]", errors)

    if isinstance(value, dict):
        props: dict[str, Any] = schema.get("properties", {})
        # A property whose value is ``None`` and whose schema does not allow ``null`` is
        # treated as absent — this mirrors pydantic's ``model_dump`` emitting ``null`` for
        # an unset Optional field the committed schema models as simply optional.
        present = {
            k: v for k, v in value.items()
            if not (v is None and not _allows_null(props.get(k, {}), root))
        }
        for req in schema.get("required", []):
            if req not in present:
                errors.append(f"{path}: missing required property {req!r}")
        if schema.get("additionalProperties") is False:
            extra = set(present) - set(props)
            if extra:
                errors.append(f"{path}: unexpected properties {sorted(extra)}")
        for key, sub in present.items():
            if key in props:
                _validate(sub, props[key], root, f"{path}.{key}", errors)


def _allows_null(schema: dict, root: dict) -> bool:
    schema = _resolve(schema, root)
    t = schema.get("type")
    if t == "null" or (isinstance(t, list) and "null" in t):
        return True
    for branch in schema.get("oneOf", []) + schema.get("anyOf", []):
        if _allows_null(branch, root):
            return True
    return False


def _collect(value: Any, schema: dict, root: dict, path: str) -> list[str]:
    errs: list[str] = []
    _validate(value, schema, root, path, errs)
    return errs


def validate(instance: Any, schema: dict) -> list[str]:
    """Return a list of conformance errors (empty ⇒ the instance conforms)."""
    return _collect(instance, schema, schema, "$")


def assert_valid(instance: Any, schema: dict) -> None:
    errors = validate(instance, schema)
    assert not errors, (
        "instance does not conform to the committed schema:\n  " + "\n  ".join(errors)
    )
