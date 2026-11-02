from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.record_examples import record_scenario, render_transcript, scenarios
from test_agent import make_agent, response, tool_call


class RecorderTests(unittest.TestCase):
    def test_five_multiturn_scenarios_use_explicit_dates(self):
        cases = scenarios(date(2026, 11, 2))
        self.assertEqual(len(cases), 5)
        self.assertTrue(all(len(turns) >= 3 for _, turns in cases))
        self.assertIn("2026-10-28", cases[3][1][1])
        self.assertIn("2026-09-18", cases[3][1][2])
        self.assertIn("wrong@example.com", cases[2][1][2])

    def test_recorder_preserves_calls_results_and_separate_turns(self):
        agent = make_agent(response(calls=[tool_call()]), response("Hoje."), response("Até mais."))
        with TemporaryDirectory() as directory:
            path = record_scenario(agent, "example", ["Hoje?", "Obrigado"], Path(directory))
            text = path.read_text(encoding="utf-8")
            self.assertIn("Status: complete", text)
            self.assertIn("get_today", text)
            self.assertIn("Tool result — call_1", text)
            self.assertEqual(text.count("## Customer"), 2)
            self.assertFalse((Path(directory) / "example.partial.md").exists())
            self.assertNotIn("Você é o", text)

    def test_recorder_retains_failed_attempt_without_claiming_completion(self):
        agent = make_agent(response("Olá"), RuntimeError("secret-provider-detail"))
        with TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                record_scenario(agent, "failed", ["Oi", "Hoje?"], Path(directory))
            text = (Path(directory) / "failed.partial.md").read_text(encoding="utf-8")
            self.assertIn("Status: failed (RuntimeError)", text)
            self.assertIn("Hoje?", text)
            self.assertNotIn("secret-provider-detail", text)
            self.assertFalse((Path(directory) / "failed.md").exists())

    def test_markdown_fences_cannot_be_closed_by_reply(self):
        result = render_transcript("example", "test", [
            {"role": "assistant", "content": "```text\nreply\n```"}], "now")
        self.assertIn("````text", result)
