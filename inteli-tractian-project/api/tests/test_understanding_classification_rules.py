"""Regra de precedência de `request_class` introduzida na Etapa 09.6.

Os testes verificam a *regra*, não respostas memorizadas: nenhum caso do DEV é
reproduzido aqui, conforme §12.
"""

from app.agents.understanding.prompts import (
    PROMPT_VERSION,
    PROMPT_VERSION_V2,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_V2,
)
from app.agents.understanding.schemas import RequestClass


def test_v1_prompt_is_preserved_untouched() -> None:
    """A Etapa 09.5 precisa continuar reproduzível a partir do mesmo prompt."""

    assert PROMPT_VERSION == "understanding_prompt_v1"
    assert "Regra de precedência" not in SYSTEM_PROMPT


def test_v2_is_v1_plus_the_precedence_rule_only() -> None:
    assert PROMPT_VERSION_V2 == "understanding_prompt_v2"
    assert len(SYSTEM_PROMPT_V2) > len(SYSTEM_PROMPT)
    # Tudo que existia em V1 continua em V2: a única diferença é o bloco novo.
    for chunk in SYSTEM_PROMPT.split("\n\n"):
        if chunk.strip():
            assert chunk in SYSTEM_PROMPT_V2


def _flat(text: str) -> str:
    """O prompt é quebrado em linhas; comparar frases exige normalizar espaço."""

    return " ".join(text.split())


def test_v2_states_that_action_precedes_mixed() -> None:
    flat = _flat(SYSTEM_PROMPT_V2)

    assert "Regra de precedência" in SYSTEM_PROMPT_V2
    assert "PRÉ-CONDIÇÃO" in flat
    assert "não torne o caso `mixed` por causa dela" in flat


def test_v2_separates_recognising_an_action_from_classifying_as_execute() -> None:
    """`requested_actions` precisa continuar preenchido fora de `execute`."""

    assert "`requested_actions` é INDEPENDENTE de `request_class`" in _flat(SYSTEM_PROMPT_V2)
    assert "pedido de recomendação, não de execução" in _flat(SYSTEM_PROMPT_V2)


def test_v2_does_not_weaken_the_action_execution_guarantee() -> None:
    assert "`action_execution_allowed` permanece `false`" in _flat(SYSTEM_PROMPT_V2)
    assert "`execute` NÃO significa que você pode executar" in _flat(SYSTEM_PROMPT_V2)
    assert "SEMPRE `false`" in SYSTEM_PROMPT_V2


def test_v2_covers_every_declared_class() -> None:
    for item in RequestClass:
        assert f"`{item.value}`" in SYSTEM_PROMPT_V2


def test_v2_contains_no_dev_sample_text() -> None:
    """Guard contra vazar exemplos do split para dentro do prompt."""

    from app.agents.understanding.dataset import load_dev_split

    for sample in load_dev_split():
        assert sample.input.message not in SYSTEM_PROMPT_V2
        assert sample.sample_id not in SYSTEM_PROMPT_V2
