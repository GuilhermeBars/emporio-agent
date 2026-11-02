import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.record_examples import main as record_main
from src.agent import Agent
from src import agent as agent_module
from src.codex_provider import CodexClient, CodexError
from src.config import ProviderConfig, load_dotenv
from src.main import main as interactive_main


@pytest.fixture(autouse=True)
def provider_environment(monkeypatch):
    for name in ("LLM_PROVIDER", "OPENAI_API_KEY", "GROQ_API_KEY", "MODEL",
                 "CODEX_BIN", "CODEX_MODEL", "CODEX_TIMEOUT", "DEBUG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("src.config.load_dotenv", Mock())


@pytest.fixture
def run(monkeypatch):
    mocked = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr("src.codex_provider.subprocess.run", mocked)
    return mocked


def complete(run, text):
    run.return_value.stdout = text
    return CodexClient().chat.completions.create(
        model="codex-cli", messages=[{"role": "user", "content": "Oi"}],
        tools=[], temperature=0.2).choices[0].message


def test_tool_call_parsing_and_openai_dict(run):
    message = complete(run, json.dumps({"content": None, "tool_calls": [
        {"name": "search_products", "arguments": {"query": "violão", "limit": 2}},
        {"name": "get_today", "arguments": {}}]}))
    assert message.content is None
    first, second = message.tool_calls
    assert first.type == "function"
    assert first.function.name == "search_products"
    assert json.loads(first.function.arguments) == {"query": "violão", "limit": 2}
    assert first.id.startswith("call_")
    assert len(first.id) == 17
    int(first.id[5:], 16)
    assert first.id != second.id
    assert first.model_dump(exclude_none=True) == {
        "id": first.id, "type": "function", "function": {
            "name": "search_products", "arguments": first.function.arguments}}


def test_plain_content(run):
    message = complete(run, '{"content": "Olá!", "tool_calls": []}')
    assert message.content == "Olá!"
    assert message.tool_calls == []


@pytest.mark.parametrize("wrapper", ["```json\n{}\n```", "```\n{}\n```",
                                     "Here is the reply:\n{}\nDone."])
def test_fenced_json_and_surrounding_text(run, wrapper):
    message = complete(run, wrapper.format(json.dumps({
        "content": 'Nested braces { and } and a quote " are safe.', "tool_calls": []})))
    assert message.content == 'Nested braces { and } and a quote " are safe.'
    assert message.tool_calls == []


@pytest.mark.parametrize("text", ["A normal reply.", "```json\n{broken}\n```",
                                 '{"content": 12}', '{"tool_calls": "bad"}',
                                 '{"tool_calls": [{"name": "get_today", "arguments": []}]}',
                                 '{"unrelated": "object"}'])
def test_unparseable_or_invalid_response_falls_back_to_original_text(run, text):
    message = complete(run, text)
    assert message.content == text
    assert message.tool_calls == []


def test_extracts_first_json_object(run):
    message = complete(run, '{"content":"first"} {"content":"second"}')
    assert message.content == "first"


def test_subprocess_contract_and_temporary_directory_cleanup(run):
    complete(run, '{"content":"ok","tool_calls":[]}')
    args, kwargs = run.call_args
    command = args[0]
    assert command == ["codex", "exec", "--skip-git-repo-check", "-s", "read-only",
                       "--output-last-message", str(Path(kwargs["cwd"]) / "answer.txt"), "-"]
    assert kwargs["timeout"] == 180
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["capture_output"] is True
    assert kwargs["check"] is False
    assert not Path(kwargs["cwd"]).exists()


def test_codex_environment_overrides(run, monkeypatch):
    monkeypatch.setenv("CODEX_BIN", "C:/Program Files/Codex/codex.exe")
    monkeypatch.setenv("CODEX_MODEL", "custom-model")
    monkeypatch.setenv("CODEX_TIMEOUT", "42.5")
    complete(run, "ok")
    command = run.call_args.args[0]
    assert command[0] == "C:/Program Files/Codex/codex.exe"
    assert command[-3:] == ["-m", "custom-model", "-"]
    assert run.call_args.kwargs["timeout"] == 42.5


@pytest.mark.parametrize("timeout", ["0", "-1", "bad", "nan", "inf"])
def test_invalid_timeout_is_rejected(monkeypatch, timeout):
    monkeypatch.setenv("CODEX_TIMEOUT", timeout)
    with pytest.raises(ValueError, match="CODEX_TIMEOUT"):
        CodexClient()


def test_output_file_takes_precedence_over_stdout(run):
    def write_answer(command, **kwargs):
        assert Path(kwargs["cwd"]).is_dir()
        answer_file = Path(command[command.index("--output-last-message") + 1])
        answer_file.write_text('{"content":"Olá do arquivo","tool_calls":[]}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "CLI progress", "")

    run.side_effect = write_answer
    assert complete(run, "ignored").content == "Olá do arquivo"


def test_empty_output_file_falls_back_to_stdout(run):
    def write_empty_answer(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, '{"content":"stdout","tool_calls":[]}', "")

    run.side_effect = write_empty_answer
    assert complete(run, "ignored").content == "stdout"


def test_timeout_raises_safe_codex_error(run):
    run.side_effect = subprocess.TimeoutExpired("secret command", 180, output="private prompt")
    with pytest.raises(CodexError, match="timed out") as error:
        complete(run, "")
    assert "private" not in str(error.value)
    assert "secret" not in str(error.value)
    assert not Path(run.call_args.kwargs["cwd"]).exists()


def test_missing_binary_raises_codex_error(run):
    run.side_effect = FileNotFoundError("private path")
    with pytest.raises(CodexError, match="binary not found") as error:
        complete(run, "")
    assert "private" not in str(error.value)


def test_nonzero_exit_raises_safe_codex_error(run):
    run.return_value = subprocess.CompletedProcess([], 1, "private stdout", "private stderr")
    with pytest.raises(CodexError, match="exited unsuccessfully") as error:
        complete(run, "private stdout")
    assert "private" not in str(error.value)


def test_prompt_contains_full_conversation_schemas_and_tool_results(run):
    messages = [
        {"role": "system", "content": "Follow store rules."},
        {"role": "user", "content": "Que dia é hoje?"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_previous", "type": "function",
            "function": {"name": "get_today", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_previous", "content": "2026-11-02"},
    ]
    tools = [{"type": "function", "function": {"name": "get_today", "parameters": {
        "type": "object", "properties": {}, "required": []}}}]
    CodexClient().chat.completions.create(model="codex-cli", messages=messages,
                                          tools=tools, temperature=0.2)
    prompt = run.call_args.kwargs["input"]
    payload = json.loads(prompt.split("\n\n", 1)[1])
    assert payload == {"messages": messages, "tools": tools, "temperature": 0.2}
    assert "ONLY as the chat model" in prompt
    assert "Do not run commands or read files" in prompt
    assert "exactly one JSON object" in prompt


@pytest.mark.parametrize("model,label", [("", "codex-cli"), ("custom-model", "codex-cli:custom-model")])
def test_config_selects_codex_without_keys(monkeypatch, model, label):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("CODEX_MODEL", model)
    config = ProviderConfig.from_env()
    assert config.provider == "codex"
    assert config.api_key == ""
    assert config.model == label


def test_codex_can_be_selected_via_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("LLM_PROVIDER=codex\nCODEX_MODEL=dotenv-model\n", encoding="utf-8")
    monkeypatch.setattr("src.config.ROOT", tmp_path)
    monkeypatch.setattr("src.config.load_dotenv", load_dotenv)
    # Let monkeypatch restore the variables that python-dotenv will set.
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.delenv("LLM_PROVIDER")
    monkeypatch.setenv("CODEX_MODEL", "")
    monkeypatch.delenv("CODEX_MODEL")
    assert ProviderConfig.from_env().model == "codex-cli:dotenv-model"


def test_dotenv_does_not_override_shell_provider(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("LLM_PROVIDER=openai\n", encoding="utf-8")
    monkeypatch.setattr("src.config.ROOT", tmp_path)
    monkeypatch.setattr("src.config.load_dotenv", load_dotenv)
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    assert ProviderConfig.from_env().provider == "codex"


def test_agent_codex_loop_without_openai_import(monkeypatch, run):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("CODEX_MODEL", "test-model")
    monkeypatch.setitem(sys.modules, "openai", None)
    run.side_effect = [
        subprocess.CompletedProcess([], 0, '{"content":null,"tool_calls":[{"name":"get_today","arguments":{}}]}', ""),
        subprocess.CompletedProcess([], 0, '{"content":"Hoje.","tool_calls":[]}', ""),
        subprocess.CompletedProcess([], 0, '{"content":"Até mais.","tool_calls":[]}', ""),
    ]
    monkeypatch.setitem(agent_module.TOOLS, "get_today", lambda: "2026-11-02")
    agent = Agent()
    assert isinstance(agent.client, CodexClient)
    assert agent.model == "codex-cli:test-model"
    assert agent.chat("Hoje?") == "Hoje."
    second_prompt = json.loads(run.call_args_list[1].kwargs["input"].split("\n\n", 1)[1])
    assert second_prompt["messages"] == agent.messages[:-1]
    assert second_prompt["messages"][-1] == {
        "role": "tool", "tool_call_id": agent.messages[2]["tool_calls"][0]["id"], "content": "2026-11-02"}
    assert agent.chat("Obrigado") == "Até mais."
    assert [message["role"] for message in agent.messages] == [
        "system", "user", "assistant", "tool", "assistant", "user", "assistant"]


def test_agent_loop_with_fake_client_sequence(run):
    call_response = CodexClient().chat.completions.create
    run.return_value.stdout = '{"content":null,"tool_calls":[{"name":"get_today","arguments":{}}]}'
    first = call_response(model="codex-cli", messages=[])
    run.return_value.stdout = '{"content":"Hoje.","tool_calls":[]}'
    second = call_response(model="codex-cli", messages=[])
    client = Mock()
    client.chat.completions.create.side_effect = [first, second]
    agent = Agent(model="codex-cli", client=client)
    assert agent.chat("Hoje?") == "Hoje."
    assert client.chat.completions.create.call_count == 2
    assert agent.messages[3]["role"] == "tool"


def test_codex_error_rolls_back_agent_turn(monkeypatch, run):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    agent = Agent()
    previous = list(agent.messages)
    run.side_effect = subprocess.TimeoutExpired("codex", 180)
    with pytest.raises(CodexError):
        agent.chat("Hoje?")
    assert agent.messages == previous


def test_recorder_catches_codex_error_without_openai(monkeypatch, tmp_path, run, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.setattr("scripts.record_examples.scenarios", lambda today: [("example", ["Oi"])])
    run.side_effect = FileNotFoundError("private detail")
    assert record_main(["--output-dir", str(tmp_path)]) == 1
    error = capsys.readouterr().err
    assert "Failed example (CodexError)" in error
    assert "private detail" not in error
    partial = (tmp_path / "example.partial.md").read_text(encoding="utf-8")
    assert "Model: `codex-cli`" in partial
    assert "failed (CodexError)" in partial
    assert not (tmp_path / "example.md").exists()


@pytest.mark.parametrize("key,base,model", [
    ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
])
def test_agent_preserves_api_provider_construction(monkeypatch, key, base, model):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv(key, "test-key")
    constructor = Mock()
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=constructor))
    agent = Agent()
    assert agent.client is constructor.return_value
    assert agent.model == model
    constructor.assert_called_once_with(base_url=base, api_key="test-key", timeout=60.0, max_retries=2)


def test_recorder_still_catches_openai_errors(monkeypatch, tmp_path, capsys):
    class FakeOpenAIError(Exception):
        pass

    agent = Mock(model="test-model", messages=[])
    agent.chat.side_effect = FakeOpenAIError("private detail")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAIError=FakeOpenAIError))
    monkeypatch.setattr("scripts.record_examples.Agent", Mock(return_value=agent))
    monkeypatch.setattr("scripts.record_examples.scenarios", lambda today: [("example", ["Oi"])])
    assert record_main(["--output-dir", str(tmp_path)]) == 1
    error = capsys.readouterr().err
    assert "Failed example (FakeOpenAIError)" in error
    assert "private detail" not in error


def test_interactive_cli_handles_codex_errors_without_openai(monkeypatch, run, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setitem(sys.modules, "openai", None)
    answers = iter(["Oi", "sair"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    run.side_effect = FileNotFoundError("private detail")
    assert interactive_main() == 0
    output = capsys.readouterr().out
    assert "Falha ao consultar o Codex CLI" in output
    assert "private detail" not in output
