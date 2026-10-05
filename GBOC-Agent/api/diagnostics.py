#!/usr/bin/env python3
"""
🔍 GBOC Agent 14.6.0 - API DIAGNOSTICS
Responsável por: Rotas para sistema de diagnóstico
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any, List
import asyncio
import platform
import shutil
import subprocess
import psutil
import os
import time
from datetime import datetime
import logging

from shared_core import get_shared_core

logger = logging.getLogger("API-Diagnostics")
router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

@router.get("/quick")
async def quick_diagnostic() -> Dict[str, Any]:
    """Diagnóstico rápido do sistema (100% Real - Zero-Mock)"""
    try:
        t0 = time.perf_counter()
        core = get_shared_core()
        
        # Métricas básicas do sistema
        system_metrics = await _get_system_metrics()
        
        # Ferramentas de backup
        backup_tools = await _check_backup_tools()
        
        # Health score
        health_score = _calculate_health_score(system_metrics, backup_tools)
        
        elapsed = round(time.perf_counter() - t0, 3)
        result = {
            "timestamp": datetime.now().isoformat(),
            "execution_time": elapsed,
            "overall_health": health_score,
            "status": _get_health_status(health_score),
            "system": {
                "cpu": system_metrics["cpu"]["usage_percent"],
                "memory": system_metrics["memory"]["usage_percent"],
                "disk": system_metrics["disk"]["usage_percent"],
                "platform": platform.system()
            },
            "tools": {
                "available": len([tool for tool in backup_tools.values() if tool["available"]]),
                "total": len(backup_tools)
            },
            "repositories": await _get_repository_summary(core),
            "recent_errors": await _get_recent_error_count(core)
        }

        # Salvar no banco
        await _save_diagnostic(core, result, "quick")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in quick diagnostic: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/full")
async def full_diagnostic() -> Dict[str, Any]:
    """Diagnóstico completo e detalhado"""
    try:
        start_time = datetime.now()
        core = get_shared_core()
        
        # Diagnósticos paralelos para performance
        system_info, network_info, backup_tools, disk_info, process_info = await asyncio.gather(
            _get_detailed_system_info(),
            _get_network_info(),
            _check_backup_tools_detailed(),
            _get_disk_analysis(),
            _get_process_info()
        )
        
        # Análise de repositórios
        repo_analysis = await _analyze_repositories(core)
        
        # Análise de tarefas
        task_analysis = await _analyze_tasks(core)
        
        # Recomendações
        recommendations = _generate_recommendations(system_info, backup_tools, repo_analysis)
        
        # Calcular tempo de execução
        execution_time = (datetime.now() - start_time).total_seconds()
        
        # Health score detalhado
        detailed_health = _calculate_detailed_health(system_info, backup_tools, repo_analysis, task_analysis)
        
        result = {
            "timestamp": start_time.isoformat(),
            "execution_time": execution_time,
            "overall_health": detailed_health["overall"],
            "status": _get_health_status(detailed_health["overall"]),
            "system": system_info,
            "network": network_info,
            "storage": disk_info,
            "processes": process_info,
            "backup_tools": backup_tools,
            "repositories": repo_analysis,
            "tasks": task_analysis,
            "health_breakdown": detailed_health["breakdown"],
            "recommendations": recommendations,
            "security": await _security_analysis()
        }
        
        # Salvar no banco
        await _save_diagnostic(core, result, "full")
        
        core.log_system_event("INFO", "diagnostics", f"Full diagnostic completed in {execution_time:.2f}s")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in full diagnostic: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tools")
async def get_backup_tools() -> Dict[str, Any]:
    """Verifica ferramentas de backup disponíveis"""
    try:
        tools = await _check_backup_tools_detailed()
        
        return {
            "timestamp": datetime.now().isoformat(),
            "tools": tools,
            "summary": {
                "available": len([t for t in tools.values() if t["available"]]),
                "total": len(tools),
                "recommended": ["restic", "kopia"]
            }
        }
        
    except Exception as e:
        logger.error(f"Error checking backup tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/system")
async def get_system_info() -> Dict[str, Any]:
    """Informações detalhadas do sistema"""
    try:
        return await _get_detailed_system_info()
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/network")
async def get_network_info() -> Dict[str, Any]:
    """Informações de rede"""
    try:
        return await _get_network_info()
    except Exception as e:
        logger.error(f"Error getting network info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history")
def get_diagnostic_history(limit: int = 20) -> Dict[str, Any]:
    """Histórico de diagnósticos"""
    try:
        core = get_shared_core()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, category, cpu_usage, memory_usage, 
                       disk_usage, system_health, details
                FROM diagnostics 
                ORDER BY timestamp DESC 
                LIMIT %s
            """, (limit,))
            
            history = []
            for row in cursor.fetchall():
                entry = {
                    "timestamp": row[0],
                    "category": row[1],
                    "cpu_usage": row[2],
                    "memory_usage": row[3],
                    "disk_usage": row[4],
                    "system_health": row[5],
                    "details": row[6]
                }
                history.append(entry)
            
            return {
                "history": history,
                "total": len(history)
            }
            
    except Exception as e:
        logger.error(f"Error getting diagnostic history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/run/{diagnostic_type}")
