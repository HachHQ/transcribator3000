import unittest

from app.services.templates import (
    DEFAULT_PROMPTS,
    parse_prompt_kind,
    preview_prompt,
)


class PromptHelpersTests(unittest.TestCase):
    def test_parse_kind_aliases(self) -> None:
        self.assertEqual(parse_prompt_kind("notes"), "notes")
        self.assertEqual(parse_prompt_kind("default"), "notes")
        self.assertEqual(parse_prompt_kind("BRIEF"), "brief")
        self.assertEqual(parse_prompt_kind("classification"), "classify")
        self.assertIsNone(parse_prompt_kind("foo"))

    def test_preview_truncates(self) -> None:
        text = "a" * 50
        self.assertEqual(preview_prompt(text, 20), "a" * 19 + "…")
        self.assertEqual(preview_prompt("short", 100), "short")

    def test_defaults_exist(self) -> None:
        for kind in ("notes", "brief", "classify"):
            self.assertTrue(DEFAULT_PROMPTS[kind].strip())


if __name__ == "__main__":
    unittest.main()
