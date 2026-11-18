"""Tests del argumento workflow F1 y del cliente (mocks)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auditor.modelos import LoteDescarga, construir_argumento_workflow
from auditor.periodo import parse_periodo, periodo_default, periodo_texto
from auditor.workflows_cliente import WorkflowsCliente
from datetime import date


def test_construir_argumento_workflow_contrato_f1():
    arg = construir_argumento_workflow(
        ruts=["27168649-8", "22564605-8"],
        periodos="2026-10",
        empresa="Security",
        fuente="lista",
        forzar="1",
        dry_run="0",
        solicitud_id="finiquitados-oct-2026",
        incluir_industry=False,
        sync="no",
    )
    assert arg["incluir_industry"] == "false"
    assert arg["sync"] == "no"
    obj = arg["objetivo"]
    assert obj["ruts"] == "27168649-8,22564605-8"
    assert obj["periodos"] == "2026-10"
    assert obj["fuente"] == "lista"
    assert obj["empresa"] == "Security"
    assert obj["forzar"] == "1"
    assert obj["solicitud_id"] == "finiquitados-oct-2026"
    # Debe ser JSON-serializable (lo que recibe Workflows API)
    json.dumps(arg)


def test_lote_argument_objetivo():
    lote = LoteDescarga(
        tipo_auditor="cotizaciones",
        workflow="documentos-cotizaciones",
        empresa="Security",
        ruts=["18064222-6"],
        periodo="2026-10",
        solicitud_id="auditor-cotiz",
    )
    arg = lote.argument_objetivo(incluir_industry=True, sync="fin")
    # El lote expone el flag; el cliente fuerza false en cotizaciones al lanzar
    assert arg["incluir_industry"] == "true"
    assert arg["objetivo"]["fuente"] == "lista"


def test_cliente_fuerza_industry_false_en_cotizaciones():
    session = mock.MagicMock()
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.raise_for_status = mock.MagicMock()
    resp.json.return_value = {
        "name": "projects/p/locations/us-east1/workflows/documentos-cotizaciones/executions/e1",
        "state": "ACTIVE",
    }
    session.post.return_value = resp
    session.get.return_value = mock.MagicMock(
        status_code=200,
        json=mock.MagicMock(return_value={"executions": []}),
        raise_for_status=mock.MagicMock(),
    )

    client = WorkflowsCliente(
        project="worldwide-470917",
        region="us-east1",
        session=session,
        sleep_fn=lambda _s: None,
    )
    lote = LoteDescarga(
        tipo_auditor="cotizaciones",
        workflow="documentos-cotizaciones",
        empresa="Security",
        ruts=["27168649-8"],
        periodo="2026-10",
        solicitud_id="sol-cot",
    )
    outs = client.lanzar_lotes_en_serie(
        [lote],
        incluir_industry=True,  # se ignora para cotizaciones
        esperar=False,
        abortar_si_ocupado=False,
    )
    assert len(outs) == 1
    # Revisar body enviado
    body = session.post.call_args.kwargs.get("json") or session.post.call_args[1].get("json")
    if body is None:
        body = session.post.call_args[1]["json"] if session.post.call_args[1] else session.post.call_args[0]
    # call_args: post(url, json=body)
    _, kwargs = session.post.call_args
    payload = json.loads(kwargs["json"]["argument"])
    assert payload["incluir_industry"] == "false"
    assert payload["sync"] == "no"
    assert payload["objetivo"]["fuente"] == "lista"


def test_cliente_no_cancela_y_serializa_lotes():
    session = mock.MagicMock()

    def _get(url, **kw):
        r = mock.MagicMock()
        r.status_code = 200
        r.raise_for_status = mock.MagicMock()
        if "executions" in url and "filter" in str(kw.get("params", {})):
            r.json.return_value = {"executions": []}
        else:
            r.json.return_value = {"state": "SUCCEEDED", "executions": []}
        return r

    posts = []

    def _post(url, **kw):
        posts.append(url)
        r = mock.MagicMock()
        r.status_code = 200
        r.raise_for_status = mock.MagicMock()
        r.json.return_value = {
            "name": f"{url.rstrip('/')}/executions/x{len(posts)}",
            "state": "ACTIVE",
        }
        return r

    session.get.side_effect = _get
    session.post.side_effect = _post
    client = WorkflowsCliente(
        project="worldwide-470917",
        region="us-east1",
        session=session,
        sleep_fn=lambda _s: None,
    )
    lotes = [
        LoteDescarga(
            tipo_auditor="liquidacion",
            workflow="documentos-liquidaciones",
            empresa="Security",
            ruts=["1-9"],
            periodo="2026-10",
            solicitud_id="s-liq",
        ),
        LoteDescarga(
            tipo_auditor="asistencia",
            workflow="documentos-asistencias",
            empresa="Security",
            ruts=["1-9"],
            periodo="2026-10",
            solicitud_id="s-as",
        ),
    ]
    outs = client.lanzar_lotes_en_serie(lotes, esperar=False)
    assert len(outs) == 2
    assert "documentos-liquidaciones" in posts[0]
    assert "documentos-asistencias" in posts[1]
    # Nunca DELETE/cancel
    assert not hasattr(session, "delete") or not session.delete.called


def test_parse_periodo():
    assert parse_periodo("2026-10") == date(2026, 10, 1)
    assert parse_periodo("octubre 2026") == date(2026, 10, 1)
    assert periodo_texto(date(2026, 10, 1)) == "octubre 2026"
    assert periodo_default(date(2026, 11, 17)) == date(2026, 10, 1)


def test_sync_final_tipos():
    session = mock.MagicMock()
    resp = mock.MagicMock()
    resp.raise_for_status = mock.MagicMock()
    resp.json.return_value = {"name": "executions/sync1"}
    session.post.return_value = resp
    client = WorkflowsCliente(
        project="worldwide-470917",
        region="us-east1",
        session=session,
        sleep_fn=lambda _s: None,
    )
    client.sync_final(["liquidacion", "cotizaciones", "transferencia"])
    _, kwargs = session.post.call_args
    env = kwargs["json"]["overrides"]["containerOverrides"][0]["env"]
    assert env[0]["name"] == "SYNC_TIPOS"
    assert env[0]["value"] == "liquidaciones,cotizaciones,transferencias"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
