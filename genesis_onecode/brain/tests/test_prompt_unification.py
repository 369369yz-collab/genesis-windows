"""test_prompt_unification.py — drift guard for the canonical prompt.

GENESIS embed step 7, Phase 2, gap G5 (2026-10-21). The model was
trained with SYSTEM from repo/model/dataset/build_369_dataset.py baked
into all 3,227 SFT+DPO records. service.py's runtime SYSTEM_PROMPT must
be that exact string, character for character — the model only ever saw
the trained prompt, so a divergent runtime prompt is a silent identity
drift. This test parses BOTH source files with ast (executing neither)
and asserts equality, so the two can never silently diverge again.
"""

import ast
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVICE = os.path.abspath(os.path.join(_HERE, "..", "..", "service.py"))
_DATASET = os.path.abspath(os.path.join(
    _HERE, "..", "..", "..", "model", "dataset", "build_369_dataset.py"))


def _extract_assign(path, name):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


class TestPromptUnification(unittest.TestCase):

    def test_runtime_prompt_equals_trained_prompt(self):
        trained = _extract_assign(_DATASET, "SYSTEM")
        runtime = _extract_assign(_SERVICE, "SYSTEM_PROMPT")
        self.assertEqual(runtime, trained)

    def test_prompt_is_the_genesis_identity(self):
        trained = _extract_assign(_DATASET, "SYSTEM")
        self.assertTrue(trained.startswith("You are GENESIS"))
        self.assertIn("YZ (Younes Montazeriani)", trained)
        self.assertIn("پدر", trained)


if __name__ == "__main__":
    unittest.main()
