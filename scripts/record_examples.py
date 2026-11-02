"""Record five real provider conversations, including every tool call and result."""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent import Agent
from src.tools import get_today


def scenarios(today: date) -> list[tuple[str, list[str]]]:
    received = (today - timedelta(days=5)).isoformat()
    purchased = (today - timedelta(days=45)).isoformat()
    defect_received = (today - timedelta(days=40)).isoformat()
    return [
        ("01_product_price_stock", [
            "Quanto custa o Takamine GD20 e tem em estoque?",
            "Quais as características dele?",
            "Tem algum violão disponível até R$ 1.000?",
        ]),
        ("02_promotion_pix", [
            "O Ohana CK-20 está em promoção? Qual o preço original, desconto e preço atual?",
            "Se eu pagar por PIX, ganho mais 5% sobre essa promoção?",
            "E no Yamaha C40, sem promoção, como funciona o PIX? Consulte o preço dele.",
        ]),
        ("03_order_identity", [
            "Quero consultar o status do meu pedido.",
            "O número do pedido é 8.",
            "Meu e-mail é wrong@example.com. Consulte o pedido 8 com esse e-mail.",
            "Digitei errado: anacarol.ferreira@coldmail.com. Pode consultar novamente o pedido 8?",
            "Qual o rastreio? Essa data de entrega é uma previsão ou confirmação de recebimento?",
        ]),
        ("04_returns_warranty_dates", [
            "Me arrependi de uma compra online. Posso devolver? Que informação precisa?",
            f"Recebi em {received}, está sem uso e na embalagem original. "
            "Consulte a data de hoje e calcule quantos dias passaram. Ainda estou no prazo? Quem paga o frete?",
            f"Outro instrumento apresentou defeito: comprei em {purchased} e recebi em {defect_received}. "
            "Qual prazo vale para troca na loja e para garantia legal? Calcule os dias.",
            "E quanto dura a garantia do fabricante? Não tenho o certificado em mãos.",
        ]),
        ("05_scope_complaint", [
            "Qual é a capital da França?",
            "Vocês vendem cordas e cabos?",
            "Estou muito insatisfeito com o atendimento e quero reclamar com um responsável.",
            "Você já encaminhou minha reclamação? Qual o canal e o prazo para falar com uma pessoa?",
        ]),
    ]


def fenced(text: str, language: str = "text") -> str:
    # Tool outputs and model replies can themselves contain Markdown fences.
    length = max([3] + [len(m.group()) + 1 for m in re.finditer(r"`+", text)])
    fence = "`" * length
    return f"{fence}{language}\n{text}\n{fence}"


def render_transcript(name: str, model: str, messages: list[dict], started: str,
                      status: str = "complete") -> str:
    lines = [f"# {name}", "", f"Model: `{model}`", f"Started (UTC): {started}",
             f"Status: {status}", "", "Source: real LLM API responses; local tools use the supplied case data.", ""]
    for message in messages:
        role = message["role"]
        if role == "system":
            continue
        if role == "tool":
            lines.extend([f"### Tool result — {message['tool_call_id']}", "",
                          fenced(message["content"]), ""])
            continue
        lines.extend([f"## {'Customer' if role == 'user' else 'Toninho'}", ""])
        if message.get("content"):
            lines.extend([fenced(message["content"]), ""])
        for call in message.get("tool_calls", []):
            lines.extend([f"### Tool call — {call['function']['name']} ({call['id']})", "",
                          fenced(json.dumps(call, ensure_ascii=False, indent=2), "json"), ""])
    return "\n".join(lines)


def record_scenario(agent: Agent, name: str, turns: list[str], output: Path) -> Path:
    started = datetime.now(timezone.utc).isoformat()
    partial = output / f"{name}.partial.md"
    final = output / f"{name}.md"
    for turn in turns:
        try:
            agent.chat(turn)
        except Exception as exc:
            # chat() rolls back failed turns. Preserve the attempted input and a safe error type.
            messages = agent.messages + [{"role": "user", "content": turn}]
            partial.write_text(render_transcript(name, agent.model, messages, started,
                                                f"failed ({type(exc).__name__})"), encoding="utf-8")
            raise
        partial.write_text(render_transcript(name, agent.model, agent.messages, started,
                                            "in progress"), encoding="utf-8")
    partial.write_text(render_transcript(name, agent.model, agent.messages, started), encoding="utf-8")
    partial.replace(final)
    return final


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "examples")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing completed transcripts")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    cases = scenarios(date.fromisoformat(get_today()))
    if not args.overwrite and any((args.output_dir / f"{name}.md").exists() for name, _ in cases):
        parser.error("Completed transcripts already exist; use --overwrite or another --output-dir.")
    try:
        # Fail before creating files when configuration is missing.
        first_agent = Agent()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    from openai import OpenAIError

    args.output_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    for index, (name, turns) in enumerate(cases):
        try:
            agent = first_agent if index == 0 else Agent()
            path = record_scenario(agent, name, turns, args.output_dir)
            print(f"Saved {path}")
        except (OpenAIError, ValueError, OSError) as exc:
            failed += 1
            print(f"Failed {name} ({type(exc).__name__}); inspect any .partial.md file.", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
