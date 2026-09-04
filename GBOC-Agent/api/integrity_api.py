#!/usr/bin/env python3
"""
GBOC 14.0.0 - API de Verificação de Integridade
Executa restic check / kopia verify para validar integridade dos repositórios
"""

from fastapi import APIRouter, HTTPException
import logging
import subprocess
import os
import threading
import json
import tempfile
import re
from datetime import datetime
from typing import Dict, Any, List
from engines.engine_paths import get_engine_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/integrity", tags=["Integrity Verification"])

# Status de verificações em andamento
_running_checks: Dict[int, Dict] = {}


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


def _expand_repo_config(repo: Dict[str, Any]) -> Dict[str, Any]:
    """Expande repo.config JSON para o nível superior sem sobrescrever valores já presentes."""
    merged = dict(repo or {})
    raw_cfg = merged.get('config')
    if raw_cfg:
        try:
            cfg = json.loads(raw_cfg) if isinstance(raw_cfg, str) else raw_cfg
            if isinstance(cfg, dict):
                for k, v in cfg.items():
                    if v is not None and (k not in merged or not merged.get(k)):
                        merged[k] = v
        except Exception:
            pass
    return merged


def _get_repo_password(repo: Dict[str, Any]) -> str:
    repo_type = (repo.get('repo_type') or repo.get('type') or 'local').lower()
    if repo_type == 'local':
        return str(repo.get('motor_password') or '')
    return str(repo.get('cloud_password') or '')


def _build_kopia_connect_cmd(repo: Dict[str, Any], kopia: str, config_path: str) -> List[str]:
    repo_type = (repo.get('type') or 'local').lower()
    connect_cmd = [kopia, 'repository', 'connect', '--config-file', config_path]

    if repo_type == 'local':
        path = str(repo.get('path') or '')
        if not path:
            raise ValueError("Caminho local não configurado")
        connect_cmd.extend(['filesystem', '--path', path])
    elif repo_type == 'b2':
        bucket = str(repo.get('bucket') or repo.get('path') or '')
        key_id = str(repo.get('b2_account_id') or repo.get('access_key') or '')
        key = str(repo.get('b2_account_key') or repo.get('secret_key') or '')
        if not bucket or not key_id or not key:
            raise ValueError("Bucket/credenciais B2 incompletos")
        connect_cmd.extend(['b2', '--bucket', bucket, '--key-id', key_id, '--key', key])
    elif repo_type in ('s3', 'wasabi'):
        bucket = str(repo.get('bucket') or repo.get('path') or '')
        access_key = str(repo.get('aws_access_key') or repo.get('access_key') or '')
        secret_key = str(repo.get('aws_secret_key') or repo.get('secret_key') or '')
        region = str(repo.get('region') or 'us-east-1')
        if not bucket or not access_key or not secret_key:
            raise ValueError("Bucket/credenciais S3/Wasabi incompletos")
        connect_cmd.extend(['s3', '--bucket', bucket, '--access-key', access_key, '--secret-access-key', secret_key, '--region', region])
        endpoint = str(repo.get('endpoint') or '').strip()
        if repo_type == 'wasabi':
            endpoint = endpoint or f"s3.{region}.wasabisys.com"
        if endpoint:
            connect_cmd.extend(['--endpoint', endpoint])
        prefix = str(repo.get('prefix') or '').strip()
        if prefix:
            if not prefix.endswith('/'):
                prefix += '/'
            connect_cmd.extend(['--prefix', prefix])
    else:
        raise ValueError(f"Tipo '{repo_type}' não suportado para Kopia")

    return connect_cmd


