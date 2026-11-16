"""Architecture rules, checked on the source:

- catppuccinizer.core never imports a target;
- a target only imports catppuccinizer.core (and its own sub-package), never
  another target;
- every built-in target exposes a TARGET object with a unique name.
"""
import ast
import sys
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "catppuccinizer"
sys.path.insert(0, str(PKG.parent))
sys.dont_write_bytecode = True


def imported_modules(path):
    """Absolute module names imported by a file of the catppuccinizer package."""
    rel = path.relative_to(PKG.parent).with_suffix("")
    package = list(rel.parts[:-1]) if rel.name != "__init__" else list(rel.parts[:-1])
    if rel.name == "__init__":
        package = list(rel.parts[:-1])
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            out.append(mod)
            out += [f"{mod}.{a.name}" for a in node.names]
    return [m for m in out if m.startswith("catppuccinizer")]


def target_of(module):
    parts = module.split(".")
    return parts[2] if len(parts) > 2 and parts[1] == "targets" else None


class Architecture(unittest.TestCase):
    def test_core_does_not_import_targets(self):
        for f in (PKG / "core").rglob("*.py"):
            for m in imported_modules(f):
                self.assertNotIn(".targets", m, f"{f.relative_to(PKG)} imports {m}")

    def test_targets_are_independent(self):
        for f in (PKG / "targets").rglob("*.py"):
            own = target_of(".".join(f.relative_to(PKG.parent).with_suffix("").parts))
            for m in imported_modules(f):
                other = target_of(m)
                if other is not None:
                    self.assertEqual(other, own, f"{f.relative_to(PKG)} imports target {m}")

    def test_builtin_targets(self):
        from catppuccinizer.core.target import BUILTIN, Target, discover
        targets = discover()
        for name in BUILTIN:
            self.assertIn(name, targets)
            self.assertIsInstance(targets[name], Target)
            self.assertEqual(targets[name].name, name)


if __name__ == "__main__":
    unittest.main()
