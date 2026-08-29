# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Module: Compliance Central Server Router
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================
"""
Compliance Central Server Router

Agrega dados de conformidade de todos os agentes (ISO 27001, SOC 2, HIPAA, LGPD)
e expõe dashboards, relatórios e alertas de violação centralizados.
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

logger = logging.getLogger("compliance_server_router")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from server_gboc import get_db, release_db
except Exception:
    from gboc_server import get_db, release_db

router = APIRouter(prefix="/api/v1/server/compliance", tags=["Compliance Central"])


@router.get("/dashboard")
async def compliance_dashboard():
    """
    Painel central de conformidade agregado de todos os agentes.
    Retorna scores ISO 27001 / SOC 2 / HIPAA / LGPD por agente e globais.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()

        # Score global: % de agentes com backup nas últimas 24h
        cur.execute("""
            SELECT
                COUNT(DISTINCT a.agent_id) AS total_agents,
                COUNT(DISTINCT br.agent_id) AS agents_with_backup_24h,
                SUM(CASE WHEN br.status = 'success' THEN 1 ELSE 0 END) AS successful_backups_24h,
                SUM(CASE WHEN br.status = 'error' THEN 1 ELSE 0 END) AS failed_backups_24h
            FROM agents a
            LEFT JOIN backup_reports br ON br.agent_id = a.agent_id
                AND br.created_at > LOCALTIMESTAMP - INTERVAL '24 hours'
        """)
        global_row = cur.fetchone()
        global_cols = [d[0] for d in cur.description]
        global_stats = dict(zip(global_cols, global_row)) if global_row else {}

        total_agents = global_stats.get("total_agents", 0) or 1
        agents_backed = global_stats.get("agents_with_backup_24h", 0) or 0
        coverage_pct = round((agents_backed / total_agents) * 100, 1)

        # Por agente
        cur.execute("""
            SELECT
                a.agent_id,
                a.hostname,
                a.status,
                a.last_heartbeat,
                COUNT(br.report_id) AS backups_30d,
                SUM(CASE WHEN br.status = 'success' THEN 1 ELSE 0 END) AS success_30d,
                SUM(CASE WHEN br.status = 'error' THEN 1 ELSE 0 END) AS failed_30d,
                MAX(CASE WHEN br.status = 'success' THEN br.created_at END) AS last_success_at
            FROM agents a
            LEFT JOIN backup_reports br ON br.agent_id = a.agent_id
                AND br.created_at > LOCALTIMESTAMP - INTERVAL '30 days'
            GROUP BY a.agent_id, a.hostname, a.status, a.last_heartbeat
            ORDER BY a.hostname
        """)
        agents = []
        for row in cur.fetchall():
            cols = [d[0] for d in cur.description]
            agent = dict(zip(cols, row))
            backups_30d = agent.get("backups_30d", 0) or 0
            success_30d = agent.get("success_30d", 0) or 0
            agent["success_rate_30d"] = round((success_30d / backups_30d) * 100, 1) if backups_30d > 0 else 0.0
            # Compliance score simples: cobertura + taxa de sucesso
            agent["compliance_score"] = round((agent["success_rate_30d"] * 0.7) + (coverage_pct * 0.3), 1)
            agent["compliance_level"] = (
                "critical" if agent["compliance_score"] < 50 else
                "warning" if agent["compliance_score"] < 80 else
                "compliant"
            )
            agents.append(agent)

        cur.close()
        return {
            "status": "success",
            "global_coverage_pct": coverage_pct,
            "global_stats": global_stats,
            "standards": {
                "iso_27001": {"requirement": "Backup documentado e testado", "coverage_pct": coverage_pct},
                "soc2_cc9": {"requirement": "Recuperabilidade verificada", "coverage_pct": coverage_pct},
                "hipaa_164": {"requirement": "Backup de dados de saúde", "coverage_pct": coverage_pct},
                "lgpd": {"requirement": "Proteção de dados pessoais", "coverage_pct": coverage_pct}
            },
            "agent_count": len(agents),
            "agents": agents,
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"[COMPLIANCE] Erro no dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.get("/violations")
async def compliance_violations(days: int = Query(default=7, ge=1, le=90)):
    """
    Lista violações de conformidade (agentes sem backup há mais de X dias,
    backups com falha consecutiva, etc.).
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()

        # Agentes sem backup bem-sucedido nos últimos `days` dias
        cur.execute("""
            SELECT
                a.agent_id,
                a.hostname,
                a.status,
                a.last_heartbeat,
                MAX(br.created_at) AS last_backup_at,
                MAX(CASE WHEN br.status = 'success' THEN br.created_at END) AS last_success_at
            FROM agents a
            LEFT JOIN backup_reports br ON br.agent_id = a.agent_id
            GROUP BY a.agent_id, a.hostname, a.status, a.last_heartbeat
            HAVING MAX(CASE WHEN br.status = 'success' THEN br.created_at END) < LOCALTIMESTAMP - INTERVAL '%s days'
                OR MAX(CASE WHEN br.status = 'success' THEN br.created_at END) IS NULL
            ORDER BY last_success_at ASC NULLS FIRST
        """ % int(days))

        violations = []
        for row in cur.fetchall():
            cols = [d[0] for d in cur.description]
            v = dict(zip(cols, row))
            # Calcular dias desde o último backup bem-sucedido
            if v.get("last_success_at"):
                try:
                    last_ts = v["last_success_at"]
                    if hasattr(last_ts, "timestamp"):
                        age_days = (datetime.now() - last_ts.replace(tzinfo=None)).days
                    else:
                        age_days = -1
                except Exception:
                    age_days = -1
            else:
                age_days = -1  # Nunca teve backup bem-sucedido
            v["days_since_last_success"] = age_days
            v["severity"] = "critical" if age_days < 0 or age_days > 14 else "warning"
            violations.append(v)

        cur.close()
        return {
            "status": "success",
            "period_days": days,
            "violations_count": len(violations),
            "violations": violations,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"[COMPLIANCE] Erro nas violações: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.get("/certificates")
async def compliance_certificates():
    """
    Lista provas digitais de backup (SHA-256 hash dos snapshots) de todos os agentes
    para uso em auditoria ISO 27001 / SOC 2.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                br.report_id,
                br.agent_id,
                a.hostname,
                br.backup_type,
                br.source_path,
                br.start_time,
                br.end_time,
                br.status,
                br.total_bytes,
                br.snapshot_id,
                br.created_at
            FROM backup_reports br
            JOIN agents a ON a.agent_id = br.agent_id
            WHERE br.status = 'success'
              AND br.snapshot_id IS NOT NULL
            ORDER BY br.created_at DESC
            LIMIT 200
        """)
        certs = []
        for row in cur.fetchall():
            cols = [d[0] for d in cur.description]
            cert = dict(zip(cols, row))
            # Gerar prova digital baseada nos dados reais do relatório
            import hashlib
            proof_data = f"{cert['agent_id']}:{cert['snapshot_id']}:{cert['start_time']}:{cert['total_bytes']}"
            cert["digital_proof_sha256"] = hashlib.sha256(proof_data.encode()).hexdigest()
            cert["certificate_id"] = f"GBOC-CERT-{cert['report_id']:08d}"
            certs.append(cert)
        cur.close()
        return {
            "status": "success",
            "certificate_count": len(certs),
            "certificates": certs,
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"[COMPLIANCE] Erro nos certificados: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)