def _build_duplicati_url(repo: Dict[str, Any]) -> str:
    repo_type = (repo.get('type') or 'local').lower()
    repo_path = str(repo.get('path') or repo.get('bucket') or '')
    prefix = str(repo.get('prefix') or '').strip('/')

    if repo_type == 'local':
        if not repo_path:
            raise ValueError("Caminho local não configurado")
        return f"file://{repo_path}"
    if repo_type == 'b2':
        if not repo_path:
            raise ValueError("Bucket B2 não configurado")
        return f"b2://{repo_path}/{prefix}" if prefix else f"b2://{repo_path}"
    if repo_type in ('s3', 'wasabi'):
        if not repo_path:
            raise ValueError("Bucket S3/Wasabi não configurado")
        return f"s3://{repo_path}/{prefix}" if prefix else f"s3://{repo_path}"
    if repo_type == 'azure':
        if not repo_path:
            raise ValueError("Container Azure não configurado")
        return f"azure://{repo_path}/{prefix}" if prefix else f"azure://{repo_path}"

    raise ValueError(f"Tipo de repositório Duplicati não suportado: {repo_type}")


def _build_duplicati_auth_args(repo: Dict[str, Any]) -> List[str]:
    repo_type = (repo.get('type') or 'local').lower()
    args: List[str] = []

    password = _get_repo_password(repo)
    if password:
        args.append(f"--passphrase={password}")

    if repo_type in ('s3', 'wasabi'):
        access_key = str(repo.get('access_key') or repo.get('aws_access_key') or '')
        secret_key = str(repo.get('secret_key') or repo.get('aws_secret_key') or '')
        endpoint = str(repo.get('endpoint') or '')
        region = str(repo.get('region') or '')

        if access_key:
            args.append(f"--aws-access-key-id={access_key}")
        if secret_key:
            args.append(f"--aws-secret-access-key={secret_key}")

        if endpoint:
            args.append(f"--s3-server-name={endpoint}")
        elif repo_type == 'wasabi' and region:
            args.append(f"--s3-server-name=s3.{region}.wasabisys.com")
        elif repo_type == 's3' and region:
            args.append(f"--s3-server-name=s3.{region}.amazonaws.com")

    elif repo_type == 'b2':
        app_id = str(repo.get('access_key') or repo.get('b2_account_id') or '')
        app_key = str(repo.get('secret_key') or repo.get('b2_account_key') or '')
        if app_id:
            args.append(f"--b2-accountid={app_id}")
        if app_key:
            args.append(f"--b2-applicationkey={app_key}")

    elif repo_type == 'azure':
        account = str(repo.get('access_key') or repo.get('azure_account_name') or '')
        key = str(repo.get('secret_key') or repo.get('azure_account_key') or '')
        if account:
            args.append(f"--azure-account-name={account}")
        if key:
            args.append(f"--azure-accesskey={key}")

    return args


def _build_preemptive_diagnostic(repo: Dict, engine: str) -> Dict:
    """Executa validações prévias para reduzir falso positivo no integrity check."""
    repo_type = (repo.get('type') or 'local').lower()
    path = repo.get('path') or ''

    engine_path = get_engine_path(engine) if engine != 'gboc_native' else None
    engine_stage = {
        "checked": True,
        "ok": True if engine == 'gboc_native' else bool(engine_path),
        "message": "Engine nativa embutida" if engine == 'gboc_native' else (f"Executável encontrado em {engine_path}" if engine_path else f"Engine '{engine}' não encontrada")
    }

    auth_ok = True
    auth_msg = "OK"
    if engine in ('restic', 'kopia', 'duplicati'):
        if repo_type == 'local':
            auth_ok = bool(repo.get('motor_password'))
            auth_msg = "motor_password configurada" if auth_ok else "motor_password não configurada"
        else:
            auth_ok = bool(repo.get('cloud_password'))
            auth_msg = "cloud_password configurada" if auth_ok else "cloud_password não configurada"

    repository_ok = bool(path)
    repository_msg = "Path/bucket configurado" if repository_ok else "Path/bucket não configurado"

    checks = {
        "engine": engine_stage,
        "repository": {"checked": True, "ok": repository_ok, "message": repository_msg},
        "auth": {"checked": engine in ('restic', 'kopia', 'duplicati'), "ok": auth_ok if engine in ('restic', 'kopia', 'duplicati') else True, "message": auth_msg if engine in ('restic', 'kopia', 'duplicati') else "N/A"}
    }

    all_ok = bool(checks['engine']['ok'] and checks['repository']['ok'] and checks['auth']['ok'])
    summary = "Pré-diagnóstico OK" if all_ok else "Pré-diagnóstico detectou inconsistências"

    return {
        "ok": all_ok,
        "summary": summary,
        "checks": checks
    }


