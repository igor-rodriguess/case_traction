"""Cliente HTTP tipado para a API industrial TRACTIAN do projeto.

Esta camada conhece o contrato de transporte. Ela não contém decisões de agente,
política de autorização adicional ou interpretação diagnóstica das evidências.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Mapping
from urllib.parse import quote

import httpx


class EvidenceStatus(str, Enum):
    """Estados semânticos comprovadamente retornados pelos READs envelopados."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    INCONCLUSIVE = "inconclusive"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


class OperationKind(str, Enum):
    """Natureza da operação, independente do método HTTP."""

    READ = "READ"
    ACTION = "ACTION"


class ClientErrorKind(str, Enum):
    """Falhas de transporte ou de protocolo normalizadas pelo client."""

    TIMEOUT = "timeout"
    CONNECTION = "connection"
    HTTP_STATUS = "http_status"
    INVALID_JSON = "invalid_json"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Contexto confiável fornecido pela aplicação, nunca por um futuro LLM."""

    user_id: str | None = None

    def __post_init__(self) -> None:
        if self.user_id is not None and not self.user_id.strip():
            raise ValueError("user_id não pode ser vazio.")


@dataclass(frozen=True, slots=True)
class ClientError:
    kind: ClientErrorKind
    message: str
    code: str | None = None


@dataclass(frozen=True, slots=True)
class ClientResult:
    """Resultado que não confunde sucesso HTTP com qualidade da evidência."""

    operation: str
    operation_kind: OperationKind
    method: str
    path: str
    transport_ok: bool
    status_code: int | None
    evidence_status: EvidenceStatus | None
    data: Any = None
    notes: str | None = None
    error: ClientError | None = None


@dataclass(frozen=True, slots=True)
class OperationSpec:
    method: str
    path_template: str
    kind: OperationKind
    evidence_envelope: bool


def _spec(
    method: str,
    path_template: str,
    kind: OperationKind,
    *,
    evidence_envelope: bool = False,
) -> OperationSpec:
    return OperationSpec(method, path_template, kind, evidence_envelope)


class TractianClient:
    """Ponto único de comunicação HTTP com a API TRACTIAN.

    O client é síncrono porque a API e os testes existentes também são síncronos.
    Um ``httpx.MockTransport`` pode ser injetado para testes sem servidor externo.
    """

    DEFAULT_BASE_URL: ClassVar[str] = "http://127.0.0.1:8000"
    DEFAULT_TIMEOUT_SECONDS: ClassVar[float] = 10.0

    OPERATIONS: ClassVar[Mapping[str, OperationSpec]] = MappingProxyType(
        {
            "get_company": _spec("GET", "/companies/{company_id}", OperationKind.READ, evidence_envelope=True),
            "list_company_assets": _spec(
                "GET", "/companies/{company_id}/assets", OperationKind.READ, evidence_envelope=True
            ),
            "get_current_user": _spec("GET", "/users/me", OperationKind.READ),
            "get_asset": _spec("GET", "/assets/{asset_id}", OperationKind.READ, evidence_envelope=True),
            "update_asset_config": _spec("PATCH", "/assets/{asset_id}", OperationKind.ACTION),
            "list_asset_analyses": _spec(
                "GET", "/assets/{asset_id}/analyses", OperationKind.READ, evidence_envelope=True
            ),
            "get_analysis": _spec(
                "GET", "/analyses/{analysis_id}", OperationKind.READ, evidence_envelope=True
            ),
            "reprocess_analysis": _spec(
                "POST", "/analyses/{analysis_id}/reprocess", OperationKind.ACTION
            ),
            "request_specialist_analysis": _spec(
                "POST", "/analyses/{analysis_id}/request-specialist", OperationKind.ACTION
            ),
            "get_baseline": _spec(
                "GET", "/assets/{asset_id}/baseline", OperationKind.READ, evidence_envelope=True
            ),
            "get_rms": _spec("GET", "/assets/{asset_id}/rms", OperationKind.READ, evidence_envelope=True),
            "get_spectrum": _spec(
                "GET", "/assets/{asset_id}/spectrum", OperationKind.READ, evidence_envelope=True
            ),
            "get_data_quality": _spec(
                "GET", "/assets/{asset_id}/data-quality", OperationKind.READ, evidence_envelope=True
            ),
            "get_model": _spec("GET", "/models/{model_id}", OperationKind.READ, evidence_envelope=True),
            "request_model_retraining": _spec(
                "POST", "/models/{model_id}/request-retraining", OperationKind.ACTION
            ),
            "search_knowledge": _spec("GET", "/knowledge/search", OperationKind.READ, evidence_envelope=True),
            "get_knowledge_document": _spec(
                "GET", "/knowledge/{doc_id}", OperationKind.READ, evidence_envelope=True
            ),
            "escalate_case": _spec("POST", "/cases/{case_id}/escalate", OperationKind.ACTION),
        }
    )

    def __init__(
        self,
        context: RequestContext,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._context = context
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> TractianClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_company(self, company_id: str, *, seed: str | None = None) -> ClientResult:
        return self._call("get_company", path_values={"company_id": company_id}, query={"seed": seed})

    def list_company_assets(self, company_id: str, *, seed: str | None = None) -> ClientResult:
        return self._call(
            "list_company_assets", path_values={"company_id": company_id}, query={"seed": seed}
        )

    def get_current_user(self) -> ClientResult:
        return self._call("get_current_user")

    def get_asset(self, asset_id: str, *, seed: str | None = None) -> ClientResult:
        return self._call("get_asset", path_values={"asset_id": asset_id}, query={"seed": seed})

    def update_asset_config(
        self,
        asset_id: str,
        *,
        justification: str,
        changes: Mapping[str, Any],
    ) -> ClientResult:
        return self._call(
            "update_asset_config",
            path_values={"asset_id": asset_id},
            body={"justification": justification, "changes": dict(changes)},
        )

    def list_asset_analyses(
        self,
        asset_id: str,
        *,
        status: str | None = None,
        seed: str | None = None,
    ) -> ClientResult:
        return self._call(
            "list_asset_analyses",
            path_values={"asset_id": asset_id},
            query={"status": status, "seed": seed},
        )

    def get_analysis(self, analysis_id: str, *, seed: str | None = None) -> ClientResult:
        return self._call(
            "get_analysis", path_values={"analysis_id": analysis_id}, query={"seed": seed}
        )

    def reprocess_analysis(
        self,
        analysis_id: str,
        *,
        justification: str,
        params: Mapping[str, Any] | None = None,
    ) -> ClientResult:
        return self._call(
            "reprocess_analysis",
            path_values={"analysis_id": analysis_id},
            body=self._action_body(justification, params),
        )

    def request_specialist_analysis(
        self,
        analysis_id: str,
        *,
        justification: str,
        params: Mapping[str, Any] | None = None,
    ) -> ClientResult:
        return self._call(
            "request_specialist_analysis",
            path_values={"analysis_id": analysis_id},
            body=self._action_body(justification, params),
        )

    def get_baseline(
        self,
        asset_id: str,
        *,
        point_id: str | None = None,
        seed: str | None = None,
    ) -> ClientResult:
        return self._call(
            "get_baseline",
            path_values={"asset_id": asset_id},
            query={"point_id": point_id, "seed": seed},
        )

    def get_rms(
        self,
        asset_id: str,
        *,
        point_id: str | None = None,
        seed: str | None = None,
    ) -> ClientResult:
        return self._call(
            "get_rms",
            path_values={"asset_id": asset_id},
            query={"point_id": point_id, "seed": seed},
        )

    def get_spectrum(
        self,
        asset_id: str,
        *,
        point_id: str | None = None,
        seed: str | None = None,
    ) -> ClientResult:
        return self._call(
            "get_spectrum",
            path_values={"asset_id": asset_id},
            query={"point_id": point_id, "seed": seed},
        )

    def get_data_quality(
        self,
        asset_id: str,
        *,
        point_id: str | None = None,
        seed: str | None = None,
    ) -> ClientResult:
        return self._call(
            "get_data_quality",
            path_values={"asset_id": asset_id},
            query={"point_id": point_id, "seed": seed},
        )

    def get_model(self, model_id: str, *, seed: str | None = None) -> ClientResult:
        return self._call("get_model", path_values={"model_id": model_id}, query={"seed": seed})

    def request_model_retraining(
        self,
        model_id: str,
        *,
        justification: str,
        params: Mapping[str, Any] | None = None,
    ) -> ClientResult:
        return self._call(
            "request_model_retraining",
            path_values={"model_id": model_id},
            body=self._action_body(justification, params),
        )

    def search_knowledge(
        self,
        query: str,
        *,
        knowledge_type: str | None = None,
        seed: str | None = None,
    ) -> ClientResult:
        return self._call(
            "search_knowledge",
            query={"q": query, "type": knowledge_type, "seed": seed},
        )

    def get_knowledge_document(self, doc_id: str, *, seed: str | None = None) -> ClientResult:
        return self._call(
            "get_knowledge_document", path_values={"doc_id": doc_id}, query={"seed": seed}
        )

    def escalate_case(
        self,
        case_id: str,
        *,
        justification: str,
        params: Mapping[str, Any] | None = None,
    ) -> ClientResult:
        return self._call(
            "escalate_case",
            path_values={"case_id": case_id},
            body=self._action_body(justification, params),
        )

    @staticmethod
    def _action_body(
        justification: str,
        params: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"justification": justification}
        if params is not None:
            body["params"] = dict(params)
        return body

    def _call(
        self,
        operation: str,
        *,
        path_values: Mapping[str, str] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> ClientResult:
        spec = self.OPERATIONS[operation]
        encoded_values = {key: quote(str(value), safe="") for key, value in (path_values or {}).items()}
        path = spec.path_template.format(**encoded_values)
        params = {key: value for key, value in (query or {}).items() if value is not None}
        headers = {"x-user-id": self._context.user_id} if self._context.user_id is not None else None

        try:
            response = self._http.request(
                spec.method,
                path,
                params=params or None,
                json=dict(body) if body is not None else None,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            return self._transport_failure(operation, spec, path, ClientErrorKind.TIMEOUT, str(exc))
        except httpx.RequestError as exc:
            return self._transport_failure(operation, spec, path, ClientErrorKind.CONNECTION, str(exc))

        transport_ok = response.is_success
        try:
            payload = response.json()
        except ValueError as exc:
            return ClientResult(
                operation=operation,
                operation_kind=spec.kind,
                method=spec.method,
                path=path,
                transport_ok=transport_ok,
                status_code=response.status_code,
                evidence_status=None,
                error=ClientError(ClientErrorKind.INVALID_JSON, str(exc)),
            )

        if not transport_ok:
            code = payload.get("code") if isinstance(payload, dict) else None
            message = payload.get("message") if isinstance(payload, dict) else None
            return ClientResult(
                operation=operation,
                operation_kind=spec.kind,
                method=spec.method,
                path=path,
                transport_ok=False,
                status_code=response.status_code,
                evidence_status=None,
                data=payload,
                error=ClientError(
                    ClientErrorKind.HTTP_STATUS,
                    str(message or response.reason_phrase),
                    str(code) if code is not None else None,
                ),
            )

        if spec.evidence_envelope:
            try:
                evidence_status = EvidenceStatus(payload.get("mode")) if isinstance(payload, dict) else None
            except ValueError:
                evidence_status = None
            if evidence_status is None:
                return ClientResult(
                    operation=operation,
                    operation_kind=spec.kind,
                    method=spec.method,
                    path=path,
                    transport_ok=True,
                    status_code=response.status_code,
                    evidence_status=None,
                    data=payload,
                    error=ClientError(
                        ClientErrorKind.INVALID_RESPONSE,
                        "Resposta READ sem um evidence status reconhecido.",
                    ),
                )
            return ClientResult(
                operation=operation,
                operation_kind=spec.kind,
                method=spec.method,
                path=path,
                transport_ok=True,
                status_code=response.status_code,
                evidence_status=evidence_status,
                data=payload.get("data"),
                notes=payload.get("notes"),
            )

        return ClientResult(
            operation=operation,
            operation_kind=spec.kind,
            method=spec.method,
            path=path,
            transport_ok=True,
            status_code=response.status_code,
            evidence_status=None,
            data=payload,
        )

    @staticmethod
    def _transport_failure(
        operation: str,
        spec: OperationSpec,
        path: str,
        kind: ClientErrorKind,
        message: str,
    ) -> ClientResult:
        return ClientResult(
            operation=operation,
            operation_kind=spec.kind,
            method=spec.method,
            path=path,
            transport_ok=False,
            status_code=None,
            evidence_status=None,
            error=ClientError(kind, message),
        )
