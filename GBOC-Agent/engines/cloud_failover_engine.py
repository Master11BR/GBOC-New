# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
# Module: Multi-Cloud Direct Failover Engine (AWS EC2 & Azure VM Auto-Spinup)
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import json
import time
import shutil
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("gboc_cloud_failover")


class CloudFailoverEngine:
    """
    Motor de Failover Direto para Nuvem Pública (P2C - Physical/Virtual to Cloud).
    Zero-Mock: Valida imagens de backup reais e ferramentas CLI da AWS (aws-cli) ou Azure (az-cli).
    """

    def launch_aws_ec2_failover(
        self,
        backup_image_path: str,
        instance_type: str = "t3.xlarge",
        region: str = "us-east-1"
    ) -> Dict[str, Any]:
        logs: List[str] = [f"Iniciando procedimento de failover para AWS EC2 (Região: {region})..."]

        if not backup_image_path or not os.path.exists(backup_image_path):
            logs.append(f"❌ Imagem de backup '{backup_image_path}' não encontrada no host.")
            return {
                "success": False,
                "error": f"Imagem de backup '{backup_image_path}' inexistente.",
                "logs": logs
            }

        aws_bin = shutil.which("aws")
        if not aws_bin:
            logs.append("⚠️ Utilitário 'aws' (AWS CLI v2) não instalado no sistema operacional host.")
            logs.append("Para provisionar instâncias EC2 automaticamente, instale e autentique a AWS CLI.")
            return {
                "success": False,
                "error": "AWS CLI não instalada no host.",
                "logs": logs
            }

        ok, ident = _cli_identity([aws_bin, "sts", "get-caller-identity", "--output", "json"])
        if not ok:
            logs.append(f"❌ Credenciais da AWS CLI não funcionam: {ident}")
            return {"success": False, "error": f"Credenciais da AWS CLI inválidas ou ausentes ('aws configure'): {ident}",
                    "cloud_provider": "AWS", "region": region, "logs": logs}
        logs.append(f"✅ AWS CLI autenticada ({ident}).")
        logs.append("ℹ️ O provisionamento automático da instância (importação da imagem e criação da EC2) ainda não está implementado no GBOC.")
        return {
            "success": False,
            "implemented": False,
            "error": "Failover automático para AWS ainda não implementado (credenciais verificadas e válidas).",
            "cloud_provider": "AWS",
            "region": region,
            "logs": logs
        }

    def launch_azure_vm_failover(
        self,
        backup_image_path: str,
        vm_size: str = "Standard_D4s_v5",
        region: str = "brazilsouth"
    ) -> Dict[str, Any]:
        logs: List[str] = [f"Iniciando procedimento de failover para Microsoft Azure (Região: {region})..."]

        if not backup_image_path or not os.path.exists(backup_image_path):
            logs.append(f"❌ Imagem de backup '{backup_image_path}' não encontrada no host.")
            return {
                "success": False,
                "error": f"Imagem de backup '{backup_image_path}' inexistente.",
                "logs": logs
            }

        az_bin = shutil.which("az")
        if not az_bin:
            logs.append("⚠️ Utilitário 'az' (Azure CLI) não instalado no sistema operacional host.")
            logs.append("Para provisionar Máquinas Virtuais Azure automaticamente, instale e autentique a Azure CLI.")
            return {
                "success": False,
                "error": "Azure CLI não instalada no host.",
                "logs": logs
            }

        ok, ident = _cli_identity([az_bin, "account", "show", "--output", "json"])
        if not ok:
            logs.append(f"❌ Azure CLI não autenticada: {ident}")
            return {"success": False, "error": f"Azure CLI não autenticada ('az login'): {ident}",
                    "cloud_provider": "Azure", "region": region, "logs": logs}
        logs.append(f"✅ Azure CLI autenticada ({ident}).")
        logs.append("ℹ️ O provisionamento automático da VM (upload do VHD e criação da VM) ainda não está implementado no GBOC.")
        return {
            "success": False,
            "implemented": False,
            "error": "Failover automático para Azure ainda não implementado (credenciais verificadas e válidas).",
            "cloud_provider": "Azure",
            "region": region,
            "logs": logs
        }


def _cli_identity(cmd):
    """Executa o comando de identidade da CLI de nuvem; retorna (ok, conta_ou_erro)."""
    import json as _json, subprocess as _sp
    try:
        r = _sp.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except Exception as e:
        return False, str(e)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or f"código {r.returncode}").strip()[:300]
    try:
        d = _json.loads(r.stdout or "{}")
        return True, d.get("Arn") or d.get("user", {}).get("name") or d.get("name") or "conta ativa"
    except ValueError:
        return True, "conta ativa"


# Singleton global
cloud_failover_engine = CloudFailoverEngine()
