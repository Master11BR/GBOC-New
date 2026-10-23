# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
# Module: Active Directory Granular Object Explorer & Item-Level Restore
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import re
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
        # Entradas vao para dentro do script PowerShell: whitelist (evita injecao de comandos no DC)
        filter_type = filter_type if filter_type in ("all", "user", "group", "gpo") else "all"
        search_query = re.sub(r"[^\w\s.@-]", "", search_query or "", flags=re.UNICODE)[:64]
        if sys.platform == "win32":
            ps_script = f"""
                $ErrorActionPreference = 'SilentlyContinue'
                if (-not (Get-Module -ListAvailable ActiveDirectory)) {{ Write-Output 'GBOC_NO_AD_MODULE'; exit 3 }}
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
                if "GBOC_NO_AD_MODULE" in (res.stdout or ""):
                    return {"status": "error", "message": "Módulo PowerShell ActiveDirectory (RSAT AD) não está disponível neste servidor.",
                            "count": 0, "objects": [], "filter": filter_type, "search": search_query,
                            "timestamp": datetime.now().isoformat()}
                if res.returncode != 0:
                    return {"status": "error", "message": f"Consulta ao AD falhou (código {res.returncode}): {(res.stderr or '').strip()[:300]}",
                            "count": 0, "objects": [], "filter": filter_type, "search": search_query,
                            "timestamp": datetime.now().isoformat()}
                if res.stdout.strip():
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
        Restaura um objeto EXCLUIDO do Active Directory a partir da Lixeira do AD (Restore-ADObject).
        Objetos ativos nao sao alterados. O DN e a senha vao por variavel de ambiente (sem injecao no script).
        """
        logs = [f"Iniciando restauração granular do objeto '{object_dn}' (Tipo: {object_type})"]
        base = {"object_dn": object_dn, "object_type": object_type, "timestamp": datetime.now().isoformat()}
        if sys.platform != "win32":
            return {**base, "success": False, "restored": False, "error": "Disponível apenas no Windows.", "logs": logs}

        ps_cmd = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory
$dn = $env:GBOC_AD_DN
$out = [ordered]@{ result = 'NOT_FOUND' }
$live = $null
try { $live = Get-ADObject -Identity $dn } catch { $live = $null }
if ($live) {
    $out.result = 'ALREADY_ACTIVE'; $out.guid = $live.ObjectGUID.ToString()
} else {
    $parts = $dn -split '(?<!\\),', 2
    $rdn = ($parts[0] -replace '^[^=]+=', '') -replace '\\(.)', '$1'
    $parent = if ($parts.Count -gt 1) { $parts[1] } else { '' }
    $del = Get-ADObject -Filter 'isDeleted -eq $true' -IncludeDeletedObjects -Properties 'msDS-LastKnownRDN','LastKnownParent','whenChanged' |
           Where-Object { $_.'msDS-LastKnownRDN' -eq $rdn -and $_.LastKnownParent -eq $parent } |
           Sort-Object whenChanged -Descending | Select-Object -First 1
    if ($del) {
        Restore-ADObject -Identity $del.ObjectGUID
        $out.result = 'RESTORED'; $out.guid = $del.ObjectGUID.ToString()
    }
}
if ($env:GBOC_AD_PWD -and $out.result -eq 'RESTORED' -and $env:GBOC_AD_TYPE -eq 'User') {
    try {
        Set-ADAccountPassword -Identity $out.guid -Reset -NewPassword (ConvertTo-SecureString $env:GBOC_AD_PWD -AsPlainText -Force)
        $out.password_reset = 'OK'
    } catch { $out.password_reset = $_.Exception.Message }
}
$out | ConvertTo-Json -Compress
"""
        env = dict(os.environ, GBOC_AD_DN=object_dn or "", GBOC_AD_TYPE=object_type or "", GBOC_AD_PWD=password_reset or "")
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, env=env
            )
        except Exception as e:
            logs.append(f"❌ Erro ao executar o PowerShell: {e}")
            return {**base, "success": False, "restored": False, "error": str(e), "logs": logs}

        data = {}
        for line in reversed((res.stdout or "").splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                except ValueError:
                    pass
                break
        result = data.get("result")
        if res.returncode != 0 or not result:
            err = (res.stderr or res.stdout or "").strip()[:400] or f"código {res.returncode}"
            logs.append(f"❌ Restauração falhou: {err}")
            return {**base, "success": False, "restored": False, "error": err, "logs": logs}

        if result == "RESTORED":
            logs.append("✅ Objeto restaurado da Lixeira do Active Directory (Restore-ADObject).")
            pr = data.get("password_reset")
            if pr == "OK":
                logs.append("✅ Senha redefinida.")
            elif pr:
                logs.append(f"⚠️ Objeto restaurado, mas a redefinição de senha falhou: {pr}")
            return {**base, "success": True, "restored": True, "object_guid": data.get("guid"), "logs": logs}
        if result == "ALREADY_ACTIVE":
            msg = "O objeto está ativo no AD; nada foi restaurado (a restauração granular recupera objetos excluídos da Lixeira do AD)."
        else:
            msg = "Objeto não encontrado na Lixeira do AD (a Lixeira pode estar desativada ou o objeto já expirou)."
        logs.append(f"ℹ️ {msg}")
        return {**base, "success": False, "restored": False, "error": msg, "logs": logs}


# Singleton global
ad_granular_explorer = ActiveDirectoryGranularExplorer()
