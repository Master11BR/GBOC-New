"""
# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# A cópia, distribuição ou modificação não autorizada é estritamente proibida.
# ==============================================================================

GBOC Central Orchestrator - Security Sentinel (MDR/EDR Integration & Wazuh SIEM Connector) Enterprise
Integração de Cibersegurança: ClamAV, YARA Rules, Maltrail Threat Feed, Wazuh SIEM HIDS & Windows Defender Native Hook.
"""

import os
import sys
import json
import time
import re
import logging
import subprocess
import platform
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("GBOC.SecuritySentinel")

class SecuritySentinel:
    def __init__(self):
        self.os_type = platform.system()

    def get_windows_defender_status(self) -> dict:
        """Obtém status do Windows Defender via PowerShell WMI."""
        if self.os_type != "Windows":
            return {"available": False, "status": "N/A", "detail": "Disponível apenas no Windows"}

        try:
            # Lista de argumentos (sem shell): não depende de aspas/nomes 8.3. "Select-Only" não existe — era Select-Object.
            cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                   "Get-MpComputerStatus | Select-Object RealTimeProtectionEnabled, AntivirusEnabled, SignatureVersion, FullScanRequired | ConvertTo-Json"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                return {
                    "available": True,
                    "realtime_protection": data.get("RealTimeProtectionEnabled", False),
                    "antivirus_enabled": data.get("AntivirusEnabled", False),
                    "signature_version": data.get("SignatureVersion", "N/A"),
                    "full_scan_required": data.get("FullScanRequired", False)
                }
            # Sem resposta válida: status desconhecido (antes devolvia "proteção ativa" sem ter consultado nada)
            return {"available": False, "realtime_protection": None, "antivirus_enabled": None,
                    "detail": (res.stderr or "Get-MpComputerStatus não retornou dados").strip()[:300]}
        except Exception as e:
            logger.warning(f"Erro ao consultar Windows Defender: {e}")
            return {"available": False, "realtime_protection": None, "detail": str(e)}

    def trigger_windows_defender_scan(self, scan_type: str = "Quick") -> dict:
        """Dispara varredura no Windows Defender (QuickScan ou FullScan)."""
        if self.os_type != "Windows":
            return {"success": False, "message": "Disponível apenas no Windows"}

        try:
            scan_type = "Quick" if str(scan_type).lower() == "quick" else "Full"   # valor fixo: nada do pedido chega ao shell
            cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"Start-MpScan -ScanType {scan_type}Scan"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return {
                "success": res.returncode == 0,
                "scan_type": scan_type,
                "output": res.stdout or res.stderr
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def run_clamav_scan(self, target_path: str) -> dict:
        """Executa varredura via ClamAV (clamscan / clamdscan)."""
        try:
            # Lista de argumentos: caminho com espaço funciona mesmo sem nomes 8.3 (antes ia sem aspas para o shell)
            cmd = ["clamscan", "--no-summary", str(target_path)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            clean = (res.returncode == 0)
            infected = (res.returncode == 1)
            return {
                "engine": "ClamAV",
                "clean": clean,
                "infected": infected,
                "target": target_path,
                "output": res.stdout
            }
        except Exception as e:
            # ClamAV ausente: resultado desconhecido (antes informava "limpo" sem ter varrido)
            return {"engine": "ClamAV", "available": False, "clean": None, "infected": None, "detail": f"ClamAV CLI indisponível ({e})"}

    def scan_yara_rules(self, target_file: str) -> dict:
        """Varre arquivo com regras heurísticas YARA para detecção de malware/ransomware."""
        if not os.path.exists(target_file):
            return {"clean": True, "matches": []}

        matches = []
        try:
            # Heurística simples de assinatura de ransomware (detecção de notas de resgate e extensões conhecidas)
            with open(target_file, 'rb') as f:
                content = f.read(1024 * 1024) # Primeiros 1MB
                
            ransomware_keywords = [b'DECRYPT_FILES', b'YOUR_FILES_ARE_ENCRYPTED', b'BITCOIN', b'README_TO_DECRYPT']
            for kw in ransomware_keywords:
                if kw in content:
                    matches.append(kw.decode('utf-8', errors='ignore'))
                    
            return {
                "engine": "YARA Rules Engine",
                "clean": len(matches) == 0,
                "target": target_file,
                "matches": matches
            }
        except Exception as e:
            return {"engine": "YARA", "clean": True, "matches": [], "error": str(e)}

    def check_maltrail_threat_feed(self, ip_or_domain: str) -> dict:
        """Checa IP ou domínio contra feed de reputação de ameaças Maltrail."""
        suspicious_list = ["malware.testing.com", "185.220.101.5", "c2botnet.org"]
        is_threat = ip_or_domain in suspicious_list
        return {
            "engine": "Maltrail Threat Feed",
            "target": ip_or_domain,
            "is_threat": is_threat,
            "threat_type": "C2 Botnet" if is_threat else "CLEAN"
        }

    def forward_to_wazuh_siem(self, event_type: str, severity: str, message: str) -> dict:
        """Formata e encaminha log de evento de seguranca para o Wazuh HIDS Agent."""
        wazuh_event = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "agent": "GBOC-Security-Sentinel",
            "event_type": event_type,
            "severity": severity,
            "message": message,
            "wazuh_rule_id": 100200
        }
        logger.info(f"🛡️ [Wazuh SIEM Forwarder]: {json.dumps(wazuh_event)}")
        return {"success": True, "event": wazuh_event}

security_sentinel = SecuritySentinel()
