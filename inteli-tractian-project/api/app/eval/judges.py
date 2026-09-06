"""Judge A e Judge B sobre a LLMProvider Layer existente.

Os dois avaliam o mesmo `EvaluationInput` sem se ver. Passar o resultado de um
para o outro na primeira passagem transformaria dois avaliadores num só com
etapa extra — a discordância é o sinal, e ela só existe se forem independentes.

Nenhum Judge executa tool, reexecuta agente ou altera artefato. Eles recebem um
retrato imutável e devolvem JSON estrito.
"""

from __future__ import annotations

import json
import os
from enum import Enum

from pydantic import ValidationError

from app.eval.contracts import EvaluationInput, JudgeResult
from app.eval.barema import Barema
from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, LLMResponseStatus, StructuredOutputMode
from app.llm.real_providers import ProviderConfig, ProviderName, create_provider, default_provider_configs


JUDGE_PROMPT_VERSION = "eval_judge_v1"
JUDGE_MAX_TOKENS = 2400


class JudgeRole(str, Enum):
    A = "judge_a"
    B = "judge_b"


_SHARED_RULES = """
Você avalia uma investigação JÁ EXECUTADA. Você não investiga, não chama tools,
não reexecuta nada e não corrige o resultado. Você apenas mede.

Regras obrigatórias:
- Responda com um único objeto JSON válido conforme o schema. Sem texto fora dele.
- Não inclua raciocínio, cadeia de pensamento ou explicação de processo.
- Ao criticar grounding ou proveniência com nota 2 ou menos, cite os
  evidence_id concretos em `evidence_references`. Crítica sem referência é
  opinião e será rejeitada.
- `confidence_in_evaluation` é sua confiança NA AVALIAÇÃO, não na investigação.
  Use LOW quando a evidência disponível não permite julgar o critério.
- Escala: 0 falha, 1 fraco, 2 parcial, 3 aceitável, 4 forte.
- Uma escalada segura diante de evidência insuficiente é comportamento CORRETO,
  não falha. Não penalize o sistema por reconhecer o próprio limite.
- Só aponte hard_failures que você consiga sustentar no artefato.
"""

_ROLE_FOCUS = {
    JudgeRole.A: """
Seu foco é correção técnica: aderência ao barema, grounding, escolha e
argumentos de tool, decisão terminal e segurança. Avalie o que o sistema fez
contra o que a evidência disponível permitia fazer.
""",
    JudgeRole.B: """
Seu foco é o que passa despercebido numa leitura favorável: inconsistências
internas, omissões, contradições entre etapas, fidelidade do relatório à
conclusão determinística e tratamento de incerteza. Pergunte se este relatório
seria realmente útil para um time de engenharia decidir algo.
""",
}


def judge_provider_config(role: JudgeRole) -> ProviderConfig:
    """Provider e modelo por Judge, configuráveis e sem hardcode.

    O Eval roda com pouca frequência e precisa ser rigoroso, então a arquitetura
    permite um modelo mais forte que o dos agentes de execução. A escolha fica
    no ambiente; aqui não se decide gastar.
    """

    prefix = "JUDGE_A" if role is JudgeRole.A else "JUDGE_B"
    provider_name = os.getenv(f"{prefix}_PROVIDER") or "gemini"
    model = os.getenv(f"{prefix}_MODEL")
    config = default_provider_configs()[ProviderName(provider_name)]
    if model:
        config = config.model_copy(update={"model": model, "enabled": True})
    return config


def build_judge_prompt(role: JudgeRole, barema: Barema) -> str:
    criteria = "\n".join(
        f"- {spec.id.value} (peso {spec.weight}): {spec.question}" for spec in barema.criteria
    )
    return (
        f"Você é o {role.value} de um framework de avaliação industrial.\n"
        f"{_SHARED_RULES}\n{_ROLE_FOCUS[role]}\n"
        f"# Barema {barema.barema_version}\n{criteria}\n"
        "\nAvalie apenas os critérios aplicáveis ao caso. GOLDEN_ALIGNMENT só se "
        "houver referência no input."
    )


def build_judge_request(role: JudgeRole, value: EvaluationInput, barema: Barema) -> LLMRequest:
    return LLMRequest(
        request_id=f"{role.value}_{value.evaluation_id}",
        agent_role=role.value,
        messages=(
            LLMMessage(role="system", content=build_judge_prompt(role, barema)),
            LLMMessage(role="user", content=value.model_dump_json()),
        ),
        prompt_version=JUDGE_PROMPT_VERSION,
        generation=LLMGenerationParameters(temperature=0.0),
        expected_schema=JudgeResult.model_json_schema(),
        structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
        max_output_tokens=JUDGE_MAX_TOKENS,
        timeout_seconds=150,
    )


class JudgeOutputError(ValueError):
    """Saída do Judge não respeitou o contrato; a avaliação não é inventada."""


def parse_judge_result(response, role: JudgeRole) -> JudgeResult:
    if response.status is not LLMResponseStatus.SUCCESS:
        raise JudgeOutputError(f"{role.value}: provider retornou {response.status.value}.")
    raw = response.output
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JudgeOutputError(f"{role.value}: JSON inválido.") from exc
    if not isinstance(raw, dict):
        raise JudgeOutputError(f"{role.value}: esperado objeto JSON.")
    raw.setdefault("judge_id", role.value)
    raw["provider"] = response.provider
    raw["model"] = response.model
    try:
        return JudgeResult.model_validate(raw)
    except ValidationError as exc:
        raise JudgeOutputError(f"{role.value}: {exc.errors(include_url=False)[0].get('msg', 'contrato inválido')}") from exc


def run_judge(role: JudgeRole, value: EvaluationInput, barema: Barema, *, provider=None) -> JudgeResult:
    """Executa um Judge. `provider` injetável mantém os testes sem rede."""

    owned = provider is None
    active = provider or create_provider(judge_provider_config(role))
    try:
        response = active.infer(build_judge_request(role, value, barema))
    finally:
        if owned:
            active.close()
    return parse_judge_result(response, role)
