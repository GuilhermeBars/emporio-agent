"""Provider configuration shared by the CLI and transcript recorder."""
from dataclasses import dataclass, field
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path, *, override: bool = False):
    # Deterministic tests with an injected client need no provider dependencies.
    if path.is_file():
        from dotenv import load_dotenv as load

        load(path, override=override)


@dataclass(frozen=True)
class ProviderConfig:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    provider: str = "openai"

    @classmethod
    def from_env(cls):
        # Shell variables always take precedence over the optional local file.
        load_dotenv(ROOT / ".env", override=False)
        if os.getenv("LLM_PROVIDER", "").strip().lower() == "codex":
            codex_model = os.getenv("CODEX_MODEL", "").strip()
            label = f"codex-cli:{codex_model}" if codex_model else "codex-cli"
            return cls("", "", label, provider="codex")
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        use_groq = not openai_key and bool(groq_key)
        key = openai_key or groq_key
        if not key:
            raise ValueError("Set OPENAI_API_KEY or GROQ_API_KEY in the environment or .env.")
        base = os.getenv("OPENAI_BASE_URL", "").strip() or (
            "https://api.groq.com/openai/v1" if use_groq else "https://api.openai.com/v1"
        )
        model = os.getenv("MODEL", "").strip() or (
            "llama-3.3-70b-versatile" if use_groq else "gpt-4o-mini"
        )
        return cls(key, base, model, provider="groq" if use_groq else "openai")
