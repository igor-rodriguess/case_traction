"""CLI do baseline prompt-only do Understanding Agent.

Uso:

    python run_understanding_baseline.py

Executa o agente sobre o split DEV aprovado e grava os artefatos em
`experiments/understanding/baseline-v1/`.

Enquanto nenhum modelo/base estiver aprovado, o comando falha de forma
explícita com `BLOCKED_MODEL_SELECTION`, registra o bloqueio em
`run-manifest.json` e não consome nenhuma API externa. Ele nunca carrega train,
holdout ou Golden Set.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.agents.understanding.dataset import FORBIDDEN_RUNTIME_PATHS
from app.agents.understanding.prompts import PROMPT_VERSION
from app.agents.understanding.provider import (
    APPROVED_MODEL_BASE,
    MODEL_CANDIDATES,
    MODEL_SELECTION_STATUS,
    ModelSelectionBlocked,
    resolve_structured_provider,
)
from app.agents.understanding.runner import (
    BASELINE_ID,
    DEFAULT_SPLIT,
    default_output_dir,
    run_baseline,
    validate_output_dir,
    write_run,
)


def _blocked_manifest(reason: str) -> dict[str, object]:
    return {
        "baseline_id": BASELINE_ID,
        "prompt_version": PROMPT_VERSION,
        "status": MODEL_SELECTION_STATUS,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "approved_model_base": APPROVED_MODEL_BASE,
        "reason": reason,
        "split": DEFAULT_SPLIT,
        "executions": 0,
        "external_api_calls": 0,
        "splits_not_loaded": ["train", "holdout"],
        "golden_set_paths_not_loaded": list(FORBIDDEN_RUNTIME_PATHS),
        "predictions_written": False,
        "showcase_written": False,
        "showcase_note": (
            "showcase.json exige execução real do baseline. Nenhum showcase "
            "fictício é gerado."
        ),
        "model_candidates": [candidate.model_dump(mode="json") for candidate in MODEL_CANDIDATES],
        "unblock_procedure": [
            "Registrar a decisão humana de modelo/base em datasets/approvals/.",
            "Definir APPROVED_MODEL_BASE em app/agents/understanding/provider.py.",
            "Implementar o adaptador do provedor escolhido.",
            "Fornecer a credencial por variável de ambiente; nunca no repositório.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Diretório dos artefatos (padrão: experiments/understanding/baseline-v1).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Executa apenas as N primeiras amostras do DEV.",
    )
    args = parser.parse_args(argv)

    output_dir = args.output_dir or default_output_dir()
    validate_output_dir(output_dir)

    try:
        provider = resolve_structured_provider()
    except ModelSelectionBlocked as exc:
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = _blocked_manifest(str(exc))
        (output_dir / "run-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{MODEL_SELECTION_STATUS}: {exc}", file=sys.stderr)
        print("Opções documentadas:", file=sys.stderr)
        for candidate in MODEL_CANDIDATES:
            print(f"  - {candidate.provider}/{candidate.family}: {candidate.notes}", file=sys.stderr)
        print(f"Bloqueio registrado em {output_dir / 'run-manifest.json'}", file=sys.stderr)
        return 2

    run = run_baseline(provider, split=DEFAULT_SPLIT, limit=args.limit)
    paths = write_run(run, output_dir)
    print(json.dumps(run.metrics, ensure_ascii=False, indent=2))
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
