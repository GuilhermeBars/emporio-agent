"""Interactive CLI: python -m src.main (or python src/main.py)."""
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import Agent
from src.codex_provider import CodexClient, CodexError


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        agent = Agent()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    api_errors = ()
    if not isinstance(agent.client, CodexClient):
        from openai import OpenAIError

        api_errors = (OpenAIError,)

    print("Empório da Música - digite 'sair' para encerrar.\n")
    try:
        while True:
            message = input("Você: ").strip()
            if message.lower() in {"sair", "exit", "quit"}:
                return 0
            if not message:
                continue
            try:
                print(f"Toninho: {agent.chat(message)}\n")
            except CodexError:
                print("Falha ao consultar o Codex CLI. Confira a instalação, a autenticação e a conexão.")
            except api_errors:
                print("Falha ao consultar o provedor. Confira a chave, o modelo e a conexão.")
    except (EOFError, KeyboardInterrupt):
        print("\nAté mais!")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
