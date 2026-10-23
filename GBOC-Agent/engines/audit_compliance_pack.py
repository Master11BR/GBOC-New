# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
# Module: International Audit & Regulatory Compliance Certification Pack
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import json
import time
import hashlib
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("gboc_audit_compliance_pack")


class AuditCompliancePack:
    """
    Laudo tecnico de AUTOAVALIACAO de controles de backup, mapeado para ISO/IEC 27001, SOC 2,
    HIPAA, PCI-DSS e LGPD/GDPR. Cada controle e verificado nos dados reais do Agente; nada e presumido.
    Nao e certificacao: certificacao exige auditoria independente.
    """

    STANDARDS = {
        "ISO_27001": {"name": "ISO/IEC 27001:2022 (A.8.13 Backup, A.8.24 Criptografia, A.8.15 Logs)",
                      "controls": ["encryption", "recent_backups", "restore_test", "retention", "audit_trail", "transport_tls"]},
        "SOC_2": {"name": "SOC 2 (Disponibilidade e Confidencialidade)",
                  "controls": ["recent_backups", "restore_test", "encryption", "audit_trail", "ransomware"]},
        "HIPAA": {"name": "HIPAA 45 CFR 164.308(a)(7) Data Backup / Disaster Recovery Plan",
                  "controls": ["recent_backups", "restore_test", "encryption", "retention"]},
        "LGPD_GDPR": {"name": "LGPD Art. 46 / GDPR Art. 32 (Segurança e Resiliência)",
                      "controls": ["encryption", "transport_tls", "restore_test", "audit_trail"]},
        "PCI_DSS": {"name": "PCI-DSS v4.0 Req. 3, 10 e 12 (Proteção, Trilha e Retenção)",
                    "controls": ["encryption", "audit_trail", "retention", "transport_tls"]},
    }

    @staticmethod
    def _q(sql: str, params: tuple = ()) -> list:
        from shared_core import get_shared_core
        with get_shared_core().get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()

    def _checks(self, transport_scheme: Optional[str]) -> Dict[str, Dict[str, Any]]:
        C: Dict[str, Dict[str, Any]] = {}

        def put(key, rule, ok, detail):
            C[key] = {"rule": rule, "status": "PASS" if ok is True else ("FAIL" if ok is False else "NOT_VERIFIED"), "evidence": detail}

        # 1. Criptografia em repouso: repositorios ativos com senha de criptografia
        try:
            rows = self._q("""SELECT name, COALESCE(NULLIF(encryption_password,''), NULLIF(password,''), NULLIF(motor_password,'')) IS NOT NULL
                              FROM repositories WHERE COALESCE(enabled, TRUE) AND COALESCE(status,'active') IN ('active','ready')""")
            sem = [r[0] for r in rows if not r[1]]
            put("encryption", "Criptografia em repouso dos repositórios", bool(rows) and not sem if rows else None,
                f"{len(rows) - len(sem)}/{len(rows)} repositório(s) ativos com senha de criptografia" + (f"; sem: {', '.join(sem[:5])}" if sem else ""))
        except Exception as e:
            put("encryption", "Criptografia em repouso dos repositórios", None, f"não verificado: {e}")

        # 2. Backups recentes: toda tarefa agendada com execucao concluida nas ultimas 48 h
        try:
            rows = self._q("""SELECT t.name, MAX(te.completed_at) FROM tasks t
                              LEFT JOIN task_executions te ON te.task_id = t.id AND te.status IN ('completed','success','warning')
                              WHERE COALESCE(t.enabled, TRUE) AND COALESCE(t.schedule_enabled, FALSE)
                              GROUP BY t.id, t.name""")
            now = datetime.now()
            atrasadas = []
            for name, last in rows:
                if last is not None and getattr(last, "tzinfo", None) is not None:
                    last = last.astimezone().replace(tzinfo=None)
                if not last or (now - last).total_seconds() > 48 * 3600:
                    atrasadas.append(name)
            put("recent_backups", "Backups agendados concluídos nas últimas 48 h", (not atrasadas) if rows else None,
                f"{len(rows) - len(atrasadas)}/{len(rows)} tarefa(s) agendadas em dia" + (f"; atrasadas: {', '.join(atrasadas[:5])}" if atrasadas else ""))
        except Exception as e:
            put("recent_backups", "Backups agendados concluídos nas últimas 48 h", None, f"não verificado: {e}")

        # 3. Teste de restauracao / integridade nos ultimos 30 dias
        try:
            n_int = self._q("SELECT COUNT(*) FROM integrity_checks WHERE started_at >= NOW() - INTERVAL '30 days' AND status IN ('ok','success','completed','passed')")[0][0]
            n_sb = 0
            try:
                n_sb = self._q("SELECT COUNT(*) FROM surebackup_verifications WHERE created_at >= NOW() - INTERVAL '30 days'")[0][0]
            except Exception:
                pass
            n_rs = 0
            try:
                n_rs = self._q("SELECT COUNT(*) FROM restore_history WHERE created_at >= NOW() - INTERVAL '30 days'")[0][0]
            except Exception:
                pass
            total = int(n_int or 0) + int(n_sb or 0) + int(n_rs or 0)
            put("restore_test", "Teste de integridade/restauração nos últimos 30 dias", total > 0,
                f"{n_int} verificação(ões) de integridade aprovadas, {n_sb} teste(s) de boot, {n_rs} restauração(ões)")
        except Exception as e:
            put("restore_test", "Teste de integridade/restauração nos últimos 30 dias", None, f"não verificado: {e}")

        # 4. Retencao configurada em todas as tarefas ativas
        try:
            rows = self._q("""SELECT name, COALESCE(retention_days,0)+COALESCE(retention_weekly,0)+COALESCE(retention_monthly,0)+COALESCE(retention_yearly,0)
                              FROM tasks WHERE COALESCE(enabled, TRUE)""")
            sem = [r[0] for r in rows if not r[1]]
            put("retention", "Política de retenção definida", (not sem) if rows else None,
                f"{len(rows) - len(sem)}/{len(rows)} tarefa(s) com retenção" + (f"; sem: {', '.join(sem[:5])}" if sem else ""))
        except Exception as e:
            put("retention", "Política de retenção definida", None, f"não verificado: {e}")

        # 5. Trilha de auditoria ativa (registros nos ultimos 30 dias)
        try:
            n = self._q("SELECT COUNT(*) FROM audit_log WHERE timestamp >= NOW() - INTERVAL '30 days'")[0][0]
            put("audit_trail", "Trilha de auditoria registrando eventos", int(n) > 0, f"{n} evento(s) de auditoria nos últimos 30 dias")
        except Exception as e:
            put("audit_trail", "Trilha de auditoria registrando eventos", None, f"não verificado: {e}")

        # 6. Protecao contra ransomware: Guardian ativo e sem incidente aberto
        try:
            from engines.ransomware_guardian import get_guardian
            g = get_guardian().get_guardian_status()
            n_act = self._q("SELECT COUNT(*) FROM ransomware_incidents WHERE status = 'active'")[0][0]
            ok = bool(g.get("running")) and int(n_act) == 0
            put("ransomware", "Ransomware Guardian ativo e sem incidentes abertos", ok,
                f"Guardian {'em execução' if g.get('running') else 'parado'}; {n_act} incidente(s) ativo(s)")
        except Exception as e:
            put("ransomware", "Ransomware Guardian ativo e sem incidentes abertos", None, f"não verificado: {e}")

        # 7. Transporte criptografado (TLS) na interface do Agente
        put("transport_tls", "Interface do Agente servida por HTTPS (TLS)",
            (transport_scheme == "https") if transport_scheme else None,
            f"conexão atual: {transport_scheme or 'desconhecida'}")
        return C

    def generate_compliance_certificate(self, target_agent: Optional[str] = None, transport_scheme: Optional[str] = None) -> Dict[str, Any]:
        """Laudo de autoavaliação com evidências reais e hash SHA-256 do próprio conteúdo avaliado."""
        import socket
        target = target_agent or os.environ.get("COMPUTERNAME") or socket.gethostname()
        checks = self._checks(transport_scheme)
        standards = {}
        for key, std in self.STANDARDS.items():
            evaluated = [checks[c] for c in std["controls"] if c in checks and checks[c]["status"] != "NOT_VERIFIED"]
            passed = sum(1 for c in evaluated if c["status"] == "PASS")
            not_verified = sum(1 for c in std["controls"] if checks.get(c, {}).get("status") == "NOT_VERIFIED")
            score = round(100.0 * passed / len(evaluated), 1) if evaluated else None
            status = ("SEM_DADOS" if not evaluated else "CONFORME" if passed == len(evaluated) and not not_verified
                      else "CONFORME_PARCIAL" if passed == len(evaluated) else "NAO_CONFORME")
            standards[key] = {"name": std["name"], "compliance_score": score, "status": status,
                              "controls_passed": passed, "controls_evaluated": len(evaluated), "controls_not_verified": not_verified}
        timestamp = datetime.now().isoformat()
        all_status = [c["status"] for c in checks.values()]
        overall = "CONFORME" if all(s == "PASS" for s in all_status) else ("NAO_CONFORME" if "FAIL" in all_status else "CONFORME_PARCIAL")
        body = {"target": target, "issued_at": timestamp, "checks": checks}
        proof = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
        return {
            "certificate_id": f"GBOC-AUTOAVAL-{int(time.time())}",
            "issuer": "GBOC Agent - autoavaliação técnica (não é certificação; exige auditoria independente)",
            "evaluated_target": target,
            "issued_at": timestamp,
            "valid_until": None,
            "overall_status": overall,
            "cryptographic_proof_sha256": proof,
            "standards_evaluated": standards,
            "audit_checks": [{"rule": c["rule"], "status": c["status"], "evidence": c["evidence"]} for c in checks.values()],
        }


# Singleton global
audit_compliance_pack = AuditCompliancePack()