@router.post("/check/{repository_id}")
async def start_integrity_check(repository_id: int):
    """Inicia verificação de integridade de um repositório"""
    if repository_id in _running_checks and _running_checks[repository_id].get('status') == 'running':
        return {"status": "already_running", "message": "Verificação já em andamento para este repositório"}

    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.id, r.name, r.path, r.motor_password, r.cloud_password,
                       r.type, r.config
                FROM repositories r WHERE r.id = %s
            """, (repository_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Repositório não encontrado")

            repo = {
                'id': row[0], 'name': row[1], 'path': row[2],
                'motor_password': row[3], 'cloud_password': row[4],
                'type': row[5], 'config': row[6]
            }

        # Determinar engine do repositório baseado em tarefas associadas
        engine = _detect_engine(core, repository_id)

        _running_checks[repository_id] = {
            'status': 'running',
            'started_at': datetime.now().isoformat(),
            'repository_name': repo['name'],
            'engine': engine,
            'progress': 'Iniciando verificação...'
        }

        # Executar em thread separada
        thread = threading.Thread(
            target=_run_integrity_check,
            args=(repo, engine, repository_id),
            daemon=True,
            name=f"integrity-{repository_id}"
        )
        thread.start()

        return {
            "status": "started",
            "message": f"Verificação de integridade iniciada para '{repo['name']}' ({engine})",
            "repository_id": repository_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao iniciar verificação: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check/{repository_id}/status")
async def get_integrity_check_status(repository_id: int):
    """Obtém status da verificação de integridade"""
    if repository_id in _running_checks:
        return {"status": "success", "check": _running_checks[repository_id]}
    return {"status": "success", "check": {"status": "idle", "message": "Nenhuma verificação em andamento"}}


@router.get("/history")
async def get_integrity_history():
    """Obtém histórico de verificações de integridade"""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            # Verificar se tabela existe
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'integrity_checks'
                )
            """)
            if not cursor.fetchone()[0]:
                _ensure_integrity_table(conn)

            cursor.execute("""
                SELECT ic.id, ic.repository_id, r.name as repo_name, ic.engine, ic.status,
                       ic.started_at, ic.finished_at, ic.result_summary, ic.errors_found
                FROM integrity_checks ic
                JOIN repositories r ON ic.repository_id = r.id
                ORDER BY ic.started_at DESC
                LIMIT 50
            """)

            history = []
            for row in cursor.fetchall():
                raw_status = (row[4] or '').lower()
                summary = row[7] or ''
                errors_found = row[8] or 0

                display_status = raw_status
                if raw_status in ('failed', 'error') and errors_found == 0:
                    s = summary.lower()
                    if 'íntegro' in s or 'integro' in s or 'nenhum erro' in s:
                        display_status = 'passed'
                    else:
                        display_status = 'warning'

                history.append({
                    "id": row[0],
                    "repository_id": row[1],
                    "repository_name": row[2],
                    "engine": row[3],
                    "status": raw_status,
                    "display_status": display_status,
                    "started_at": row[5].isoformat() if hasattr(row[5], 'isoformat') and row[5] else (str(row[5]) if row[5] else None),
                    "finished_at": row[6].isoformat() if hasattr(row[6], 'isoformat') and row[6] else (str(row[6]) if row[6] else None),
                    "result_summary": summary,
                    "errors_found": errors_found
                })

        return {"status": "success", "history": history}
    except Exception as e:
        logger.error(f"Erro ao obter histórico de integridade: {e}", exc_info=True)
        return {"status": "success", "history": []}


