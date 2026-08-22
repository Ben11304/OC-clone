#!/usr/bin/env python3
# Copyright (c) 2024-2026 OpenConstruction Open Science Initiative
# SPDX-License-Identifier: Apache-2.0

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


for path in sorted(ROOT.glob("*.json")):
    load_json(path)

schema = load_json(ROOT / "dataset.schema.json")
data = load_json(ROOT / "datasets.json")

validator = Draft202012Validator(schema)
errors = sorted(validator.iter_errors(data), key=lambda e: e.path)

if errors:
    print("Schema validation failed:\n")
    for e in errors[:50]:
        path = ".".join(map(str, e.path)) or "<root>"
        print(f"- {path}: {e.message}")
    sys.exit(1)
else:
    print("All JSON files parsed; datasets.json validated successfully.")
