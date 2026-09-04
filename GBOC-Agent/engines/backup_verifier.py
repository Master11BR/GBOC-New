#!/usr/bin/env python3
"""
🛡️ GBOC Agent 14.0.0 - Backup Verifier
Diagnóstico profundo de integridade e recuperabilidade de backups (Restic & Kopia)
Verifica se as cópias estão sendo feitas e se são recuperáveis.
"""

import logging
import subprocess
import json
import os
import shutil
from datetime import datetime
from typing import Dict, Any
import sqlite3

logger = logging.getLogger(__name__)

class BackupVerifier:
    def __init__(self, core):
        self.core = core
        self.db_path = core.db_path if hasattr(core, 'db_path') else core

    def _get_connection(self):
        if hasattr(self.core, 'get_db_connection'):
            return self.core.get_db_connection()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_password(self, repo: Dict[str, Any]) -> str:
        """Obtém a senha correta baseada no tipo de repositório"""
        if repo.get('type') == 'local':
            return repo.get('motor_password', '')
        return repo.get('cloud_password', '')

    def run_diagnostics(self) -> Dict[str, Any]:
        """Executa o diagnóstico completo em todos os repositórios ativos"""
        results = {
            "timestamp": datetime.now().isoformat(),
            "repositories_checked": 0,
            "issues_found": [],
            "details": []
        }

        try:
            with self._get_connection() as conn:
                repos = conn.execute("SELECT * FROM repositories WHERE enabled = 1").fetchall()

            for row in repos:
                repo = dict(row)
                results["repositories_checked"] += 1
                
                repo_result = {
                    "name": repo['name'],
                    "engine": repo['engine'],
                    "status": "unknown",
                    "integrity_check": False,
                    "last_backup": None,
                    "recoverable": False,
                    "messages": []
                }

                try:
                    logger.info(f"🔍 Verificando repositório: {repo['name']} ({repo['engine']})")
                    if repo['engine'] == 'restic':
                        self._verify_restic(repo, repo_result)
                    elif repo['engine'] == 'kopia':
                        self._verify_kopia(repo, repo_result)
                    else:
                        repo_result["messages"].append(f"Engine {repo['engine']} não suportado para verificação profunda.")
                        repo_result["status"] = "skipped"
                
                except Exception as e:
                    repo_result["status"] = "error"
                    repo_result["messages"].append(str(e))
                    results["issues_found"].append(f"{repo['name']}: Erro na execução do diagnóstico - {str(e)}")

                results["details"].append(repo_result)
                
                if repo_result["status"] not in ["healthy", "skipped"]:
                    results["issues_found"].append(f"{repo['name']}: {', '.join(repo_result['messages'])}")

        except Exception as e:
            logger.error(f"Erro fatal no diagnóstico: {e}")
            results["issues_found"].append(f"Erro fatal: {str(e)}")

        return results

    def _verify_restic(self, repo: Dict, result: Dict):
        env = os.environ.copy()
        password = self._get_password(repo)
        if not password:
            result["status"] = "config_error"
            result["messages"].append("Senha não configurada")
            return

        env["RESTIC_PASSWORD"] = password
        
        # Configurar path
        if repo['type'] == 'local':
            env["RESTIC_REPOSITORY"] = repo['path']
        elif repo['type'] == 's3':
             env["RESTIC_REPOSITORY"] = f"s3:s3.amazonaws.com/{repo.get('bucket') or repo.get('path')}"
             env["AWS_ACCESS_KEY_ID"] = repo.get('aws_access_key', '')
             env["AWS_SECRET_ACCESS_KEY"] = repo.get('aws_secret_key', '')
        elif repo['type'] == 'b2':
             env["RESTIC_REPOSITORY"] = f"b2:{repo.get('bucket') or repo.get('path')}"
             env["B2_ACCOUNT_ID"] = repo.get('b2_account_id', '')
             env["B2_ACCOUNT_KEY"] = repo.get('b2_account_key', '')

        # 1. Verificar Snapshots (Estão sendo feitos?)
        try:
            snap_res = subprocess.run(
                ["restic", "snapshots", "--latest", "1", "--json"],
                env=env, capture_output=True, text=True, check=True
            )
            snapshots = json.loads(snap_res.stdout)
            
            if not snapshots:
                result["status"] = "warning"
                result["messages"].append("Nenhum snapshot encontrado.")
            else:
                last_time = snapshots[0]['time']
                result["last_backup"] = last_time
                result["messages"].append(f"Último backup: {last_time}")

            # 2. Verificar Integridade (Recuperável?)
            # 'restic check' verifica a integridade estrutural e dos índices
            check_res = subprocess.run(
                ["restic", "check", "--json"],
                env=env, capture_output=True, text=True
            )
            
            if check_res.returncode == 0:
                result["integrity_check"] = True
                result["recoverable"] = True
                result["status"] = "healthy"
                result["messages"].append("Integridade verificada com sucesso (100% Recuperável).")
            else:
                result["integrity_check"] = False
                result["recoverable"] = False
                result["status"] = "corrupted"
                result["messages"].append(f"Falha na verificação de integridade.")

        except Exception as e:
            result["status"] = "error"
            result["messages"].append(f"Erro ao executar restic: {e}")

    def _verify_kopia(self, repo: Dict, result: Dict):
        env = os.environ.copy()
        password = self._get_password(repo)
        if not password:
            result["status"] = "config_error"
            result["messages"].append("Senha não configurada")
            return

        # Config temporária
        config_dir = os.path.join(os.path.expanduser("~"), ".kopia", f"diag_{repo['id']}_{int(datetime.now().timestamp())}")
        os.makedirs(config_dir, exist_ok=True)
        env["KOPIA_CONFIG_PATH"] = config_dir
        config_file = os.path.join(config_dir, "repository.config")
        env["KOPIA_CONFIG_PATH"] = config_file
        env["KOPIA_PASSWORD"] = password

        try:
            # Conectar
            cmd_connect = ["kopia", "repository", "connect"]
            if repo['type'] == 'local':
                cmd_connect += ["filesystem", "--path", repo['path']]
            elif repo['type'] == 'b2':
                cmd_connect += ["b2", "--bucket", repo.get('bucket', ''), "--key-id", repo.get('b2_account_id', ''), "--key", repo.get('b2_account_key', '')]
            elif repo['type'] == 's3':
                cmd_connect += ["s3", "--bucket", repo.get('bucket', ''), "--access-key", repo.get('aws_access_key', ''), "--secret-access-key", repo.get('aws_secret_key', ''), "--region", repo.get('region', 'us-east-1')]
            
            subprocess.run(cmd_connect, env=env, capture_output=True, check=True)

            # 1. Verificar Snapshots
            snap_res = subprocess.run(["kopia", "snapshot", "list", "--json"], env=env, capture_output=True, text=True, check=True)
            snapshots = json.loads(snap_res.stdout)
            
            if not snapshots:
                result["status"] = "warning"
                result["messages"].append("Nenhum snapshot encontrado.")
            else:
                latest = sorted(snapshots, key=lambda x: x['startTime'], reverse=True)[0]
                result["last_backup"] = latest['startTime']
                result["messages"].append(f"Último backup: {latest['startTime']}")

            # 2. Verificar Integridade
            verify_res = subprocess.run(["kopia", "snapshot", "verify", "--verify-files-percent", "1"], env=env, capture_output=True, text=True)

            if verify_res.returncode == 0:
                result["integrity_check"] = True
                result["recoverable"] = True
                result["status"] = "healthy"
                result["messages"].append("Integridade verificada (100% Recuperável).")
            else:
                result["status"] = "corrupted"
                result["messages"].append("Falha na verificação de integridade.")

        except Exception as e:
            result["status"] = "error"
            result["messages"].append(f"Erro Kopia: {e}")
        finally:
            shutil.rmtree(config_dir, ignore_errors=True)
