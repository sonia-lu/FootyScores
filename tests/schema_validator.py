"""A small JSON Schema validator, so the tests need no external packages.

It supports only the keywords used in schema/match.schema.json, and stops with
an error if the schema uses any other keyword, so it can never silently skip a
check. A test pipeline can validate against the same schema with any standard
JSON Schema tool instead (e.g. the "jsonschema" Python package or ajv).
"""

import re

SUPPORTED = {
    "$schema", "$id", "$defs", "$ref", "title", "description",
    "type", "required", "properties", "additionalProperties",
    "items", "minItems", "maxItems", "minimum", "pattern",
}

TYPES = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    # In Python, true/false also count as numbers, so exclude them explicitly.
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
}


def validate(data, schema: dict) -> list:
    """Return a list of problems, e.g. ['$.scorers[0].minute: must be integer']; empty if valid."""
    problems = []
    check(data, schema, schema, "$", problems)
    return problems


def check(data, schema: dict, root: dict, where: str, problems: list) -> None:
    unknown = set(schema) - SUPPORTED
    if unknown:
        raise ValueError(f"schema keywords not supported by this validator: {sorted(unknown)}")

    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]  # "#/$defs/player" -> "player"
        check(data, root["$defs"][name], root, where, problems)
        return

    expected_type = schema.get("type")
    if expected_type and not TYPES[expected_type](data):
        problems.append(f"{where}: must be {expected_type}, not {data!r}")
        return  # the other checks only make sense for the right type

    if isinstance(data, dict):
        for field in schema.get("required", []):
            if field not in data:
                problems.append(f"{where}: missing field {field!r}")
        properties = schema.get("properties", {})
        for field, value in data.items():
            if field in properties:
                check(value, properties[field], root, f"{where}.{field}", problems)
            elif schema.get("additionalProperties") is False:
                problems.append(f"{where}: unexpected field {field!r}")

    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            problems.append(f"{where}: must have at least {schema['minItems']} items, has {len(data)}")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            problems.append(f"{where}: must have at most {schema['maxItems']} items, has {len(data)}")
        if "items" in schema:
            for index, item in enumerate(data):
                check(item, schema["items"], root, f"{where}[{index}]", problems)

    if "minimum" in schema and data < schema["minimum"]:
        problems.append(f"{where}: must be at least {schema['minimum']}, not {data}")
    if "pattern" in schema and not re.search(schema["pattern"], data):
        problems.append(f"{where}: {data!r} does not match {schema['pattern']}")
