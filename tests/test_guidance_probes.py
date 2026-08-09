from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / "experiments" / "guidance-probes"


class GuidanceProbeTests(unittest.TestCase):
    def test_probe_schema_and_examples_are_offline_and_deterministic(self) -> None:
        schema = json.loads((PROBES / "schema.json").read_text(encoding="utf-8"))
        self.assertEqual(1, schema["schema_version"])
        required = set(schema["required"])
        optional = set(schema["optional"])
        self.assertTrue(required)
        for path in sorted(PROBES.glob("*.json")):
            if path.name == "schema.json":
                continue
            with self.subTest(path=path.name):
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertTrue(required <= set(value))
                self.assertFalse(set(value) - required - optional)
                self.assertRegex(value["id"], r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
                for field in (
                    "expected_allowed_behaviours",
                    "expected_forbidden_behaviours",
                    "required_outcome_checks",
                ):
                    self.assertTrue(value[field])
                    self.assertTrue(all(isinstance(item, str) and item.strip() for item in value[field]))
                self.assertNotIn("http://", json.dumps(value))
                self.assertNotIn("https://", json.dumps(value))


if __name__ == "__main__":
    unittest.main()