@router.get("/history/{check_id}")
async def get_integrity_history_detail(check_id: int):
    """Obtém detalhes completos de uma verificação (inclui raw_output)."""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            _ensure_integrity_table(conn)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ic.id, ic.repository_id, r.name as repo_name, ic.engine, ic.status,
                       ic.started_at, ic.finished_at, ic.result_summary, ic.errors_found, ic.raw_output
                FROM integrity_checks ic
                LEFT JOIN repositories r ON ic.repository_id = r.id
                WHERE ic.id = %s
            """, (check_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Registro de integrity check não encontrado")

            return {
                "status": "success",
                "detail": {
                    "id": row[0],
                    "repository_id": row[1],
                    "repository_name": row[2],
                    "engine": row[3],
                    "check_status": row[4],
                    "started_at": row[5].isoformat() if row[5] else None,
                    "finished_at": row[6].isoformat() if row[6] else None,
                    "result_summary": row[7],
                    "errors_found": row[8] or 0,
                    "raw_output": row[9] or ""
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao obter detalhe do histórico de integridade: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status-all")
async def get_all_checks_status():
    """Obtém status de todas as verificações em andamento"""
    return {"status": "success", "checks": _running_checks}


def _detect_engine(core, repository_id: int) -> str:
    """Detecta engine mais usado com o repositório"""
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT engine, COUNT(*) as cnt FROM tasks
                WHERE repository_id = %s
                GROUP BY engine ORDER BY cnt DESC LIMIT 1
            """, (repository_id,))
            row = cursor.fetchone()
            return row[0] if row else 'restic'
    except Exception:
        return 'restic'


