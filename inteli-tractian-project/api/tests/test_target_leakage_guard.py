"""Guard contra vazamento do target DEV para o runtime (Etapa 09.7, §9).

O `target` de cada amostra é rótulo de avaliação. Ele pode ser lido **depois** da
inferência, para calcular métricas, e nunca antes — nem em prompt, nem em
InvestigationState, PlannerInput, InvestigatorInput ou ReporterInput.

A garantia é estrutural e verificada por inspeção do próprio código, não por
disciplina de quem escreve o runner.
"""

import inspect
import json

import pytest

from app.agents.understanding.dataset import UnderstandingSample, load_dev_split
from app.agents.understanding.schemas import UnderstandingInput
from app.evaluation.dataset_validation import runtime_payload
from app.intelligence import InvestigatorInput, PlannerInput, ReporterInput
from app.investigation import InvestigationState

import scripts.run_full_dev_evaluation as runner


_RUNTIME_CONTRACTS = (InvestigationState, PlannerInput, InvestigatorInput, ReporterInput)


def test_no_runtime_contract_declares_a_target_field() -> None:
    for contract in _RUNTIME_CONTRACTS:
        assert "target" not in contract.model_fields
        assert "expected" not in contract.model_fields
        assert "label" not in contract.model_fields


def test_runtime_contracts_cannot_absorb_a_whole_sample() -> None:
    """`extra="forbid"` impede que a amostra inteira entre por engano."""

    sample = load_dev_split()[0]
    for contract in _RUNTIME_CONTRACTS:
        with pytest.raises(Exception):
            contract.model_validate(sample.model_dump(mode="python"))


def test_runtime_payload_is_the_only_projection_of_a_sample() -> None:
    sample = load_dev_split()[0]
    payload = runtime_payload(sample)

    assert isinstance(payload, UnderstandingInput)
    assert set(json.loads(payload.model_dump_json())) == set(UnderstandingInput.model_fields)
    assert "target" not in json.loads(payload.model_dump_json())


def test_run_case_touches_the_sample_only_through_allowed_attributes() -> None:
    """`run_case` recebe a amostra inteira; o teste prova que só usa o permitido."""

    source = inspect.getsource(runner.run_case)
    allowed = {"sample.sample_id", "sample.training_tags"}
    used = {
        f"sample.{name}"
        for name in UnderstandingSample.model_fields
        if f"sample.{name}" in source
    }
    assert used <= allowed, f"run_case acessa atributo não permitido da amostra: {used - allowed}"
    assert "runtime_payload(sample)" in source


def test_target_is_read_only_in_the_scoring_layer() -> None:
    """A pontuação offline pode ler o target; ela roda depois de todos os casos."""

    scoring = inspect.getsource(runner.understanding_metrics)
    assert "sample.target" in scoring

    # E o escore nunca é chamado de dentro da execução de um caso.
    assert "understanding_metrics" not in inspect.getsource(runner.run_case)
