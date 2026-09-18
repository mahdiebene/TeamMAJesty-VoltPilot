"""Reject duplicate JSON keys and nonstandard NaN/Infinity tokens."""

import json


def load_json(data: str | bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Nonfinite JSON constant")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)