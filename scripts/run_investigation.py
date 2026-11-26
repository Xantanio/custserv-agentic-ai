"""Roda o agente investigador contra o Ollama e o servidor MCP reais.

Raiz de composição (D23, D26): o ÚNICO lugar que monta as peças concretas e as
injeta no agente: modelo pela fábrica, ferramentas pelo protocolo MCP (HTTP),
auditoria na tabela `audit_events`.

Pré-requisitos: Postgres + seed + MCP (`docker compose up -d postgres seed_db mcp_server`)
e o Ollama com o modelo configurado no .env.

Uso:
    python scripts/run_investigation.py LOTE-2026-DEF
    python scripts/run_investigation.py LOTE-2026-DEF --max-steps 6 --json
"""

import argparse
import asyncio
import sys

from agents.investigator import Investigator
from core.audit import InMemoryAuditSink, SqlAuditSink
from core.config import Settings
from core.database import AsyncSessionLocal
from core.schemas import InvestigationReport
from integrations.mcp_tools import open_mcp_tools
from llm.factory import build_chat_model, resolve_llm_spec
from mcp_server.investigation_tools import INVESTIGATOR_TOOLS


def _print_report(report: InvestigationReport) -> None:
    print(f"\n=== Investigação de {report.batch_id} ===")
    print(f"modelo: {report.model_version} | passos: {report.steps} | parada: {report.stop_reason} "
          f"| tentativas de relatório: {report.finalize_attempts} | {report.duration_seconds:.1f} s")
    print(f"thread_id (auditoria): {report.thread_id}")
    print("\nFerramentas chamadas (registro do código, não do modelo):")
    for i, call in enumerate(report.tools_called, 1):
        print(f"  {i}. [{call.status:8}] {call.name}({', '.join(f'{k}={v}' for k, v in call.args.items())})")
    verdict = "causa identificada" if report.root_cause_identified else "CAUSA INDETERMINADA"
    print(f"\nConclusão: {verdict}")
    for i, h in enumerate(report.hypotheses, 1):
        print(f"\n  Hipótese {i} (confiança {h.confidence}): {h.description}")
        for e in h.evidence:
            print(f"    - {e}")
    if report.unknowns:
        print("\nIncógnitas:")
        for u in report.unknowns:
            print(f"  - {u}")
    if report.recommended_checks:
        print("\nVerificações recomendadas ao especialista:")
        for c in report.recommended_checks:
            print(f"  - {c}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Roda o agente investigador de causa raiz.")
    parser.add_argument("batch_id")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=300.0, help="segundos")
    parser.add_argument("--json", action="store_true", help="imprime o relatório em JSON")
    parser.add_argument("--no-audit", action="store_true", help="não grava em audit_events")
    args = parser.parse_args()

    settings = Settings()
    spec = resolve_llm_spec(settings, "investigator")
    llm = build_chat_model(spec)
    audit = InMemoryAuditSink() if args.no_audit else SqlAuditSink(AsyncSessionLocal)
    print(f"Modelo: {spec.model_version} em {spec.base_url} (num_ctx={spec.num_ctx}) | MCP: {settings.MCP_SERVER_URL}",
          file=sys.stderr)

    async with open_mcp_tools(settings.MCP_SERVER_URL, INVESTIGATOR_TOOLS) as tools:
        agent = Investigator(
            llm, tools, audit=audit, model_version=spec.model_version,
            max_steps=args.max_steps, timeout_seconds=args.timeout, context_tokens=spec.num_ctx,
        )
        report = await agent.investigate(args.batch_id)

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        _print_report(report)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
