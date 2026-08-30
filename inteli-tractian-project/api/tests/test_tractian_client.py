"""Testes unitários do TractianClient, sem servidor externo e sem LLM."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable

import httpx
import pytest

from app.integrations.tractian_client import (
    ClientErrorKind,
    EvidenceStatus,
    OperationKind,
    RequestContext,
    TractianClient,
)


Handler = Callable[[httpx.Request], httpx.Response]


def client_for(handler: Handler, *, user_id: str | None = None) -> TractianClient:
    return TractianClient(
        RequestContext(user_id=user_id),
        base_url="https://tractian.test",
        transport=httpx.MockTransport(handler),
    )


def envelope(mode: str, data: object | None = None, notes: str | None = None) -> dict[str, object]:
    return {"mode": mode, "notes": notes, "data": data if data is not None else {"id": "resource"}}


def test_builds_read_request_with_path_and_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/assets/asset_M101/rms"
        assert dict(request.url.params) == {"point_id": "pt_M101_de", "seed": "complete"}
        assert "x-user-id" not in request.headers
        return httpx.Response(200, json=envelope("complete", {"samples": []}))

    with client_for(handler) as client:
        result = client.get_rms("asset_M101", point_id="pt_M101_de", seed="complete")

    assert result.transport_ok is True
    assert result.operation_kind is OperationKind.READ
    assert result.evidence_status is EvidenceStatus.COMPLETE


def test_injects_identity_from_request_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-user-id"] == "usr_lucas"
        return httpx.Response(200, json={"id": "usr_lucas", "role": "mechanic"})

    with client_for(handler, user_id="usr_lucas") as client:
        result = client.get_current_user()

    assert result.transport_ok is True
    assert result.data["id"] == "usr_lucas"


def test_endpoint_methods_do_not_accept_arbitrary_identity_or_headers() -> None:
    forbidden = {"user_id", "x_user_id", "headers"}

    for method_name in TractianClient.OPERATIONS:
        parameters = set(inspect.signature(getattr(TractianClient, method_name)).parameters)
        assert parameters.isdisjoint(forbidden), method_name


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("complete", EvidenceStatus.COMPLETE),
        ("partial", EvidenceStatus.PARTIAL),
        ("inconclusive", EvidenceStatus.INCONCLUSIVE),
        ("conflict", EvidenceStatus.CONFLICT),
        ("unavailable", EvidenceStatus.UNAVAILABLE),
    ],
)
def test_normalizes_evidence_statuses_returned_with_http_200(
    mode: str,
    expected: EvidenceStatus,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope(mode, {}, f"mode={mode}"))

    with client_for(handler) as client:
        result = client.get_asset("asset_G501")

    assert result.status_code == 200
    assert result.transport_ok is True
    assert result.evidence_status is expected
    assert result.notes == f"mode={mode}"
    assert result.error is None


def test_normalizes_non_2xx_response_and_preserves_error_payload() -> None:
    payload = {"code": "NOT_FOUND", "message": "Ativo não encontrado."}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json=payload)

    with client_for(handler) as client:
        result = client.get_asset("missing")

    assert result.transport_ok is False
    assert result.status_code == 404
    assert result.evidence_status is None
    assert result.data == payload
    assert result.error is not None
    assert result.error.kind is ClientErrorKind.HTTP_STATUS
    assert result.error.code == "NOT_FOUND"


def test_normalizes_timeout_without_http_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("tempo esgotado", request=request)

    with client_for(handler) as client:
        result = client.get_model("mdl_vib_v3")

    assert result.transport_ok is False
    assert result.status_code is None
    assert result.error is not None
    assert result.error.kind is ClientErrorKind.TIMEOUT


def test_normalizes_connection_error_separately_from_unavailable_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conexão recusada", request=request)

    with client_for(handler) as client:
        result = client.get_model("mdl_vib_v3")

    assert result.transport_ok is False
    assert result.evidence_status is None
    assert result.error is not None
    assert result.error.kind is ClientErrorKind.CONNECTION


def test_preserves_transport_success_when_json_is_invalid() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", headers={"content-type": "application/json"})

    with client_for(handler) as client:
        result = client.get_asset("asset_M101")

    assert result.transport_ok is True
    assert result.status_code == 200
    assert result.evidence_status is None
    assert result.error is not None
    assert result.error.kind is ClientErrorKind.INVALID_JSON


def test_rejects_unknown_evidence_status_without_inventing_a_new_state() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope("pending"))

    with client_for(handler) as client:
        result = client.get_asset("asset_M101")

    assert result.transport_ok is True
    assert result.evidence_status is None
    assert result.error is not None
    assert result.error.kind is ClientErrorKind.INVALID_RESPONSE


def test_action_uses_context_identity_and_preserves_acknowledgement_semantics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/analyses/an_9906/reprocess"
        assert request.headers["x-user-id"] == "usr_lucas"
        assert json.loads(request.content) == {
            "justification": "rolamento substituído; reprocessar análise atual",
            "params": {"source": "maintenance"},
        }
        return httpx.Response(
            200,
            json={"accepted": True, "action_id": "act_12345678", "message": "Reprocesso aceito."},
        )

    with client_for(handler, user_id="usr_lucas") as client:
        result = client.reprocess_analysis(
            "an_9906",
            justification="rolamento substituído; reprocessar análise atual",
            params={"source": "maintenance"},
        )

    assert result.transport_ok is True
    assert result.operation_kind is OperationKind.ACTION
    assert result.evidence_status is None
    assert result.data["accepted"] is True
    assert result.data["action_id"] == "act_12345678"


def test_registry_maps_all_runtime_operations_and_kinds() -> None:
    specs = TractianClient.OPERATIONS

    assert len(specs) == 18
    assert sum(spec.kind is OperationKind.READ for spec in specs.values()) == 13
    assert sum(spec.kind is OperationKind.ACTION for spec in specs.values()) == 5
    assert all(hasattr(TractianClient, operation) for operation in specs)
    assert specs["get_asset"].method == "GET"
    assert specs["update_asset_config"].method == "PATCH"
    assert specs["update_asset_config"].path_template == "/assets/{asset_id}"


def test_path_identifiers_are_encoded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/knowledge/id/with/slash"
        assert request.url.raw_path == b"/knowledge/id%2Fwith%2Fslash"
        return httpx.Response(200, json=envelope("complete"))

    with client_for(handler) as client:
        result = client.get_knowledge_document("id/with/slash")

    assert result.transport_ok is True


def test_request_context_rejects_blank_identity() -> None:
    with pytest.raises(ValueError, match="user_id"):
        RequestContext(user_id="   ")
