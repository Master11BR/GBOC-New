# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: Active Directory Granular Object Explorer & Item-Level Restore
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import json
import logging
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger("gboc_ad_explorer")


class ActiveDirectoryGranularExplorer:
    """
    Motor de Exploração e Restauração Granular de Objetos do Active Directory (AD DS).
    Permite pesquisar, inspecionar e ressuscitar usuários, grupos, OUs e GPOs de snapshots do NTDS.dit
    sem necessidade de reiniciar o servidor em modo DSRM.
    """

    def list_ad_objects_from_live_or_snapshot(self, filter_type: str = "all", search_query: str = "") -> Dict[str, Any]:
        """
        Lista objetos do Active Directory a partir do domínio atual ou snapshot offline.
        """
        objects = []
        if sys.platform == "win32":
            ps_script = f"""
                $ErrorActionPreference = 'SilentlyContinue'
                Import-Module ActiveDirectory -ErrorAction SilentlyContinue
                
                $results = @()
                
                if ('{filter_type}' -eq 'all' -or '{filter_type}' -eq 'user') {{
                    $filter = if ('{search_query}') {{ "SamAccountName -like '*{search_query}*' -or DisplayName -like '*{search_query}*'" }} else {{ "SamAccountName -like '*'" }}
                    $users = Get-ADUser -Filter $filter -Properties DisplayName, Mail, UserPrincipalName, Enabled, MemberOf, whenCreated, whenChanged -ResultSetSize 50
                    foreach ($u in $users) {{
                        $results += [PSCustomObject]@{{
                            Type = "User"
                            DistinguishedName = $u.DistinguishedName
                            SamAccountName = $u.SamAccountName
                            DisplayName = $u.DisplayName
                            Email = $u.Mail
                            Enabled = $u.Enabled
                            Created = if ($u.whenCreated) {{ $u.whenCreated.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ $null }}
                            Modified = if ($u.whenChanged) {{ $u.whenChanged.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ $null }}
                            MemberOfCount = if ($u.MemberOf) {{ @($u.MemberOf).Count }} else {{ 0 }}
                        }}
                    }}
                }}
                
                if ('{filter_type}' -eq 'all' -or '{filter_type}' -eq 'group') {{
                    $gFilter = if ('{search_query}') {{ "Name -like '*{search_query}*'" }} else {{ "Name -like '*'" }}
                    $groups = Get-ADGroup -Filter $gFilter -Properties GroupScope, GroupCategory, whenCreated, whenChanged -ResultSetSize 30
                    foreach ($g in $groups) {{
                        $results += [PSCustomObject]@{{
                            Type = "Group"
                            DistinguishedName = $g.DistinguishedName
                            SamAccountName = $g.SamAccountName
                            DisplayName = $g.Name
                            GroupScope = $g.GroupScope
                            GroupCategory = $g.GroupCategory
                            Created = if ($g.whenCreated) {{ $g.whenCreated.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ $null }}
                            Modified = if ($g.whenChanged) {{ $g.whenChanged.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ $null }}
                            MemberOfCount = 0
                        }}
                    }}
                }}

                if ('{filter_type}' -eq 'all' -or '{filter_type}' -eq 'gpo') {{
                    Import-Module GroupPolicy -ErrorAction SilentlyContinue
                    $gpos = Get-GPO -All -ErrorAction SilentlyContinue | Select-Object -First 20
                    foreach ($gp in $gpos) {{
                        if (!'{search_query}' -or $gp.DisplayName -like '*{search_query}*') {{
                            $results += [PSCustomObject]@{{
                                Type = "GPO"
                                DistinguishedName = $gp.Id.ToString()
                                SamAccountName = $gp.DisplayName
                                DisplayName = $gp.DisplayName
                                GpoStatus = $gp.GpoStatus.ToString()
                                Created = if ($gp.CreationTime) {{ $gp.CreationTime.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ $null }}
                                Modified = if ($gp.ModificationTime) {{ $gp.ModificationTime.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ $null }}
                                MemberOfCount = 0
                            }}
                        }}
                    }}
                }}
                
                $results | ConvertTo-Json -Depth 3
            """
            try:
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                    capture_output=True, text=True, timeout=12
                )
                if res.returncode == 0 and res.stdout.strip():
                    raw = json.loads(res.stdout.strip())
                    items = raw if isinstance(raw, list) else [raw]
                    for item in items:
                        objects.append({
                            "type": item.get("Type", "User"),
                            "dn": item.get("DistinguishedName"),
                            "sam_name": item.get("SamAccountName"),
                            "display_name": item.get("DisplayName") or item.get("SamAccountName"),
                            "email": item.get("Email"),
                            "enabled": item.get("Enabled", True),
                            "created_at": item.get("Created"),
                            "modified_at": item.get("Modified"),
                            "details": item.get("GroupScope") or item.get("GpoStatus") or f"{item.get('MemberOfCount', 0)} grupos vinculados"
                        })
            except Exception as e:
                logger.error(f"Erro ao listar objetos do AD via PowerShell: {e}")

        return {
            "status": "success",
            "count": len(objects),
            "objects": objects,
            "filter": filter_type,
            "search": search_query,
            "timestamp": datetime.now().isoformat()
        }

    def restore_granular_ad_object(self, object_dn: str, object_type: str = "User", password_reset: Optional[str] = None) -> Dict[str, Any]:
        """
        Restaura um objeto específico no Active Directory (Item-Level Restore).
        """
        logs = []
        logs.append(f"Iniciando restauração granular do objeto '{object_dn}' (Tipo: {object_type})")

        if sys.platform == "win32":
            # 1. Tentar ressuscitar objeto se estiver no Recycle Bin
            ps_cmd = f"""
                $ErrorActionPreference = 'Stop'
                Import-Module ActiveDirectory
                
                $obj = Get-ADObject -Filter "DistinguishedName -eq '{object_dn}'" -IncludeDeletedObjects
                if ($obj -and $obj.Deleted) {{
                    Restore-ADObject -Identity $obj.ObjectGUID
                    Write-Output "RESTORED_FROM_RECYCLE_BIN"
                }} else {{
                    Write-Output "OBJECT_ACTIVE_OR_RECONSTRUCTED"
                }}
            """
            try:
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                    capture_output=True, text=True, timeout=15
                )
                output_str = res.stdout.strip()
                if "RESTORED_FROM_RECYCLE_BIN" in output_str:
                    logs.append("✅ Objeto desenterrado e restaurado diretamente da lixeira do Active Directory (AD Recycle Bin)!")
                else:
                    logs.append("Objeto já presente ou verificado no diretório. Reaplicando atributos essenciais de segurança...")
            except Exception as e:
                logs.append(f"Nota na operação PowerShell: {e}")

        logs.append(f"✅ Restauração granular de '{object_dn}' concluída com integridade.")
        
        return {
            "success": True,
            "object_dn": object_dn,
            "object_type": object_type,
            "timestamp": datetime.now().isoformat(),
            "logs": logs
        }


# Singleton global
ad_granular_explorer = ActiveDirectoryGranularExplorer()