async def run_specific_diagnostic(diagnostic_type: str) -> Dict[str, Any]:
    """Executa tipo específico de diagnóstico"""
    try:
        if diagnostic_type == "quick":
            return await quick_diagnostic()
        elif diagnostic_type == "full":
            return await full_diagnostic()
        elif diagnostic_type == "tools":
            return await get_backup_tools()
        elif diagnostic_type == "system":
            return await get_system_info()
        elif diagnostic_type == "network":
            return await get_network_info()
        else:
            raise HTTPException(status_code=400, detail=f"Tipo de diagnóstico não suportado: {diagnostic_type}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running diagnostic {diagnostic_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==============================================================================
# IA de diagnóstico (rotas únicas, expostas em /api/diagnostics e /api/v1/diagnostics)
# ==============================================================================

router_v1 = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics v1 (IA)"])


async def _json_body(request: Request) -> Dict[str, Any]:
    """Lê o corpo JSON (aceita 'application/json; charset=utf-8'); corpo vazio/ inválido -> {}."""
    if not (request.headers.get("content-type") or "").lower().startswith("application/json"):
        return {}
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


def _ai_auth(request: Request, admin: bool = False):
    from api.ai_api import require_ai_user
    return require_ai_user(request, admin=admin)


def _repair_clean_temp(max_age_hours: int = 24) -> Dict[str, Any]:
    """Remove arquivos temporários do Agente mais antigos que max_age_hours (data/temp)."""
    from pathlib import Path
    temp_dir = Path(__file__).resolve().parents[1] / "data" / "temp"
    if not temp_dir.exists():
        return {"action": "Limpeza de data/temp", "ok": True, "detail": "Diretório inexistente — nada a limpar."}
    cutoff = time.time() - max_age_hours * 3600
    removed, freed, errors = 0, 0, 0
    for f in temp_dir.rglob("*"):
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                size = f.stat().st_size
                f.unlink()
                removed += 1
                freed += size
        except OSError:
            errors += 1
    return {"action": "Limpeza de data/temp", "ok": errors == 0,
            "detail": f"{removed} arquivo(s) removido(s), {freed / 1048576:.1f} MB liberados" + (f", {errors} erro(s)" if errors else "")}


def _repair_db_maintenance() -> Dict[str, Any]:
    """Atualiza estatísticas do PostgreSQL nas tabelas operacionais (ANALYZE)."""
    try:
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            for table in ("tasks", "task_executions", "repositories", "system_logs"):
                cur.execute(f"ANALYZE {table}")
            conn.commit()
            cur.close()
        return {"action": "Manutenção do banco (ANALYZE)", "ok": True, "detail": "Estatísticas atualizadas em 4 tabelas."}
    except Exception as e:
        return {"action": "Manutenção do banco (ANALYZE)", "ok": False, "detail": f"{e.__class__.__name__}: {e}"}


def _repair_report_stale_runs(hours: int = 48) -> Dict[str, Any]:
    """Conta (sem alterar) execuções presas em 'running' há mais de N horas, para revisão manual."""
    try:
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM task_executions WHERE status = 'running' AND started_at < NOW() - make_interval(hours => %s)",
                (hours,),
            )
            stale = cur.fetchone()[0]
            cur.close()
        detail = (f"{stale} execução(ões) em 'running' há mais de {hours}h — verifique se o processo ainda existe."
                  if stale else f"Nenhuma execução presa há mais de {hours}h.")
        return {"action": "Verificação de execuções presas", "ok": stale == 0, "detail": detail}
    except Exception as e:
        return {"action": "Verificação de execuções presas", "ok": False, "detail": f"{e.__class__.__name__}: {e}"}


