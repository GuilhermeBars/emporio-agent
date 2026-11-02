import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from src.agent import Agent, STEP_LIMIT_REPLY


def response(content=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=calls))])


def tool_call(name="get_today", arguments="{}", call_id="call_1"):
    data = {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": arguments}}
    return SimpleNamespace(id=call_id, function=SimpleNamespace(**data["function"]),
                           model_dump=lambda **kwargs: data)


def make_agent(*responses):
    client = Mock()
    client.chat.completions.create.side_effect = responses
    return Agent(client=client)


class AgentTests(unittest.TestCase):
    def test_tool_calls_and_multiturn_history(self):
        agent = make_agent(response(calls=[tool_call()]), response("Hoje."), response("Até mais."))
        self.assertEqual(agent.chat("Que dia é hoje?"), "Hoje.")
        self.assertEqual(agent.messages[3]["role"], "tool")
        self.assertEqual(agent.messages[3]["tool_call_id"], "call_1")
        self.assertEqual(agent.chat("Obrigado"), "Até mais.")
        self.assertEqual([m["role"] for m in agent.messages], [
            "system", "user", "assistant", "tool", "assistant", "user", "assistant"])

    def test_bad_tool_calls_return_errors_to_model(self):
        for name, args in (("unknown_tool", "{}"), ("get_today", "{"),
                           ("get_today", "[]"), ("get_order_status", "{}")):
            with self.subTest(name=name, arguments=args):
                agent = make_agent(response(calls=[tool_call(name, args)]), response("Vou tentar novamente."))
                agent.chat("Ajude")
                self.assertIn("error", json.loads(agent.messages[3]["content"]))

    def test_all_parallel_tool_calls_receive_results(self):
        agent = make_agent(response(calls=[tool_call(call_id="a"), tool_call(call_id="b")]), response("Ok"))
        agent.chat("Hoje?")
        self.assertEqual([m["tool_call_id"] for m in agent.messages if m["role"] == "tool"], ["a", "b"])

    def test_step_limit_is_recorded_and_history_remains_usable(self):
        agent = make_agent(response(calls=[tool_call()]), response("Olá"))
        self.assertEqual(agent.chat("Hoje?", max_steps=1), STEP_LIMIT_REPLY)
        self.assertEqual(agent.messages[-1], {"role": "assistant", "content": STEP_LIMIT_REPLY})
        self.assertEqual(agent.chat("Olá"), "Olá")

    def test_api_failure_rolls_back_entire_turn(self):
        agent = make_agent(response("Olá"), response(calls=[tool_call()]), RuntimeError("provider failed"))
        agent.chat("Oi")
        previous = copy.deepcopy(agent.messages)
        with self.assertRaises(RuntimeError):
            agent.chat("Hoje?")
        self.assertEqual(agent.messages, previous)

    def test_empty_response_has_recorded_fallback(self):
        agent = make_agent(response())
        self.assertTrue(agent.chat("Oi"))
        self.assertTrue(agent.messages[-1]["content"])