def _ensure_integrity_table(conn):
    """Cria tabela de integrity_checks se não existir"""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS integrity_checks (
            id SERIAL PRIMARY KEY,
            repository_id INTEGER REFERENCES repositories(id),
            engine VARCHAR(50),
            status VARCHAR(20) DEFAULT 'running',
            started_at TIMESTAMP DEFAULT NOW(),
            finished_at TIMESTAMP,
            result_summary TEXT,
            errors_found INTEGER DEFAULT 0,
            raw_output TEXT
        )
    """)
    conn.commit()


def _run_integrity_check(repo: Dict, engine: str, repository_id: int):
    """Executa verificação de integridade em background"""
    core = _get_core()
    started_at = datetime.now()

    try:
        repo = _expand_repo_config(repo)
        preemptive = _build_preemptive_diagnostic(repo, engine)

        if engine == 'restic':
            result = _check_restic(repo)
        elif engine == 'kopia':
            result = _check_kopia(repo)
        elif engine == 'duplicati':
            result = _check_duplicati(repo)
        elif engine == 'gboc_native':
            result = _check_gboc_native(repo)
        else:
            result = {"success": False, "summary": f"Verificação não suportada para engine {engine}", "errors": 1, "output": ""}

        # se check falhou mas pré-check apontou problema de configuração, preservar causa raiz no resumo
        if not result.get('success') and not preemptive.get('ok'):
            pre_summary = preemptive.get('summary', 'Pré-diagnóstico com inconsistências')
            result['summary'] = f"{pre_summary}. {result.get('summary', '')}".strip()
            pre_json = json.dumps(preemptive.get('checks', {}), ensure_ascii=False)
            result['output'] = (f"[PREEMPTIVE]{pre_json}\n" + (result.get('output') or ''))[:5000]

        finished_at = datetime.now()
        status = 'passed' if result['success'] else 'failed'

        _running_checks[repository_id] = {
            'status': status,
            'started_at': started_at.isoformat(),
            'finished_at': finished_at.isoformat(),
            'repository_name': repo['name'],
            'engine': engine,
            'result_summary': result['summary'],
            'errors_found': result['errors'],
            'preemptive': preemptive
        }

        # Salvar no banco
        try:
            with core.get_db_connection() as conn:
                _ensure_integrity_table(conn)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO integrity_checks
                    (repository_id, engine, status, started_at, finished_at, result_summary, errors_found, raw_output)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (repository_id, engine, status, started_at, finished_at,
                      result['summary'], result['errors'], (result.get('output', '') or '')[:5000]))
                conn.commit()
        except Exception as db_err:
            logger.error(f"Erro ao salvar verificação no banco: {db_err}")

        logger.info(f"{'✅' if result['success'] else '❌'} Verificação de integridade de '{repo['name']}': {result['summary']}")

    except Exception as e:
        logger.error(f"Erro na verificação de integridade: {e}", exc_info=True)
        finished_at = datetime.now()
        _running_checks[repository_id] = {
            'status': 'error',
            'started_at': started_at.isoformat(),
            'finished_at': finished_at.isoformat(),
            'repository_name': repo['name'],
            'engine': engine,
            'result_summary': f"Erro: {str(e)}",
            'errors_found': 1
        }

        # Garantir persistência da falha no histórico
        try:
            with core.get_db_connection() as conn:
                _ensure_integrity_table(conn)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO integrity_checks
                    (repository_id, engine, status, started_at, finished_at, result_summary, errors_found, raw_output)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    repository_id, engine, 'error', started_at, finished_at,
                    f"Erro: {str(e)}", 1, str(e)[:5000]
                ))
                conn.commit()
        except Exception as db_err:
            logger.error(f"Erro ao persistir falha no histórico de integridade: {db_err}")


def _check_restic(repo: Dict) -> Dict:
    """Verifica integridade com restic check usando a mesma lógica do backup/validação."""
    from engines.engine_paths import get_engine_path_or_raise
    from engines.repository_manager import RepositoryManager

    restic = get_engine_path_or_raise('restic')

    # Reutilizar exatamente a mesma montagem de repositório/env do fluxo principal
    rm = RepositoryManager(_get_core())
    repo_arg, env, prep_error, _ = rm._build_restic_repo_and_env(repo, allow_init=False)
    if prep_error:
        return {"success": False, "summary": prep_error, "errors": 1, "output": ""}
    if not repo_arg:
        return {"success": False, "summary": "Repositório Restic não configurado corretamente", "errors": 1, "output": ""}

    cmd = [restic, 'check', '-r', repo_arg, '--json']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=7200)
        output = (result.stdout or '') + (result.stderr or '')

        if result.returncode == 0:
            return {
                "success": True,
                "summary": "Repositório íntegro — nenhum erro encontrado",
                "errors": 0,
                "output": output[:5000]
            }

        out_lower = output.lower()
        if 'wrong password' in out_lower or 'no key found' in out_lower or 'incorrect password' in out_lower:
            summary = "Falha de autenticação Restic: senha/chave do repositório inválida"
        elif 'access denied' in out_lower or 'forbidden' in out_lower or 'signaturedoesnotmatch' in out_lower:
            summary = "Falha de acesso ao storage: credenciais cloud inválidas ou sem permissão"
        elif 'no such host' in out_lower or 'timeout' in out_lower or 'connection refused' in out_lower:
            summary = "Falha de conectividade com o repositório (rede/endpoint)"
        elif 'repository does not exist' in out_lower or 'is there a repository at the following location' in out_lower:
            summary = "Repositório não encontrado no destino informado"
        else:
            error_count = out_lower.count('error')
            summary = f"Erros encontrados na verificação Restic ({max(error_count, 1)} ocorrência(s))"

        return {
            "success": False,
            "summary": summary,
            "errors": max(out_lower.count('error'), 1),
            "output": output[:5000]
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "summary": "Timeout na verificação (>2h)", "errors": 1, "output": ""}
    except Exception as e:
        return {"success": False, "summary": f"Erro: {str(e)}", "errors": 1, "output": ""}


def _check_kopia(repo: Dict) -> Dict:
    """Verifica integridade com kopia verify (com conexão explícita ao repositório)."""
    from engines.engine_paths import get_engine_path_or_raise

    kopia = get_engine_path_or_raise('kopia')
    repo = _expand_repo_config(repo)
    env = os.environ.copy()

    password = _get_repo_password(repo)
    if not password:
        return {"success": False, "summary": "Senha Kopia não configurada", "errors": 1, "output": ""}

    env["KOPIA_PASSWORD"] = password

    try:
        with tempfile.TemporaryDirectory(prefix='gboc_kopia_integrity_') as tmp:
            config_path = os.path.join(tmp, 'kopia.config')
            env['KOPIA_CONFIG_PATH'] = os.path.dirname(config_path)

            connect_cmd = _build_kopia_connect_cmd(repo, kopia, config_path)
            connect = subprocess.run(connect_cmd, capture_output=True, text=True, env=env, timeout=90)
            if connect.returncode != 0:
                conn_err = (connect.stderr or connect.stdout or 'Falha ao conectar repositório Kopia').strip()
                conn_err = re.sub(r'\x1b\[[0-9;]*m', '', conn_err)
                return {
                    "success": False,
                    "summary": "Falha de conexão Kopia: repositório não conectado",
                    "errors": 1,
                    "output": conn_err[:5000]
                }

            cmd = [kopia, 'snapshot', 'verify', '--verify-files-percent=5', '--config-file', config_path]
            result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=7200)
            output = (result.stdout or '') + (result.stderr or '')
            output = re.sub(r'\x1b\[[0-9;]*m', '', output)

            if result.returncode == 0:
                return {
                    "success": True,
                    "summary": "Repositório Kopia íntegro",
                    "errors": 0,
                    "output": output[:5000]
                }

            out_l = output.lower()
            if 'repository is not connected' in out_l:
                summary = "Repositório Kopia não conectado"
            elif 'wrong password' in out_l or 'invalid password' in out_l:
                summary = "Falha de autenticação Kopia"
            else:
                summary = "Falha na verificação Kopia"

            return {
                "success": False,
                "summary": summary,
                "errors": max(out_l.count('error'), 1),
                "output": output[:5000]
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "summary": "Timeout na verificação Kopia (>2h)", "errors": 1, "output": ""}
    except Exception as e:
        return {"success": False, "summary": f"Erro Kopia: {str(e)}", "errors": 1, "output": ""}


def _check_duplicati(repo: Dict) -> Dict:
    """Verificação leve de integridade para Duplicati via acesso ao repositório."""
    from engines.engine_paths import get_engine_path_or_raise

    try:
        dup_exe = get_engine_path_or_raise('duplicati')
        repo = _expand_repo_config(repo)
        target_url = _build_duplicati_url(repo)
        args = _build_duplicati_auth_args(repo)

        cmd = [dup_exe, 'find', target_url, *args, '--no-encryption=true']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

        if result.returncode != 0:
            cmd2 = [dup_exe, 'find', target_url, *args]
            result = subprocess.run(cmd2, capture_output=True, text=True, timeout=180)

        output = ((result.stdout or '') + (result.stderr or '')).strip()
        if result.returncode == 0:
            return {
                "success": True,
                "summary": "Acesso ao repositório Duplicati validado",
                "errors": 0,
                "output": output[:5000]
            }

        return {
            "success": False,
            "summary": "Falha na verificação Duplicati",
            "errors": 1,
            "output": (output or 'Erro desconhecido no Duplicati')[:5000]
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "summary": "Timeout na verificação Duplicati", "errors": 1, "output": ""}
    except Exception as e:
        return {"success": False, "summary": f"Erro Duplicati: {str(e)}", "errors": 1, "output": ""}


def _check_gboc_native(repo: Dict) -> Dict:
    """Verificação básica de conectividade para GBOC Native."""
    try:
        core = _get_core()
        rm = getattr(core, 'repository_manager', None)
        if not rm:
            return {"success": False, "summary": "RepositoryManager não disponível", "errors": 1, "output": ""}

        backend = rm.get_backend(int(repo.get('id') or 0))
        conn = backend.check_connection()
        if conn.get('success'):
            return {
                "success": True,
                "summary": "Repositório GBOC Native acessível",
                "errors": 0,
                "output": str(conn)[:5000]
            }
        return {
            "success": False,
            "summary": "Falha na verificação GBOC Native",
            "errors": 1,
            "output": str(conn.get('error') or conn.get('message') or conn)[:5000]
        }
    except Exception as e:
        return {"success": False, "summary": f"Erro GBOC Native: {str(e)}", "errors": 1, "output": ""}