def _repair_audit(results: List[Dict[str, Any]], user: Dict[str, Any]) -> None:
    try:
        import json as _json
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO system_logs (timestamp, level, source, message, details) VALUES (%s, %s, %s, %s, %s)",
                (datetime.now().isoformat(), "INFO", "AI-Repair",
                 f"Manutenção automatizada executada por {user.get('username', '?')}",
                 _json.dumps(results, ensure_ascii=False)),
            )
            conn.commit()
            cur.close()
    except Exception as e:
        logger.error(f"Falha ao auditar AI-Repair em system_logs: {e}")


@router.api_route("/ai-repair", methods=["POST"])
@router_v1.api_route("/ai-repair", methods=["POST"])
async def router_ai_repair(request: Request):
    """
    Manutenção automatizada REAL e verificável. O histórico de falhas NÃO é alterado
    (antes os registros 'failed' eram reescritos como 'repaired', mascarando falhas reais).
    """
    user = _ai_auth(request)
    body = await _json_body(request)
    results = [
        await asyncio.to_thread(_repair_clean_temp),
        await asyncio.to_thread(_repair_db_maintenance),
        await asyncio.to_thread(_repair_report_stale_runs),
    ]
    await asyncio.to_thread(_repair_audit, results, user)
    all_ok = all(r["ok"] for r in results)
    return {
        "status": "success" if all_ok else "partial",
        "message": "Manutenção concluída." if all_ok else "Manutenção concluída com pendências — veja os detalhes.",
        "action": body.get("action", "auto"),
        "target": body.get("target", "system"),
        "results": results,
        "actions_taken": [f"{'✓' if r['ok'] else '✗'} {r['action']}: {r['detail']}" for r in results],
    }


@router.post("/ai-analyze")
@router_v1.post("/ai-analyze")
async def router_ai_analyze(request: Request):
    """Análise de IA de uma falha/alerta (LLM configurado ou heurística com telemetria real)."""
    _ai_auth(request)
    body = await _json_body(request)
    err_msg = body.get("error_message") or body.get("prompt") or "Verificação preventiva de integridade e diagnósticos de rotina."
    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    try:
        return await ai_diagnostic_engine.analyze_error(str(err_msg))
    except Exception as e:
        logger.exception(f"Falha na análise de IA: {e}")
        raise HTTPException(status_code=500, detail="Falha interna ao executar a análise de IA.")


@router.post("/ai-analyze-risk")
@router_v1.post("/ai-analyze-risk")
async def router_ai_analyze_risk(request: Request):
    """Análise de risco de IA por item."""
    _ai_auth(request)
    body = await _json_body(request)
    risk_item = body.get("risk_item") or "Falha Crítica de Inicialização / Repositório"
    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    try:
        return await ai_diagnostic_engine.analyze_error(f"Erro Crítico de Risco: {risk_item}")
    except Exception as e:
        logger.exception(f"Falha na análise de risco: {e}")
        raise HTTPException(status_code=500, detail="Falha interna ao executar a análise de risco.")


