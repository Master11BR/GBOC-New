"""
# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# A cópia, distribuição ou modificação não autorizada é estritamente proibida.
# ==============================================================================

"""
GBOC Remote Restore Manager v13.2.0 Enterprise
Orquestração de Monitoramento e Restauração Remota de Arquivos entre Agentes na Rede.
"""

import os
import sys
import json
import logging
import httpx
from typing import Dict, Any, List, Optional

logger = logging.getLogger("GBOC.RemoteRestoreManager")

class RemoteRestoreManager:
    def __init__(self):
        self.connected_agents: Dict[str, dict] = {}

    def register_remote_agent(self, agent_id: str, ip_address: str, port: int = 9200) -> dict:
        """Registra um agente remoto na rede local para monitoramento e restore."""
        agent_info = {
            "agent_id": agent_id,
            "ip_address": ip_address,
            "port": port,
            "url": f"http://{ip_address}:{port}",
            "status": "ONLINE"
        }
        self.connected_agents[agent_id] = agent_info
        logger.info(f"🌐 Agente remoto registrado: {agent_id} em {ip_address}:{port}")
        return agent_info

    def list_remote_agents(self) -> List[dict]:
        """Lista todos os agentes remotos cadastrados na rede."""
        return list(self.connected_agents.values())

    async def get_remote_snapshots(self, agent_id: str) -> list:
        """Obtém a lista de snapshots de backup de um agente remoto."""
        agent = self.connected_agents.get(agent_id)
        if not agent:
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{agent['url']}/api/v1/backups/snapshots")
                if res.status_code == 200:
                    return res.json().get('snapshots', [])
        except Exception as e:
            logger.error(f"Erro ao buscar snapshots do agente remoto {agent_id}: {e}")
        return []

    async def trigger_remote_file_restore(self, agent_id: str, snapshot_id: str, target_files: list, destination_path: str) -> dict:
        """Dispara uma restauracao remota de arquivos em um servidor/estacao da rede."""
        agent = self.connected_agents.get(agent_id)
        if not agent:
            return {"success": False, "error": f"Agente remoto {agent_id} não encontrado"}

        try:
            payload = {
                "snapshot_id": snapshot_id,
                "files": target_files,
                "destination_path": destination_path
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(f"{agent['url']}/api/v1/restore/execute", json=payload)
                if res.status_code == 200:
                    logger.info(f"✅ Restauração remota solicitada com sucesso no agente {agent_id}!")
                    return res.json()
                return {"success": False, "error": f"HTTP {res.status_code}: {res.text}"}
        except Exception as e:
            logger.error(f"Falha ao acionar restauração remota no agente {agent_id}: {e}")
            return {"success": False, "error": str(e)}

remote_restore_manager = RemoteRestoreManager()
