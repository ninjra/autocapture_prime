"""Minimal JSON schema validation for MX."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import SchemaValidationError


@dataclass(frozen=True)
class SchemaIssue:
    path: str
    message: str


class SchemaLiteValidator:
    """Minimal schema validator supporting object/array/scalar types."""

    def validate(self, schema: dict[str, Any], data: Any, path: str = "$") -> None:
        if "enum" in schema and data not in schema["enum"]:
            raise SchemaValidationError(f"{path}: value {data!r} not in enum {schema['enum']}")

        expected_type = schema.get("type")
        if expected_type:
            self._validate_type(expected_type, data, path)

        if expected_type == "object":
            self._validate_object(schema, data, path)
        elif expected_type == "array":
            self._validate_array(schema, data, path)
        elif expected_type in ("integer", "number"):
            self._validate_number(schema, data, path)

    def _validate_type(self, expected: str | list[str], data: Any, path: str) -> None:
        type_map = {
            "object": dict,
            "array": list,
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "null": type(None),
        }
        if isinstance(expected, list):
            for typ in expected:
                try:
                    self._validate_type(typ, data, path)
                    return
                except SchemaValidationError:
                    continue
            raise SchemaValidationError(f"{path}: expected one of {expected}, got {type(data).__name__}")
        if expected not in type_map:
            raise SchemaValidationError(f"{path}: unsupported schema type {expected}")
        if not isinstance(data, type_map[expected]):
            raise SchemaValidationError(f"{path}: expected {expected}, got {type(data).__name__}")
        if expected == "integer" and isinstance(data, bool):
            raise SchemaValidationError(f"{path}: expected integer, got boolean")

    def _validate_object(self, schema: dict[str, Any], data: dict[str, Any], path: str) -> None:
        required = schema.get("required", [])
        for key in required:
            if key not in data:
                raise SchemaValidationError(f"{path}: missing required field {key}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, value in data.items():
            if key in properties:
                self.validate(properties[key], value, f"{path}.{key}")
            else:
                if additional is False:
                    raise SchemaValidationError(f"{path}: unexpected field {key}")
                if isinstance(additional, dict):
                    self.validate(additional, value, f"{path}.{key}")

    def _validate_array(self, schema: dict[str, Any], data: list[Any], path: str) -> None:
        items = schema.get("items")
        if items is None:
            return
        for idx, item in enumerate(data):
            self.validate(items, item, f"{path}[{idx}]")

    def _validate_number(self, schema: dict[str, Any], data: Any, path: str) -> None:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and data < minimum:
            raise SchemaValidationError(f"{path}: value {data} below minimum {minimum}")
        if maximum is not None and data > maximum:
            raise SchemaValidationError(f"{path}: value {data} above maximum {maximum}")


_validator = SchemaLiteValidator()


def validate_schema(schema: dict[str, Any], data: Any) -> None:
    _validator.validate(schema, data)
