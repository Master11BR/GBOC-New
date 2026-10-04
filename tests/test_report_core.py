"""Motor de relatórios (report_core): cálculos e renderização com uma fonte de dados em memória."""
import filecmp
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from modules.reports import report_core as rc

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now().replace(microsecond=0)


def test_report_core_identical_between_server_and_agent():
    assert filecmp.cmp(ROOT / "GBOC-Server/modules/reports/report_core.py",
                       ROOT / "GBOC-Agent/engines/report_core.py", shallow=False)


class MemSource:
    """Fonte mínima: 2 agentes, 3 tarefas, execuções com falhas conhecidas."""

    def info(self):
        return {"product": "server", "server_version": "14.7.7", "settings": {"rpo_target_hours": "24", "success_rate_goal": "95"}}

    def agents(self):
        return [{"agent_id": "a1", "hostname": "SRV-A", "last_heartbeat": NOW, "status": "online", "agent_version": "14.7.7"},
                {"agent_id": "a2", "hostname": "SRV-B", "last_heartbeat": NOW - timedelta(days=2), "status": "offline", "agent_version": "14.6.0"}]

    def tasks(self, agent_ids=None):
        return [{"agent_id": "a1", "task_id": 1, "name": "Arquivos", "schedule_cron": "0 22 * * *", "schedule_enabled": True,
                 "enabled": True, "source_paths": ["D:\\Dados"], "retention": "7d"},
                {"agent_id": "a1", "task_id": 2, "name": "SQL", "schedule_cron": "0 3 * * 0", "schedule_enabled": True, "enabled": True,
                 "source_paths": ["E:\\SQL"], "retention": ""},
                {"agent_id": "a2", "task_id": 1, "name": "Nunca", "schedule_cron": None, "enabled": True, "source_paths": []}]

    def repositories(self, agent_ids=None):
        return [{"agent_id": "a1", "repo_id": 1, "name": "Repo", "type": "local", "size_bytes": 900 * 1024 ** 3,
                 "free_bytes": 20 * 1024 ** 3, "capacity_bytes": 1000 * 1024 ** 3}]

    def repo_size_history(self, start, agent_ids=None):
        return [{"agent_id": "a1", "repo_id": 1, "size_bytes": (800 + i * 10) * 1024 ** 3, "recorded_at": NOW - timedelta(days=10 - i)}
                for i in range(11)]

    def runs(self, start, end, agent_ids=None):
        out = []
        for d in range(10):
            ts = NOW - timedelta(days=d, hours=1)
            fail = d in (1, 3)
            out.append({"agent_id": "a1", "task_id": 1, "task_name": "Arquivos", "raw_status": "failed" if fail else "completed",
                        "started_at": ts, "duration_s": 600, "bytes": 10 * 1024 ** 3, "bytes_added": 200 * 1024 ** 2,
                        "error": "Access is denied: 'D:\\Dados\\x.xlsx'" if fail else None})
        out.append({"agent_id": "a1", "task_id": 2, "task_name": "SQL", "raw_status": "completed", "started_at": NOW - timedelta(days=5),
                    "duration_s": 100, "bytes": 1024 ** 3})
        return out

    def restores(self, *a, **k): return []
    def verifications(self, *a, **k): return []
    def job_failures(self, *a, **k): return []
    def volumes(self, agent_ids=None): return [{"agent_id": "a1", "mountpoint": "C:\\", "total_bytes": 100 * 1024 ** 3, "used_bytes": 95 * 1024 ** 3, "free_bytes": 5 * 1024 ** 3}]
    def replication(self, agent_ids=None): return []
    def metrics(self, *a, **k): return []
    def events(self, *a, **k): return []
    def log_error_summary(self, *a, **k): return []
    def log_error_daily(self, *a, **k): return []
    def security(self, *a, **k): return {"incidents": [], "events": []}
    def audit(self, *a, **k): return []
    def tenants(self): return []
    def inventory_status(self): return {"a1": NOW, "a2": NOW}


@pytest.mark.parametrize("cron,hours", [("0 22 * * *", 24), ("0 * * * *", 1), ("0 3 * * 0", 168), ("*/30 * * * *", 0.5)])
def test_cron_interval(cron, hours):
    assert rc.cron_interval_hours(cron) == pytest.approx(hours, rel=0.05)


def test_error_classification_and_pattern():
    assert rc.classify_error("Access is denied: 'D:\\x'")[0].startswith("Permissão")
    assert rc.classify_error("connection timed out")[0].startswith("Rede")
    assert rc.error_pattern("Access is denied: 'D:\\a\\b.txt' after 3 tries") == "Access is denied: '…' after N tries"


def test_status_normalization():
    assert rc.norm_status("Completed") == "success"
    assert rc.norm_status("ERROR") == "failed"
    assert rc.norm_status("running") == "running"


def test_every_catalog_report_builds_and_renders():
    src = MemSource()
    for item in rc.catalog("server"):
        rep = rc.build_report(src, item["code"], days=30)
        html = rc.render_html(rep)
        assert rep["title"] in html and "<svg" in html or not rep["charts"]
        assert rc.render_csv(rep).startswith("GBOC")
        assert rc.legacy_payload(rep)["code"] == item["code"]


def test_numbers_come_from_data():
    src = MemSource()
    rep = rc.build_report(src, "REP-01", days=30)
    kpi = {k["label"]: k["value"] for k in rep["kpis"]}
    assert kpi["Execuções concluídas"] == "11"            # 10 + 1
    assert kpi["Taxa de sucesso"] == "81,8%"               # 9/11
    rpo = rc.build_report(src, "REP-02", days=30)
    statuses = {r[1]: rc.cell_text(r[8]) for r in rpo["tables"][0]["rows"]}
    assert statuses["SQL"] == "Dentro do RPO"              # semanal: alvo = intervalo + 25%
    assert statuses["Nunca"] == "Nunca concluída com sucesso"
    cap = rc.build_report(src, "REP-06", days=30)
    assert any("Disco acima de 90%" in rc.cell_text(c) or "Esgota" in rc.cell_text(c) for r in cap["tables"][0]["rows"] for c in r)
    rca = rc.build_report(src, "REP-04", days=30)
    assert rca["tables"][0]["rows"][0][0].startswith("Permissão")