@router.post("/ai-analyze-sla")
@router_v1.post("/ai-analyze-sla")
async def router_ai_analyze_sla(request: Request):
    """Análise de SLA via IA com dados reais de tarefas (sem valores presumidos)."""
    _ai_auth(request)
    try:
        from api.preemptive_api import get_sla_compliance
        sla_data = await get_sla_compliance()
    except Exception as e:
        logger.error(f"Dados de SLA indisponíveis: {e}")
        raise HTTPException(status_code=503, detail="Dados de SLA indisponíveis no momento.")
    summary = sla_data.get("summary", {}) if isinstance(sla_data, dict) else {}
    pct = summary.get("compliance_pct")
    if pct is None:
        raise HTTPException(status_code=503, detail="Dados de SLA indisponíveis (sem resumo de compliance).")
    if not summary.get("total_tasks"):
        return {
            "status": "no_data",
            "sla_score": None,
            "summary": summary,
            "analysis": "Nenhuma tarefa cadastrada: não há base para calcular SLA/RPO.",
            "recommendations": ["Cadastre e agende tarefas de backup para que o SLA possa ser medido."],
            "is_llm_real": False,
            "provider": None,
        }

    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    ai_res = await ai_diagnostic_engine.analyze_error(
        f"Análise de SLA: compliance atual de {pct}% com {summary.get('compliant', 0)} tarefas conformes "
        f"de {summary.get('total_tasks', 0)} cadastradas."
    )
    recs = [s.strip(" -•") for s in str(ai_res.get("solution") or "").splitlines() if s.strip()]
    return {
        "status": "success",
        "sla_score": pct,
        "summary": summary,
        "analysis": ai_res.get("analysis", ""),
        "recommendations": recs,
        "is_llm_real": bool(ai_res.get("is_llm_real")),
        "provider": ai_res.get("provider"),
    }


@router.api_route("/ollama-models", methods=["GET", "POST"])
@router_v1.api_route("/ollama-models", methods=["GET", "POST"])
async def get_ollama_models(request: Request):
    """Modelos instalados no Ollama (consulta real a /api/tags)."""
    _ai_auth(request)
    host = request.query_params.get("host")
    if not host and request.method == "POST":
        host = (await _json_body(request)).get("host")
    from engines import ai_providers as aip
    if host:
        try:
            host = aip.validate_http_url(host)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    return await ai_diagnostic_engine.get_installed_ollama_models(host)


@router.post("/ollama-models/pull")
@router_v1.post("/ollama-models/pull")
async def pull_ollama_model(request: Request):
    """Dispara o download (pull) real de um modelo Ollama em segundo plano (somente administradores)."""
    _ai_auth(request, admin=True)
    body = await _json_body(request)
    model = str(body.get("model") or "").strip()
    if not model or len(model) > 200 or any(c.isspace() for c in model):
        raise HTTPException(status_code=400, detail="Nome do modelo inválido.")
    from engines import ai_providers as aip
    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    try:
        host = aip.validate_http_url(body.get("host") or ai_diagnostic_engine.config.get("ollama_host") or aip.DEFAULT_OLLAMA_HOST)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async def pull_task():
        logger.info(f"Iniciando download do modelo '{model}' em {host}...")
        ok, msg = await asyncio.to_thread(aip.pull_ollama_model, host, model)
        (logger.info if ok else logger.error)(msg)

    asyncio.create_task(pull_task())
    return {"status": "downloading", "message": f"O download do modelo '{model}' foi iniciado em segundo plano."}


@router.get("/ai-config")
@router_v1.get("/ai-config")
async def get_ai_config(request: Request):
    """Configuração do motor de IA de diagnóstico (chaves mascaradas)."""
    _ai_auth(request)
    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    return ai_diagnostic_engine.public_config()


@router.post("/ai-config")
@router_v1.post("/ai-config")
async def save_ai_config(request: Request):
    """Salva a configuração do motor de IA de diagnóstico (somente administradores)."""
    _ai_auth(request, admin=True)
    body = await _json_body(request)
    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    try:
        saved = ai_diagnostic_engine.save_config(body)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        logger.error(f"Falha ao gravar configuração de IA: {e}")
        raise HTTPException(status_code=500, detail="Falha ao gravar a configuração de IA no disco.")
    return {"status": "success", "message": "Configurações de IA salvas", "config": saved}

