"""Understanding Agent — baseline prompt-only da Etapa 05.

Responsabilidade única: transformar uma solicitação do cliente em uma
representação estruturada do problema. Não investiga, não diagnostica, não
chama tools e não executa ações.
"""

from app.agents.understanding.agent import (
    UnderstandingAgent,
    UnderstandingInvocation,
    understand_request,
)
from app.agents.understanding.prompts import PROMPT_VERSION
from app.agents.understanding.schemas import UnderstandingInput, UnderstandingOutput

__all__ = [
    "PROMPT_VERSION",
    "UnderstandingAgent",
    "UnderstandingInput",
    "UnderstandingInvocation",
    "UnderstandingOutput",
    "understand_request",
]
