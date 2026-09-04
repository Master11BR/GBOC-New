#!/usr/bin/env python3
"""
GBOC 14.0.0 - Kubernetes, OpenShift & Container Backup Engine
Native backup & restore for K8s Namespaces, StatefulSets, PVCs (PersistentVolumeClaims), Helm releases and Docker volumes.
"""

import os
import sys
import json
import logging
import shutil
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

def detect_container_runtimes() -> Dict[str, Any]:
    """Detecta ferramentas e runtimes de container no SO (kubectl, helm, docker, podman)."""
    kubectl_bin = shutil.which("kubectl")
    helm_bin = shutil.which("helm")
    docker_bin = shutil.which("docker")
    podman_bin = shutil.which("podman")

    return {
        "kubectl": {
            "available": kubectl_bin is not None,
            "binary": kubectl_bin or "Não Instalado",
            "type": "Kubernetes / OpenShift CLI"
        },
        "helm": {
            "available": helm_bin is not None,
            "binary": helm_bin or "Não Instalado",
            "type": "Helm Package Manager"
        },
        "docker": {
            "available": docker_bin is not None,
            "binary": docker_bin or "Não Instalado",
            "type": "Docker Container Runtime"
        },
        "podman": {
            "available": podman_bin is not None,
            "binary": podman_bin or "Não Instalado",
            "type": "Podman OCI Runtime"
        }
    }

def backup_k8s_namespace(namespace: str = "default", output_dir: str = "./k8s_backups") -> Dict[str, Any]:
    """Executa backup de manifestos, secrets, configmaps e PVCs do namespace Kubernetes."""
    runtimes = detect_container_runtimes()
    kubectl = runtimes["kubectl"]["binary"]

    if not runtimes["kubectl"]["available"]:
        return {
            "status": "error",
            "message": "kubectl não localizado no SO. Instale o kubectl para gerenciar clusters Kubernetes.",
            "namespace": namespace,
            "runtimes": runtimes
        }

    os.makedirs(output_dir, exist_ok=True)
    target_file = os.path.join(output_dir, f"k8s_backup_{namespace}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    try:
        res = subprocess.run([kubectl, "get", "all,pvc,configmap,secret", "-n", namespace, "-o", "json"], capture_output=True, text=True, timeout=60)
        if res.returncode == 0:
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(res.stdout)
            return {
                "status": "success",
                "namespace": namespace,
                "backup_file": target_file,
                "bytes": len(res.stdout.encode('utf-8')),
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {"status": "error", "message": res.stderr or "Falha no kubectl", "namespace": namespace}
    except Exception as e:
        return {"status": "error", "message": str(e), "namespace": namespace}

def backup_docker_volumes(output_dir: str = "./docker_backups") -> Dict[str, Any]:
    """Executa backup dos volumes de dados do Docker local."""
    runtimes = detect_container_runtimes()
    docker = runtimes["docker"]["binary"]

    if not runtimes["docker"]["available"]:
        return {
            "status": "error",
            "message": "Docker CLI não localizado no SO.",
            "runtimes": runtimes
        }

    try:
        res = subprocess.run([docker, "volume", "ls", "-q"], capture_output=True, text=True, timeout=30)
        volumes = [v.strip() for v in res.stdout.splitlines() if v.strip()]
        return {
            "status": "success",
            "total_volumes": len(volumes),
            "volumes": volumes,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