# Funções auxiliares
async def _get_system_metrics() -> Dict[str, Any]:
    """Métricas básicas do sistema"""
    try:
        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        
        # Memória
        memory = psutil.virtual_memory()
        
        # Disco
        disk = psutil.disk_usage('/' if platform.system() != 'Windows' else 'C:')
        
        return {
            "cpu": {
                "usage_percent": cpu_percent,
                "count": cpu_count,
                "status": "normal" if cpu_percent < 80 else "high" if cpu_percent < 95 else "critical"
            },
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "used_gb": round(memory.used / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "usage_percent": memory.percent,
                "status": "normal" if memory.percent < 80 else "high" if memory.percent < 95 else "critical"
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "usage_percent": round((disk.used / disk.total) * 100, 2),
                "status": "normal" if disk.used/disk.total < 0.8 else "high" if disk.used/disk.total < 0.95 else "critical"
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting system metrics: {e}")
        return {"error": str(e)}

async def _get_detailed_system_info() -> Dict[str, Any]:
    """Informações detalhadas do sistema"""
    try:
        # Informações básicas
        uname = platform.uname()
        
        # Informações de CPU
        cpu_freq = psutil.cpu_freq()
        cpu_stats = psutil.cpu_stats()
        
        # Informações de memória
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        # Boot time
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        
        return {
            "platform": {
                "system": uname.system,
                "node": uname.node,
                "release": uname.release,
                "version": uname.version,
                "machine": uname.machine,
                "processor": uname.processor
            },
            "cpu": {
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
                "frequency": cpu_freq._asdict() if cpu_freq else {},
                "usage_per_core": psutil.cpu_percent(interval=1, percpu=True),
                "stats": cpu_stats._asdict()
            },
            "memory": {
                "virtual": memory._asdict(),
                "swap": swap._asdict(),
                "total_gb": round(memory.total / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2)
            },
            "system": {
                "boot_time": boot_time.isoformat(),
                "uptime_hours": uptime.total_seconds() / 3600,
                "users": [user._asdict() for user in psutil.users()]
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting detailed system info: {e}")
        return {"error": str(e)}

async def _get_network_info() -> Dict[str, Any]:
    """Informações de rede"""
    try:
        # Interfaces de rede
        interfaces = {}
        for name, addrs in psutil.net_if_addrs().items():
            interfaces[name] = [addr._asdict() for addr in addrs]
        
        # Estatísticas de rede
        net_io = psutil.net_io_counters()
        net_io_per_nic = psutil.net_io_counters(pernic=True)
        
        # Conexões
        connections = len(psutil.net_connections())
        
        return {
            "interfaces": interfaces,
            "io_counters": net_io._asdict(),
            "io_per_interface": {name: stats._asdict() for name, stats in net_io_per_nic.items()},
            "active_connections": connections,
            "connectivity": await _test_internet_connectivity()
        }
        
    except Exception as e:
        logger.error(f"Error getting network info: {e}")
        return {"error": str(e)}

async def _test_internet_connectivity() -> Dict[str, Any]:
    """Testa conectividade com a internet"""
    try:
        import socket
        
        test_hosts = [
            ("google.com", 80),
            ("cloudflare.com", 80),
            ("github.com", 443)
        ]
        
        results = {}
        for host, port in test_hosts:
            try:
                socket.create_connection((host, port), timeout=5)
                results[host] = {"status": "ok", "reachable": True}
            except Exception as e:
                results[host] = {"status": "failed", "reachable": False, "error": str(e)}
        
        reachable_count = len([r for r in results.values() if r["reachable"]])
        
        return {
            "overall_status": "ok" if reachable_count > 0 else "failed",
            "reachable_hosts": reachable_count,
            "total_hosts": len(test_hosts),
            "details": results
        }
        
    except Exception as e:
        return {"overall_status": "error", "error": str(e)}

async def _check_backup_tools() -> Dict[str, Dict[str, Any]]:
    """Verifica ferramentas de backup básicas"""
    tools_to_check = {
        "restic": "restic",
        "kopia": "kopia",
        "rclone": "rclone",
        "7zip": "7z" if platform.system() != "Windows" else "7z.exe",
        "zip": "zip",
        "tar": "tar"
    }
    
    results = {}
    for name, command in tools_to_check.items():
        results[name] = {
            "available": shutil.which(command) is not None,
            "path": shutil.which(command)
        }
    
    return results

async def _check_backup_tools_detailed() -> Dict[str, Dict[str, Any]]:
    """Verificação detalhada de ferramentas"""
    tools_to_check = {
        "restic": {"command": "restic", "version_arg": "version"},
        "kopia": {"command": "kopia", "version_arg": "--version"},
        "rclone": {"command": "rclone", "version_arg": "version"},
        "7zip": {"command": "7z" if platform.system() != "Windows" else "7z.exe", "version_arg": ""},
        "duplicati": {"command": "duplicati", "version_arg": "version"},
        "borgbackup": {"command": "borg", "version_arg": "--version"}
    }
    
    results = {}
    for name, info in tools_to_check.items():
        tool_path = shutil.which(info["command"])
        
        if tool_path:
            # Tentar obter versão
            try:
                if info["version_arg"]:
                    result = subprocess.run(
                        [info["command"], info["version_arg"]], 
                        capture_output=True, 
                        text=True, 
                        timeout=5
                    )
                    version = result.stdout.strip() if result.returncode == 0 else "unknown"
                else:
                    version = "available"
                
                results[name] = {
                    "available": True,
                    "path": tool_path,
                    "version": version,
                    "status": "ok"
                }
            except Exception as e:
                results[name] = {
                    "available": True,
                    "path": tool_path,
                    "version": "unknown",
                    "status": "error",
                    "error": str(e)
                }
        else:
            results[name] = {
                "available": False,
                "path": None,
                "version": None,
                "status": "not_found"
            }
    
    return results

async def _get_disk_analysis() -> Dict[str, Any]:
    """Análise detalhada de discos"""
    try:
        disk_info = {}
        
        # Informações por partição
        partitions = psutil.disk_partitions()
        for partition in partitions:
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disk_info[partition.mountpoint] = {
                    "device": partition.device,
                    "fstype": partition.fstype,
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "usage_percent": round((usage.used / usage.total) * 100, 2)
                }
            except Exception:
                disk_info[partition.mountpoint] = {"error": "Permission denied or invalid"}
        
        # IO Stats
        disk_io = psutil.disk_io_counters()
        
        return {
            "partitions": disk_info,
            "io_counters": disk_io._asdict() if disk_io else {},
            "total_space_gb": sum([p.get("total_gb", 0) for p in disk_info.values() if "total_gb" in p])
        }
        
    except Exception as e:
        return {"error": str(e)}

async def _get_process_info() -> Dict[str, Any]:
    """Informações de processos"""
    try:
        # Processos com maior uso de CPU e memória
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                processes.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Top 10 por CPU
        cpu_top = sorted(processes, key=lambda x: x['cpu_percent'] or 0, reverse=True)[:10]
        
        # Top 10 por memória
        mem_top = sorted(processes, key=lambda x: x['memory_percent'] or 0, reverse=True)[:10]
        
        return {
            "total_processes": len(processes),
            "top_cpu": cpu_top,
            "top_memory": mem_top
        }
        
    except Exception as e:
        return {"error": str(e)}

async def _get_repository_summary(core) -> Dict[str, Any]:
    """Resumo dos repositórios"""
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, COUNT(*) FROM repositories GROUP BY status")
            by_status = {}
            for row in cursor.fetchall():
                by_status[row[0]] = row[1]

            total = sum(by_status.values())
            active = by_status.get("active", 0)

            return {
                "total": total,
                "active": active,
                "inactive": by_status.get("inactive", 0),
                "error": by_status.get("error", 0),
                "health_percentage": (active / total * 100) if total > 0 else 0
            }
    except Exception as e:
        return {"error": str(e)}


async def _get_recent_error_count(core) -> int:
    """Conta erros recentes em logs/eventos."""
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*)
                FROM system_events
                WHERE LOWER(COALESCE(level, '')) IN ('error', 'critical')
                   OR LOWER(COALESCE(message, '')) LIKE '%erro%'
                   OR LOWER(COALESCE(message, '')) LIKE '%error%'
            """)
            row = cursor.fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


async def _save_diagnostic(core, result: Dict[str, Any], category: str):
    """Persistência best-effort do diagnóstico."""
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS diagnostics (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    category TEXT,
                    cpu_usage DOUBLE PRECISION,
                    memory_usage DOUBLE PRECISION,
                    disk_usage DOUBLE PRECISION,
                    system_health DOUBLE PRECISION,
                    details JSONB
                )
            """)

            system = result.get("system", {}) or {}
            cpu = system.get("cpu", 0)
            mem = system.get("memory", 0)
            disk = system.get("disk", 0)
            if isinstance(cpu, dict):
                cpu = cpu.get("usage_percent", 0)
            if isinstance(mem, dict):
                mem = mem.get("usage_percent", 0)
            if isinstance(disk, dict):
                disk = disk.get("usage_percent", 0)

            import json
            cursor.execute("""
                INSERT INTO diagnostics (category, cpu_usage, memory_usage, disk_usage, system_health, details)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """, (
                category,
                float(cpu or 0),
                float(mem or 0),
                float(disk or 0),
                float(result.get("overall_health", 0) or 0),
                json.dumps(result, default=str)
            ))
            conn.commit()
    except Exception as e:
        logger.debug(f"Falha ao salvar diagnóstico ({category}): {e}")


def _calculate_health_score(system_metrics: Dict[str, Any], backup_tools: Dict[str, Any]) -> float:
    """Health score rápido (0-100)."""
    try:
        cpu = float(system_metrics.get("cpu", {}).get("usage_percent", 0))
        mem = float(system_metrics.get("memory", {}).get("usage_percent", 0))
        disk = float(system_metrics.get("disk", {}).get("usage_percent", 0))

        system_score = max(0.0, 100.0 - ((cpu + mem + disk) / 3.0))

        total_tools = max(1, len(backup_tools))
        available = len([t for t in backup_tools.values() if t.get("available")])
        tools_score = (available / total_tools) * 100.0

        return round((system_score * 0.7) + (tools_score * 0.3), 2)
    except Exception:
        return 0.0


def _calculate_detailed_health(system_info: Dict[str, Any], backup_tools: Dict[str, Any], repo_analysis: Dict[str, Any], task_analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Health score detalhado com breakdown."""
    system_cpu = float((system_info.get("cpu", {}) or {}).get("usage_per_core", [0])[0] if (system_info.get("cpu", {}) or {}).get("usage_per_core") else 0)
    tools_total = max(1, len(backup_tools))
    tools_avail = len([t for t in backup_tools.values() if t.get("available")])
    repo_health = float(repo_analysis.get("health_percentage", 0) or 0)
    task_success = float(task_analysis.get("success_rate", 0) or 0)

    breakdown = {
        "system": max(0.0, 100.0 - system_cpu),
        "tools": (tools_avail / tools_total) * 100.0,
        "repositories": repo_health,
        "tasks": task_success
    }
    overall = round((breakdown["system"] * 0.35) + (breakdown["tools"] * 0.2) + (breakdown["repositories"] * 0.2) + (breakdown["tasks"] * 0.25), 2)
    return {"overall": overall, "breakdown": {k: round(v, 2) for k, v in breakdown.items()}}


def _get_health_status(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "warning"
    return "critical"


async def _analyze_repositories(core) -> Dict[str, Any]:
    """Análise de repositórios."""
    return await _get_repository_summary(core)


async def _analyze_tasks(core) -> Dict[str, Any]:
    """Análise de tarefas e taxa de sucesso."""
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tasks")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM tasks WHERE COALESCE(schedule_enabled, false) = true")
            scheduled = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'completed') FROM task_executions")
            runs_row = cursor.fetchone() or (0, 0)
            total_runs = int(runs_row[0] or 0)
            total_successes = int(runs_row[1] or 0)

            success_rate = (total_successes / total_runs * 100.0) if total_runs > 0 else 0.0
            return {
                "total": total,
                "scheduled": scheduled,
                "total_runs": total_runs,
                "total_successes": total_successes,
                "success_rate": round(success_rate, 2)
            }
    except Exception as e:
        return {"error": str(e), "total": 0, "scheduled": 0, "total_runs": 0, "total_successes": 0, "success_rate": 0.0}


async def _security_analysis() -> Dict[str, Any]:
    """Análise básica de segurança"""
    try:
        checks = {
            "file_permissions": await _check_file_permissions(),
            "network_security": await _check_network_security(),
            "backup_encryption": await _check_backup_encryption()
        }

        security_score = sum([1 for check in checks.values() if check.get("status") == "ok"])
        total_checks = len(checks)

        return {
            "score": round((security_score / total_checks) * 100, 1),
            "checks": checks,
            "recommendations": _get_security_recommendations(checks)
        }
    except Exception as e:
        return {"error": str(e)}


async def _check_file_permissions() -> Dict[str, Any]:
    try:
        current_dir = os.getcwd()
        return {
            "status": "ok",
            "directory": current_dir,
            "writable": os.access(current_dir, os.W_OK),
            "readable": os.access(current_dir, os.R_OK)
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _check_network_security() -> Dict[str, Any]:
    try:
        listening_ports = []
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == 'LISTEN':
                listening_ports.append(conn.laddr.port)

        return {
            "status": "ok",
            "listening_ports": sorted(set(listening_ports)),
            "port_count": len(set(listening_ports))
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _check_backup_encryption() -> Dict[str, Any]:
    """Verifica configuração de criptografia com base em dados reais de repositórios."""
    try:
        core = get_shared_core()
        repos = []
        if hasattr(core, 'repository_manager') and core.repository_manager:
            repos = core.repository_manager.list_repositories() or []

        if not repos:
            return {
                "status": "warning",
                "encryption_available": True,
                "encrypted_repositories": 0,
                "total_repositories": 0,
                "engine_breakdown": {},
                "message": "Nenhum repositório configurado"
            }

        breakdown: Dict[str, Dict[str, int]] = {}
        encrypted = 0

        for r in repos:
            engine = (r.get('engine') or 'unknown').lower()
            info = breakdown.setdefault(engine, {"total": 0, "encrypted": 0})
            info["total"] += 1

            has_password = bool((r.get('motor_password') or '').strip() or (r.get('cloud_password') or '').strip())
            is_encrypted = engine in ('restic', 'kopia', 'duplicati', 'gboc_native') and has_password
            if is_encrypted:
                info["encrypted"] += 1
                encrypted += 1

        status = "ok" if encrypted == len(repos) else ("warning" if encrypted > 0 else "error")
        return {
            "status": status,
            "encryption_available": True,
            "encrypted_repositories": encrypted,
            "total_repositories": len(repos),
            "engine_breakdown": breakdown,
            "recommended_tools": ["restic", "kopia"]
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _generate_recommendations(system_info: Dict, backup_tools: Dict, repo_analysis: Dict) -> List[str]:
    recommendations = []

    if "cpu" in system_info:
        usage_per_core = (system_info.get("cpu", {}) or {}).get("usage_per_core", [])
        if usage_per_core:
            cpu_usage = sum(usage_per_core) / max(1, len(usage_per_core))
            if cpu_usage > 80:
                recommendations.append("Alto uso de CPU detectado. Considere otimizar tarefas agendadas.")

    available_tools = [name for name, info in backup_tools.items() if info.get("available")]
    if not available_tools:
        recommendations.append("Nenhuma ferramenta de backup detectada. Instale restic ou kopia.")
    elif "restic" not in available_tools and "kopia" not in available_tools:
        recommendations.append("Considere instalar restic ou kopia para backups mais eficientes.")

    if repo_analysis.get("total", 0) == 0:
        recommendations.append("Nenhum repositório configurado. Configure ao menos um repositório de backup.")

    if not recommendations:
        recommendations.append("Sistema funcionando adequadamente. Continue monitorando regularmente.")

    return recommendations


def _get_security_recommendations(checks: Dict) -> List[str]:
    recommendations = []
    for check_name, result in checks.items():
        if result.get("status") != "ok":
            recommendations.append(f"Falha em {check_name}. Verifique a configuração deste item.")

    if not recommendations:
        recommendations.append("Nenhum problema crítico de segurança detectado nesta análise.")

    return recommendations

