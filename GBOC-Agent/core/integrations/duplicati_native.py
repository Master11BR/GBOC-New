#!/usr/bin/env python3
"""
Integração nativa inicial com Duplicati (módulo isolado).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from engines.engine_paths import get_engine_path

logger = logging.getLogger("DuplicatiNative")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "duplicati_native_config.json")

def _other_profile_duplicati_dbs(already: List[str]) -> List[str]:
    """Bancos do Duplicati de OUTROS perfis do Windows, do mais recente para o mais antigo.
    Como serviço (LocalSystem), %LOCALAPPDATA% aponta para o perfil do sistema e o Duplicati do usuário
    (ou o Duplicati rodando como serviço) não era encontrado: a importação voltava vazia."""
    if os.name != "nt":
        return []
    import glob
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    users_root = os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "Users")
    patterns = [
        os.path.join(users_root, "*", "AppData", "Local", "Duplicati", "Duplicati-server.sqlite"),
        os.path.join(users_root, "*", "AppData", "Roaming", "Duplicati", "Duplicati-server.sqlite"),
        os.path.join(sysroot, "System32", "config", "systemprofile", "AppData", "Local", "Duplicati", "Duplicati-server.sqlite"),
        os.path.join(sysroot, "System32", "config", "systemprofile", "AppData", "Roaming", "Duplicati", "Duplicati-server.sqlite"),
    ]
    seen = {os.path.normcase(os.path.abspath(p)) for p in already if p}
    found = []
    for pat in patterns:
        for f in glob.glob(pat):
            key = os.path.normcase(os.path.abspath(f))
            if key in seen:
                continue
            seen.add(key)
            try:
                found.append((os.path.getmtime(f), f))
            except OSError:
                continue
    return [f for _, f in sorted(found, reverse=True)]


@dataclass
class DuplicatiConfig:
    base_url: str = "http://localhost:8200"
    username: str = ""
    password: str = ""
    verify_tls: bool = False
    timeout_seconds: int = 8


def parse_duplicati_target_and_creds(target_url: str, passphrase: str = "", settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from urllib.parse import urlparse, parse_qs
    import re
    settings = settings or {}
    passphrase = (passphrase or "").strip()
    if passphrase.startswith("enc-v1:"):
        passphrase = ""

    target_url = str(target_url or "").strip()
    if target_url.startswith("enc-v1:"):
        clean_path = target_url
        endpoint = ""
        bucket = ""
        prefix = ""
        access_key = ""
        secret_key = ""
        repo_type = "cloud"
    else:
        u = urlparse(target_url)
        qs = parse_qs(u.query)
        bucket = u.netloc or ""
        prefix = u.path.strip("/") if u.path else ""
        endpoint = qs.get("s3-server-name", [""])[0]
        access_key = qs.get("auth-username", [""])[0]
        secret_key = qs.get("auth-password", [""])[0]
        if secret_key == "***************":
            secret_key = ""

        is_cloud = any(p in target_url.lower() for p in ["s3:", "wasabi", "b2:", "azure", "sftp:"]) or bool(endpoint)
        target_lower = (target_url + " " + endpoint).lower()
        if "wasabi" in target_lower:
            repo_type = "wasabi"
        elif "b2" in target_lower or "backblaze" in target_lower:
            repo_type = "b2"
        elif "azure" in target_lower:
            repo_type = "azure"
        elif is_cloud:
            repo_type = "s3"
        else:
            repo_type = "local"

        if is_cloud:
            clean_path = f"s3://{bucket}/{prefix}" if prefix else f"s3://{bucket}"
        else:
            clean_path = target_url[7:] if target_url.startswith("file://") else target_url
            if clean_path.startswith("/") and len(clean_path) > 2 and clean_path[2] == ":":
                clean_path = clean_path[1:]
            clean_path = os.path.normpath(clean_path)

    region = ""
    if endpoint:
        m = re.search(r"s3[.-]([a-z0-9-]+)\.(?:wasabisys|amazonaws)\.com", endpoint, re.IGNORECASE)
        if m:
            region = m.group(1)
        elif qs.get("s3-location-constraint"):
            region = qs.get("s3-location-constraint")[0]

    enc_mod = settings.get("encryption-module") or settings.get("--encryption-module") or "aes"
    comp_mod = settings.get("compression-module") or settings.get("--compression-module") or "zip"
    dblock = settings.get("dblock-size") or settings.get("--dblock-size") or "50MB"

    config = {
        "bucket": bucket,
        "prefix": prefix,
        "endpoint": endpoint,
        "region": region,
        "access_key": access_key,
        "secret_key": secret_key,
        "aws_access_key": access_key,
        "aws_secret_key": secret_key,
        "b2_account_id": access_key,
        "b2_account_key": secret_key,
        "azure_account_name": access_key,
        "azure_account_key": secret_key,
        "passphrase": passphrase,
        "encryption_module": enc_mod,
        "compression_module": comp_mod,
        "dblock_size": dblock
    }

    return {
        "repo_type": repo_type,
        "clean_path": clean_path,
        "config": config,
        "password": passphrase,
        "motor_password": passphrase,
        "encryption_password": passphrase,
        "cloud_password": secret_key
    }


def convert_duplicati_repeat_to_cron(repeat: str, time_str: str = "") -> str:
    import re
    repeat = (repeat or "").strip().lower()
    time_str = (time_str or "").strip()

    minute = "0"
    hour = "2"
    if time_str:
        m = re.search(r"T(\d{2}):(\d{2})", time_str)
        if m:
            hour = str(int(m.group(1)))
            minute = str(int(m.group(2)))

    if not repeat or repeat == "manual":
        return f"{minute} {hour} * * *"

    m_h = re.match(r"^(\d+)\s*h", repeat)
    if m_h:
        h = int(m_h.group(1))
        if h <= 1:
            return f"{minute} * * * *"
        return f"{minute} */{h} * * *"

    m_m = re.match(r"^(\d+)\s*m(?:in)?$", repeat)
    if m_m:
        m_val = int(m_m.group(1))
        return f"*/{m_val} * * * *" if m_val > 1 else "* * * * *"

    m_d = re.match(r"^(\d+)\s*d", repeat)
    if m_d:
        d = int(m_d.group(1))
        if d <= 1:
            return f"{minute} {hour} * * *"
        return f"{minute} {hour} */{d} * *"

    m_w = re.match(r"^(\d+)\s*w", repeat)
    if m_w:
        return f"{minute} {hour} * * 0"

    return "0 */2 * * *"


def normalize_sources_list(sources_list: Any) -> List[str]:
    if not sources_list:
        return ["C:\\"] if sys.platform == "win32" else ["/"]
    if isinstance(sources_list, str):
        try:
            sources_list = json.loads(sources_list)
        except Exception:
            sources_list = [sources_list]
    if not isinstance(sources_list, list):
        sources_list = [str(sources_list)]

    clean = []
    seen = set()
    for s in sources_list:
        if not s:
            continue
        s_str = str(s).strip()
        if sys.platform == "win32":
            if len(s_str) == 3 and s_str[1] == ':' and s_str[2] in ('\\', '/'):
                norm = s_str[:2].upper() + '\\'
            elif len(s_str) == 2 and s_str[1] == ':':
                norm = s_str.upper() + '\\'
            else:
                norm = os.path.normpath(s_str)
        else:
            norm = os.path.normpath(s_str)
        norm_key = norm.lower() if sys.platform == "win32" else norm
        if norm_key not in seen:
            seen.add(norm_key)
            clean.append(norm)
    return clean or (["C:\\"] if sys.platform == "win32" else ["/"])


def parse_duplicati_retention(settings: Optional[Dict[str, Any]] = None) -> int:
    import re
    if not settings:
        return 30
    kt = str(settings.get("keep-time") or settings.get("--keep-time") or "").strip().lower()
    if kt:
        m = re.match(r"^(\d+)\s*([dmy])", kt)
        if m:
            val = int(m.group(1))
            unit = m.group(2)
            if unit == 'd':
                return val
            if unit == 'm':
                return val * 30
            if unit == 'y':
                return val * 365
    kv = str(settings.get("keep-versions") or settings.get("--keep-versions") or "").strip()
    if kv.isdigit() and int(kv) > 0:
        return max(30, int(kv))
    return 30


_DUP_UNIT_DAYS = {"s": 1 / 86400, "m": 1 / 1440, "h": 1 / 24, "D": 1, "W": 7, "M": 30, "Y": 365}


def _dup_dt(value: Any):
    """Converte datas do Duplicati ('20261022T230014Z', '2026-10-22T23:00:14Z', '2026-10-22 23:00:14') em datetime UTC."""
    import re as _re
    from datetime import datetime as _dt
    digits = _re.sub(r"\D", "", str(value or ""))[:14]
    if len(digits) < 14:
        return None
    try:
        return _dt.strptime(digits, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def dup_last_status(meta: Dict[str, Any], fallback: Optional[str] = None) -> str:
    """
    Status real da ultima execucao. O Duplicati mantem LastErrorDate para sempre;
    so e 'Erro' se o erro for MAIS RECENTE que o ultimo backup concluido.
    """
    meta = meta or {}
    err = _dup_dt(meta.get("LastErrorDate"))
    ok = _dup_dt(meta.get("LastBackupFinished")) or _dup_dt(meta.get("LastBackupDate"))
    if err and (not ok or err > ok):
        return "Erro"
    if meta.get("LastBackupResult"):
        return str(meta["LastBackupResult"])
    if ok:
        return "OK"
    return fallback or "Pendente"


def _dup_span_days(txt: str) -> Optional[float]:
    """Intervalo do Duplicati ("1W", "12M", "1Y1D", "0s", "U") em dias. "U" (ilimitado) = 100 anos."""
    import re
    txt = (txt or "").strip()
    if txt.upper() == "U":
        return 36500.0
    parts = re.findall(r"(\d+)\s*([smhDWMY])", txt)
    if not parts:
        return None
    return sum(int(n) * _DUP_UNIT_DAYS[u] for n, u in parts)


def map_duplicati_retention(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Retenção do job original do Duplicati -> campos do GBOC (dias, semanais, mensais, anuais).
    Antes só "dias" era importado (keep-versions virava dias) e semanal/mensal/anual ficavam no padrão do banco
    (4/6/1): um job que GUARDAVA TUDO no Duplicati passava a ter versões apagadas pelo GBOC.
      * retention-policy "JANELA:INTERVALO,..." (inclui a "inteligente" 1W:1D,4W:1W,12M:1M) -> buckets equivalentes
        (intervalo <= 3 dias -> dias; <= 15 -> semanas; <= 180 -> meses; maior -> anos), sempre arredondando para MAIS
      * keep-time -> só dias
      * keep-versions (o GBOC não tem "manter as N últimas") e sem retenção -> retenção do GBOC DESLIGADA
        (nada é apagado; mais seguro que apagar o que o original mantinha)"""
    import math
    settings = settings or {}
    out = {"days": 0, "weekly": 0, "monthly": 0, "yearly": 0, "source": "nenhuma (guarda todas as versões)"}
    get = lambda k: str(settings.get(k) or settings.get("--" + k) or "").strip()
    pol = get("retention-policy")
    if pol:
        for part in pol.split(","):
            if ":" not in part:
                continue
            tf, iv = (x.strip() for x in part.split(":", 1))
            tf_d, iv_d = _dup_span_days(tf), _dup_span_days(iv)
            if tf_d is None or iv_d is None:
                continue
            if iv_d <= 3:
                out["days"] = max(out["days"], math.ceil(tf_d))
            elif iv_d <= 15:
                out["weekly"] = max(out["weekly"], math.ceil(tf_d / 7))
            elif iv_d <= 180:
                out["monthly"] = max(out["monthly"], math.ceil(tf_d / 30))
            else:
                out["yearly"] = max(out["yearly"], math.ceil(tf_d / 365))
        out["source"] = f"retention-policy {pol}"
        return out
    kt = get("keep-time")
    if kt:
        d = _dup_span_days(kt)
        if d:
            out["days"] = math.ceil(d)
            out["source"] = f"keep-time {kt}"
        return out
    kv = get("keep-versions")
    if kv:
        out["source"] = f"keep-versions {kv} (sem equivalente no GBOC: retenção desligada, nada é apagado)"
    return out


class DuplicatiNativeService:
    def __init__(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        self._session = requests.Session()
        self._xsrf_token: Optional[str] = None
        self._authenticated: bool = False

    # ──────────────────────────────────────────────
    # Config
    # ──────────────────────────────────────────────

    def load_config(self) -> DuplicatiConfig:
        if not os.path.exists(CONFIG_FILE):
            return DuplicatiConfig()
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return DuplicatiConfig(
                base_url=str(raw.get("base_url", "http://localhost:8200")).rstrip("/"),
                username=str(raw.get("username", "")),
                password=str(raw.get("password", "")),
                verify_tls=bool(raw.get("verify_tls", False)),
                timeout_seconds=int(raw.get("timeout_seconds", 8)),
            )
        except Exception as e:
            logger.warning(f"Falha ao carregar config do Duplicati: {e}")
            return DuplicatiConfig()

    def _load_extra(self) -> Dict[str, Any]:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {k: raw[k] for k in ("password_managed", "password_set_at", "server_datafolder") if k in raw}
        except Exception:
            return {}

    def save_config(self, payload: Dict[str, Any]) -> DuplicatiConfig:
        current = self.load_config()
        next_cfg = DuplicatiConfig(
            base_url=str(payload.get("base_url", current.base_url)).rstrip("/"),
            username=str(payload.get("username", current.username)),
            password=str(payload.get("password", current.password)),
            verify_tls=bool(payload.get("verify_tls", current.verify_tls)),
            timeout_seconds=max(2, int(payload.get("timeout_seconds", current.timeout_seconds))),
        )
        extra = self._load_extra()
        if "password" in payload and str(payload.get("password")) != current.password:
            # senha trocada: gerenciada pelo GBOC só se veio do próprio GBOC
            extra["password_managed"] = bool(payload.get("password_managed", False))
            extra["password_set_at"] = str(payload.get("password_set_at", ""))
        if "server_datafolder" in payload:
            extra["server_datafolder"] = str(payload.get("server_datafolder") or "")
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "base_url": next_cfg.base_url,
                "username": next_cfg.username,
                "password": next_cfg.password,
                "verify_tls": next_cfg.verify_tls,
                "timeout_seconds": next_cfg.timeout_seconds,
                **extra,
            }, f, ensure_ascii=False, indent=2)
        # Invalidar sessão ao salvar nova config
        self._authenticated = False
        self._xsrf_token = None
        self._session = requests.Session()
        return next_cfg

    # ──────────────────────────────────────────────
    # ServerUtil (CLI do Duplicati) e senha definida pelo GBOC
    # ──────────────────────────────────────────────

    SERVERUTIL_SETTINGS = os.path.join(DATA_DIR, "duplicati_serverutil.json")   # sessão do ServerUtil (dentro do Agente)

    def find_serverutil(self) -> Optional[str]:
        """Duplicati.CommandLine.ServerUtil(.exe): instalação padrão, perfil do usuário, pasta do motor do GBOC
        (Tools\\Duplicati, onde o instalador do GBOC coloca o Duplicati) ou PATH."""
        import glob
        import shutil
        names = ["Duplicati.CommandLine.ServerUtil.exe", "duplicati-server-util", "duplicati-serverutil"]
        cands = [
            r"C:\Program Files\Duplicati 2\Duplicati.CommandLine.ServerUtil.exe",
            r"C:\Program Files (x86)\Duplicati 2\Duplicati.CommandLine.ServerUtil.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Duplicati 2\Duplicati.CommandLine.ServerUtil.exe"),
        ]
        try:
            eng = get_engine_path("duplicati")
            if eng:
                d = os.path.dirname(eng)
                cands += [os.path.join(d, n) for n in names]
        except Exception:
            pass
        for root in (r"C:\GBOC\Tools\Duplicati", os.path.join(os.path.dirname(BASE_DIR), "Tools", "Duplicati")):
            cands += glob.glob(os.path.join(root, "**", "Duplicati.CommandLine.ServerUtil.exe"), recursive=True)
        if os.name == "nt":
            cands += glob.glob(os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "Users", "*", "AppData", "Local",
                                            "Programs", "Duplicati 2", "Duplicati.CommandLine.ServerUtil.exe"))
        cands += [shutil.which(n) or "" for n in names]
        cands.append("/usr/lib/duplicati/Duplicati.CommandLine.ServerUtil.exe")
        return next((c for c in cands if c and os.path.isfile(c)), None)

    def server_datafolders(self) -> List[str]:
        """Pastas de dados do Duplicati Server encontradas (a do perfil deste processo primeiro).
        Como serviço (LocalSystem) o ServerUtil procuraria no perfil do sistema; o Duplicati do usuário
        só é alcançado informando --server-datafolder."""
        own = [
            os.path.expandvars(r"%LOCALAPPDATA%\Duplicati\Duplicati-server.sqlite"),
            os.path.expandvars(r"%APPDATA%\Duplicati\Duplicati-server.sqlite"),
            r"C:\ProgramData\Duplicati\Duplicati-server.sqlite",
        ]
        out: List[str] = []
        for db in [p for p in own if os.path.isfile(p)] + _other_profile_duplicati_dbs(own):
            d = os.path.dirname(db)
            if d not in out:
                out.append(d)
        return out

    def run_serverutil(self, args: List[str], datafolder: Optional[str] = None, password: Optional[str] = None,
                       timeout: int = 45) -> Dict[str, Any]:
        """Executa o ServerUtil. Sem senha ele entra pelo banco local do Duplicati (precisa de acesso à pasta de dados)."""
        import subprocess
        exe = self.find_serverutil()
        if not exe:
            return {"ok": False, "error": "Duplicati.CommandLine.ServerUtil não encontrado"}
        cfg = self.load_config()
        cmd = [exe] + list(args) + ["--hosturl", cfg.base_url.rstrip("/") + "/", "--settings-file", self.SERVERUTIL_SETTINGS]
        if datafolder:
            cmd += ["--server-datafolder", datafolder]
        if password:
            cmd += ["--password", password]
        try:
            # stdin fechado: sem acesso ao banco o ServerUtil pediria a senha no teclado e travaria o Agente
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                                  encoding="utf-8", errors="replace")
            out = (proc.stdout or "") + (proc.stderr or "")
            return {"ok": proc.returncode == 0, "code": proc.returncode, "output": out}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _running_as_system() -> bool:
        if os.name != "nt":
            return False
        import getpass
        u = (getpass.getuser() or "").upper()
        return u.endswith("$") or u in ("SYSTEM", "SISTEMA")

    def _change_password_in_owner_session(self, new_pwd: str, datafolder: Optional[str] = None) -> bool:
        """Agente como serviço (SYSTEM) e Duplicati rodando no perfil do usuário: o banco do Duplicati é
        criptografado com uma chave DO USUÁRIO, então o ServerUtil como SYSTEM não entra. A troca de senha
        roda numa tarefa agendada de uso único na sessão do dono do processo do Duplicati (logon interativo,
        sem senha do Windows) e a tarefa é apagada em seguida."""
        import subprocess
        exe = self.find_serverutil()
        if not exe:
            return False
        cfg = self.load_config()
        ps = r"""
$ErrorActionPreference = 'Stop'
$owners = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^Duplicati\.(GUI\.TrayIcon|Server)\.exe$' } |
    ForEach-Object { $o = Invoke-CimMethod -InputObject $_ -MethodName GetOwner; if ($o.User) { "$($o.Domain)\$($o.User)" } } |
    Where-Object { $_ -and $_ -notmatch '\\(SYSTEM|SISTEMA|LOCAL SERVICE|NETWORK SERVICE)$' } | Select-Object -Unique)
if ($owners.Count -eq 0) { 'NO_OWNER'; exit 3 }
$su = $env:GBOC_SU; $url = $env:GBOC_URL; $pw = $env:GBOC_PW -replace "'", "''"
$df = if ($env:GBOC_DF) { " --server-datafolder '" + ($env:GBOC_DF -replace "'", "''") + "'" } else { "" }
foreach ($owner in $owners) {
    $name = 'GBOC_DuplicatiSenha_' + [guid]::NewGuid().ToString('N')
    $cmd = "`$f = Join-Path `$env:TEMP ('gboc_su_' + [guid]::NewGuid().ToString('N') + '.json'); " +
           "& '$su' change-password '$pw' --hosturl '$url'$df --settings-file `$f; `$c = `$LASTEXITCODE; " +
           "Remove-Item `$f -ErrorAction SilentlyContinue; exit `$c"
    $act = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$cmd`""
    $pri = New-ScheduledTaskPrincipal -UserId $owner -LogonType Interactive -RunLevel Limited
    $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
    try {
        Register-ScheduledTask -TaskName $name -Action $act -Principal $pri -Settings $set -Force | Out-Null
        Start-ScheduledTask -TaskName $name
        $res = $null
        for ($i = 0; $i -lt 90; $i++) {
            Start-Sleep -Seconds 1
            $t = Get-ScheduledTask -TaskName $name
            if ($t.State -ne 'Running' -and $i -ge 2) { $res = (Get-ScheduledTaskInfo -TaskName $name).LastTaskResult; break }
        }
    } finally {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    }
    if ($res -eq 0) { "OK $owner"; exit 0 }
    "FAIL $owner $res"
}
exit 4
"""
        try:
            env = dict(os.environ, GBOC_SU=exe, GBOC_URL=cfg.base_url.rstrip("/") + "/", GBOC_PW=new_pwd,
                       GBOC_DF=datafolder or "")
            r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                               text=True, timeout=150, stdin=subprocess.DEVNULL, env=env, encoding="utf-8", errors="replace")
            out = (r.stdout or "").strip()
            if r.returncode == 0:
                logger.info(f"🔐 Duplicati: senha do GBOC aplicada na sessão do usuário dono do Duplicati ({out[3:]})")
                return True
            logger.warning(f"Duplicati: troca de senha na sessão do usuário não concluída ({out or r.stderr.strip()[-300:]})")
        except Exception as e:
            logger.warning(f"Duplicati: troca de senha na sessão do usuário falhou: {e}")
        return False

    def ensure_managed_password(self) -> bool:
        """Sem senha do Duplicati informada no GBOC: o GBOC define uma senha forte no Duplicati Server
        (ServerUtil change-password, entrando pelo banco local) e passa a usá-la. Senha informada pelo
        usuário nunca é substituída."""
        import secrets
        from datetime import datetime
        cfg = self.load_config()
        if cfg.password:
            return False
        if getattr(self, "_managed_attempted", False):
            return False
        self._managed_attempted = True
        new_pwd = secrets.token_urlsafe(24)
        folders = self.server_datafolders() or [None]
        last = ""
        for folder in folders:
            r = self.run_serverutil(["change-password", new_pwd], datafolder=folder)
            if r.get("ok"):
                self.save_config({"password": new_pwd, "password_managed": True,
                                  "password_set_at": datetime.now().isoformat(timespec="seconds"),
                                  "server_datafolder": folder or ""})
                logger.info(f"🔐 Duplicati: senha definida pelo GBOC aplicada no servidor ({folder or 'pasta padrão'}); "
                            f"guardada em {CONFIG_FILE}")
                return True
            last = (r.get("error") or r.get("output") or "").strip().splitlines()[-1:] or [""]
            last = last[0]
        if self._running_as_system() and any(self._change_password_in_owner_session(new_pwd, f)
                                             for f in ([f for f in folders if f] or [None])):
            self.save_config({"password": new_pwd, "password_managed": True,
                              "password_set_at": datetime.now().isoformat(timespec="seconds"),
                              "server_datafolder": ""})
            return True
        logger.warning(f"Duplicati: não foi possível definir a senha do GBOC no servidor ({last})")
        return False

    # ──────────────────────────────────────────────
    # Autenticação por sessão + XSRF (Duplicati v2.x)
    # ──────────────────────────────────────────────

    def _login(self, cfg: DuplicatiConfig) -> bool:
        """
        Realiza login na API do Duplicati.
        Suporta dois fluxos:
          - v2.3+ (Kestrel/JWT): POST /api/v1/auth/login → {"AccessToken": "<jwt>"}
          - v2.x legado: GET / → xsrf-token → POST /login.cgi
        Sem senha configurada, tenta acesso direto (Duplicati sem senha).
        """
        try:
            # ── 1. Tentar ler XSRF token da página inicial ──────────────────────
            home = self._session.get(
                cfg.base_url + "/",
                timeout=cfg.timeout_seconds,
                verify=cfg.verify_tls,
                allow_redirects=True,
            )
            xsrf = (
                home.cookies.get("xsrf-token")
                or home.cookies.get("XSRF-TOKEN")
                or home.headers.get("X-XSRF-Token", "")
            )
            if xsrf:
                self._xsrf_token = xsrf
                self._session.headers.update({"X-XSRF-Token": xsrf})

            if cfg.password:
                self._session.headers.update({"X-Duplicati-Password": cfg.password})

            # ── 2. Fluxo v2.3+: JWT via /api/v1/auth/login ──────────────────────
            login_url_jwt = cfg.base_url + "/api/v1/auth/login"
            resp_jwt = self._session.post(
                login_url_jwt,
                json={"Password": cfg.password, "password": cfg.password},
                timeout=cfg.timeout_seconds,
                verify=cfg.verify_tls,
            )
            if resp_jwt.status_code == 200:
                try:
                    token = resp_jwt.json().get("AccessToken", "")
                    if token:
                        self._session.headers.update({"Authorization": f"Bearer {token}"})
                        self._xsrf_token = token
                        self._authenticated = True
                        logger.info("✅ Autenticado no Duplicati v2.3+ via JWT")
                        return True
                except Exception:
                    pass

            # ── 3. Fluxo v2.x legado: POST /login.cgi ou /api/v1/login ──────────────
            if cfg.password:
                for login_path in ["/login.cgi", "/api/v1/login"]:
                    login_url = cfg.base_url + login_path
                    resp = self._session.post(
                        login_url,
                        data={"Password": cfg.password, "password": cfg.password},
                        headers={"X-XSRF-Token": self._xsrf_token or ""},
                        timeout=cfg.timeout_seconds,
                        verify=cfg.verify_tls,
                    )
                    if resp.status_code in (200, 302, 303):
                        new_xsrf = (
                            resp.cookies.get("xsrf-token")
                            or resp.cookies.get("XSRF-TOKEN")
                            or resp.headers.get("X-XSRF-Token", "")
                        )
                        if new_xsrf:
                            self._xsrf_token = new_xsrf
                            self._session.headers.update({"X-XSRF-Token": new_xsrf})
                        self._authenticated = True
                        logger.info(f"✅ Autenticado no Duplicati via {login_path}")
                        return True

            # Se a checagem básica no /api/v1/serverstate passar, a conexão está OK
            chk = self._session.get(f"{cfg.base_url}/api/v1/serverstate", timeout=cfg.timeout_seconds, verify=cfg.verify_tls, params={"password": cfg.password} if cfg.password else None)
            if chk.status_code == 200:
                self._authenticated = True
                logger.info("✅ Conexão Duplicati estabelecida com sucesso")
                return True

            if not cfg.password and self.ensure_managed_password():
                self._session = requests.Session()
                self._xsrf_token = None
                return self._login(self.load_config())

            logger.warning("Falha no login Duplicati com as credenciais fornecidas.")
            return False

        except Exception as e:
            logger.warning(f"Erro no login Duplicati: {e}")
            return False

    def _ensure_authenticated(self, cfg: DuplicatiConfig) -> bool:
        """Garante que a sessão está autenticada; refaz login se necessário."""
        if self._authenticated:
            return True
        return self._login(cfg)

    def _api_get(self, cfg: DuplicatiConfig, path: str) -> requests.Response:
        """GET autenticado com retry de login se receber 401/403."""
        self._ensure_authenticated(cfg)
        url = f"{cfg.base_url}/{path.lstrip('/')}"
        resp = self._session.get(
            url,
            timeout=cfg.timeout_seconds,
            verify=cfg.verify_tls,
        )
        if resp.status_code in (401, 403):
            # Sessão expirada — refaz login
            self._authenticated = False
            self._xsrf_token = None
            if self._login(cfg):
                resp = self._session.get(url, timeout=cfg.timeout_seconds, verify=cfg.verify_tls)
        return resp

    def _api_put(self, cfg: DuplicatiConfig, path: str, json_body: Any = None) -> requests.Response:
        """PUT autenticado com retry de login se receber 401/403."""
        self._ensure_authenticated(cfg)
        url = f"{cfg.base_url}/{path.lstrip('/')}"
        headers = {"X-XSRF-Token": self._xsrf_token or ""}
        resp = self._session.put(
            url,
            json=json_body,
            headers=headers,
            timeout=cfg.timeout_seconds,
            verify=cfg.verify_tls,
        )
        if resp.status_code in (401, 403):
            self._authenticated = False
            self._xsrf_token = None
            if self._login(cfg):
                headers = {"X-XSRF-Token": self._xsrf_token or ""}
                resp = self._session.put(url, json=json_body, headers=headers,
                                         timeout=cfg.timeout_seconds, verify=cfg.verify_tls)
        return resp

    def _api_post(self, cfg: DuplicatiConfig, path: str, json_body: Any = None, data: Any = None) -> requests.Response:
        """POST autenticado com retry de login se receber 401/403."""
        self._ensure_authenticated(cfg)
        url = f"{cfg.base_url}/{path.lstrip('/')}"
        headers = {"X-XSRF-Token": self._xsrf_token or ""}
        resp = self._session.post(
            url,
            json=json_body,
            data=data,
            headers=headers,
            timeout=cfg.timeout_seconds,
            verify=cfg.verify_tls,
        )
        if resp.status_code in (401, 403):
            self._authenticated = False
            self._xsrf_token = None
            if self._login(cfg):
                headers = {"X-XSRF-Token": self._xsrf_token or ""}
                resp = self._session.post(url, json=json_body, data=data, headers=headers,
                                          timeout=cfg.timeout_seconds, verify=cfg.verify_tls)
        return resp

    # ──────────────────────────────────────────────
    # Métodos públicos existentes (interface preservada)
    # ──────────────────────────────────────────────

    def _build_url(self, cfg: DuplicatiConfig, path: str) -> str:
        return f"{cfg.base_url}/{path.lstrip('/')}"

    def _mask(self, value: str) -> str:
        if not value:
            return ""
        if len(value) <= 2:
            return "*" * len(value)
        return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"

    def get_config_summary(self) -> Dict[str, Any]:
        cfg = self.load_config()
        return {
            "base_url": cfg.base_url,
            "username": cfg.username,
            "password_masked": self._mask(cfg.password),
            "verify_tls": cfg.verify_tls,
            "timeout_seconds": cfg.timeout_seconds,
            "config_file": CONFIG_FILE,
            "authenticated": self._authenticated,
            "password_managed_by_gboc": bool(self._load_extra().get("password_managed")),
            "password_set_at": self._load_extra().get("password_set_at", ""),
        }

    def detect_local_installation(self) -> Dict[str, Any]:
        path = get_engine_path("duplicati")
        return {
            "detected": bool(path),
            "path": path,
        }

    def discover_endpoints(self) -> List[str]:
        cfg = self.load_config()
        candidates = list(dict.fromkeys([
            cfg.base_url.rstrip("/"),
            "http://localhost:8200",
            "http://127.0.0.1:8200",
        ]))
        found: List[str] = []
        for base in candidates:
            try:
                response = self._session.get(f"{base}/", timeout=0.5)
                if response.status_code < 500:
                    found.append(base)
            except Exception:
                continue
        return found

    def probe(self) -> Dict[str, Any]:
        cfg = self.load_config()

        # 1. Testar conectividade HTTP básica no servidor Duplicati
        server_reachable = False
        try:
            r = self._session.get(f"{cfg.base_url}/", timeout=min(cfg.timeout_seconds, 2.0), verify=cfg.verify_tls)
            if r.status_code < 500:
                server_reachable = True
        except Exception:
            pass

        probe_paths = [
            "api/v1/serverstate",
            "api/v1/systeminfo",
            "api/v1/backups",
        ]
        results = []
        ok = False
        auth_required = False

        for path in probe_paths:
            try:
                resp = self._api_get(cfg, path)
                status = resp.status_code
                results.append({"url": self._build_url(cfg, path), "status": status})
                if status == 200:
                    ok = True
                elif status == 401:
                    auth_required = True
            except Exception as e:
                results.append({"url": self._build_url(cfg, path), "status": "error", "error": str(e)})

        install = self.detect_local_installation()
        if ok:
            status_msg = "✅ Conectado e autenticado no Duplicati!"
        elif server_reachable or auth_required:
            status_msg = "🟢 Instância do Duplicati detectada e rodando! (Configure a senha de acesso web se exigida)."
        else:
            status_msg = "❌ Servidor Duplicati não foi localizado no endereço especificado."

        # Otimização de latência: se já conectou, não precisa varrer portas alternativas
        discovered = [cfg.base_url] if (ok or server_reachable or auth_required) else self.discover_endpoints()

        return {
            "ok": ok or server_reachable or auth_required,
            "message": status_msg,
            "base_url": cfg.base_url,
            "authenticated": self._authenticated,
            "auth_required": auth_required,
            "installation": install,
            "probes": results,
            "discovered": discovered,
        }

    def _read_duplicati_server_db(self) -> List[Dict[str, Any]]:
        """Lê os backups e todas as métricas detalhadas do arquivo SQLite local do Duplicati."""
        import sqlite3
        db_paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\Duplicati\Duplicati-server.sqlite"),
            os.path.expandvars(r"%APPDATA%\Duplicati\Duplicati-server.sqlite"),
            r"C:\ProgramData\Duplicati\Duplicati-server.sqlite",
            "/var/lib/duplicati/Duplicati-server.sqlite",
            os.path.expanduser("~/.config/Duplicati/Duplicati-server.sqlite"),
        ]
        db_paths += _other_profile_duplicati_dbs(db_paths)

        def fix_iso_date(raw_val: Any) -> Optional[str]:
            if not raw_val:
                return None
            s = str(raw_val).strip()
            if len(s) == 16 and s[8] == 'T' and s[15] == 'Z':
                return f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}Z"
            return s

        for path in db_paths:
            if os.path.isfile(path):
                try:
                    conn = sqlite3.connect(path)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute("SELECT ID, Name, Description, TargetURL FROM Backup")
                    rows = cur.fetchall()
                    backups = []

                    for row in rows:
                        b_id = str(row["ID"])
                        name = row["Name"] or f"Backup #{b_id}"
                        desc = row["Description"] or ""
                        target_url = str(row["TargetURL"] or "")

                        dest_label = "Destino Remoto"
                        if "wasabi" in target_url.lower():
                            dest_label = "Wasabi S3"
                        elif "s3.amazonaws" in target_url.lower():
                            dest_label = "Amazon S3"
                        elif "b2" in target_url.lower():
                            dest_label = "Backblaze B2"
                        elif "azure" in target_url.lower():
                            dest_label = "Azure Blob"
                        elif "file://" in target_url.lower() or ":" in target_url:
                            dest_label = "Disco Local / Pasta"

                        metadata = {}
                        try:
                            cur.execute("SELECT Name, Value FROM Metadata WHERE BackupID = ?", (b_id,))
                            for m in cur.fetchall():
                                metadata[m["Name"]] = m["Value"]
                        except Exception:
                            pass

                        schedule_info = {}
                        try:
                            cur.execute("SELECT Time, Repeat, LastRun FROM Schedule WHERE Tags LIKE ?", (f"%ID={b_id}%",))
                            sch = cur.fetchone()
                            if sch:
                                schedule_info = {
                                    "repeat": sch["Repeat"] or "Manual",
                                    "next_run_ts": sch["Time"],
                                    "last_run_ts": sch["LastRun"]
                                }
                        except Exception:
                            pass

                        # Buscar caminhos de origem na tabela Source
                        sources = []
                        try:
                            cur.execute("SELECT Path FROM Source WHERE BackupID = ?", (b_id,))
                            sources = [s["Path"] for s in cur.fetchall()]
                        except Exception:
                            try:
                                cur.execute("SELECT Path FROM Sources WHERE BackupID = ?", (b_id,))
                                sources = [s["Path"] for s in cur.fetchall()]
                            except Exception:
                                pass

                        # Buscar opções na tabela Option (passphrase, encryption-module, etc)
                        options_dict = {}
                        passphrase = ""
                        try:
                            cur.execute("SELECT Name, Value FROM Option WHERE BackupID = ?", (b_id,))
                            for opt in cur.fetchall():
                                opt_name = (opt["Name"] or "").lstrip("-")
                                opt_val = opt["Value"]
                                if opt_name and opt_val is not None:
                                    options_dict[opt_name] = opt_val
                            raw_pass = options_dict.get("passphrase") or ""
                            if raw_pass and not raw_pass.startswith("enc-v1:"):
                                passphrase = raw_pass
                            elif desc and not desc.startswith("enc-v1:"):
                                passphrase = desc
                        except Exception:
                            if desc and not desc.startswith("enc-v1:"):
                                passphrase = desc

                        last_backup_date = fix_iso_date(metadata.get("LastBackupDate"))
                        last_result = dup_last_status(metadata, "OK")
                        source_size = metadata.get("SourceFilesSize", "0")
                        target_size = metadata.get("TargetFilesSize", "0")
                        versions_count = metadata.get("BackupListCount", "0")
                        duration = metadata.get("LastBackupDuration", "")

                        metadata["LastBackupDate"] = last_backup_date
                        metadata["LastBackupStarted"] = fix_iso_date(metadata.get("LastBackupStarted"))
                        metadata["LastBackupFinished"] = fix_iso_date(metadata.get("LastBackupFinished"))
                        metadata["TargetURL"] = target_url

                        backups.append({
                            "id": b_id,
                            "name": name,
                            "description": desc,
                            "target_url": target_url,
                            "target_label": dest_label,
                            "passphrase": passphrase,
                            "sources": sources,
                            "settings": options_dict,
                            "last_run": last_backup_date,
                            "last_status": last_result,
                            "source_size": source_size,
                            "target_size": target_size,
                            "versions_count": versions_count,
                            "duration": duration,
                            "schedule": schedule_info,
                            "source": "sqlite_database",
                            "Backup": {
                                "ID": b_id,
                                "Name": name,
                                "Description": desc,
                                "TargetURL": target_url,
                                "Sources": sources,
                                "Metadata": metadata
                            }
                        })
                    conn.close()
                    if backups:
                        logger.info(f"✅ {len(backups)} backup(s) enriquecido(s) do SQLite do Duplicati ({path})")
                        return backups
                except Exception as e:
                    logger.warning(f"Erro ao ler banco do Duplicati em {path}: {e}")

        return []

    def extract_all_duplicati_backups_detailed(self) -> List[Dict[str, Any]]:
        """
        Extrai todos os backups do Duplicati com decifragem nativa de credenciais via ServerUtil.exe
        ou com fallback avançado via SQLite (com Sources e Options) e HTTP API.
        """
        import subprocess
        import tempfile
        import shutil
        from pathlib import Path

        serverutil_path = self.find_serverutil()

        backups: List[Dict[str, Any]] = []

        if serverutil_path:
            tmp_dir = tempfile.mkdtemp(prefix="gboc_dup_exp_")
            try:
                cfg_x = self.load_config()
                folders = ([self._load_extra().get("server_datafolder")] if self._load_extra().get("server_datafolder") else []) \
                    + self.server_datafolders()
                folders = [f for i, f in enumerate(folders) if f and f not in folders[:i]] or [None]
                proc = None
                for folder in folders:
                    r = self.run_serverutil(["export", "all", "--unencrypted", "--export-passwords", "--destination", tmp_dir,
                                             "--overwrite", "--json"], datafolder=folder, password=cfg_x.password or None)
                    if not r.get("ok") and cfg_x.password:
                        # senha do GBOC desatualizada: entra pelo banco local
                        r = self.run_serverutil(["export", "all", "--unencrypted", "--export-passwords", "--destination",
                                                 tmp_dir, "--overwrite", "--json"], datafolder=folder)
                    if r.get("ok") and any(Path(tmp_dir).glob("*.json")):
                        proc = r
                        break
                    if not r.get("ok"):
                        logger.warning(f"ServerUtil export ({folder or 'pasta padrão'}): "
                                       f"{(r.get('error') or r.get('output') or '').strip()[-300:]}")
                if proc:
                    for json_file in Path(tmp_dir).glob("*.json"):
                        try:
                            with open(json_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            b = data.get("Backup", {})
                            s = data.get("Schedule", {})
                            settings_list = b.get("Settings", [])
                            settings_dict = {}
                            for item in settings_list:
                                n = (item.get("Name") or "").lstrip("-")
                                v = item.get("Value")
                                if n and v is not None:
                                    settings_dict[n] = v

                            passphrase = settings_dict.get("passphrase") or b.get("Description") or ""
                            sources = b.get("Sources") or []

                            dest_label = "Destino Remoto"
                            target_url = str(b.get("TargetURL") or "")
                            if "wasabi" in target_url.lower():
                                dest_label = "Wasabi S3 Cloud"
                            elif "s3.amazonaws" in target_url.lower() or "s3://" in target_url.lower():
                                dest_label = "Amazon S3 Cloud"
                            elif "b2" in target_url.lower():
                                dest_label = "Backblaze B2 Cloud"
                            elif "azure" in target_url.lower():
                                dest_label = "Azure Blob Cloud"
                            elif "file://" in target_url.lower() or ":" in target_url:
                                dest_label = "Disco Local / Pasta"

                            meta = b.get("Metadata", {})
                            last_run = meta.get("LastBackupDate") or meta.get("LastBackupFinished")

                            backups.append({
                                "id": str(b.get("ID") or ""),
                                "name": b.get("Name") or "",
                                "description": b.get("Description") or "",
                                "target_url": target_url,
                                "target_label": dest_label,
                                "passphrase": passphrase,
                                "sources": sources,
                                "schedule": s,
                                "settings": settings_dict,
                                "metadata": meta,
                                "last_run": last_run,
                                "last_status": dup_last_status(meta, "completed"),
                                "source_origin": "serverutil_export",
                                "Backup": b,
                                "Schedule": s
                            })
                        except Exception as _fe:
                            logger.warning(f"Erro lendo export JSON {json_file}: {_fe}")
            except Exception as _e_cmd:
                logger.warning(f"Erro ao executar ServerUtil export: {_e_cmd}")
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        if backups:
            logger.info(f"✅ {len(backups)} backup(s) Duplicati extraído(s) e decifrado(s) com sucesso via ServerUtil.")
            return backups

        # Fallback via SQLite
        sqlite_items = self._read_duplicati_server_db()
        return sqlite_items

    def _normalize_backup_item(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        """Normaliza um item de backup do Duplicati (seja vindo de HTTP ou de SQLite)."""
        b = raw_item.get("Backup") if isinstance(raw_item.get("Backup"), dict) else raw_item
        b_id = str(b.get("ID") or raw_item.get("id") or "")
        name = b.get("Name") or raw_item.get("name") or f"Backup #{b_id}"
        desc = b.get("Description") or raw_item.get("description") or ""
        target_url = str(b.get("TargetURL") or raw_item.get("target_url") or "")
        meta = b.get("Metadata") or raw_item.get("metadata") or {}

        dest_label = "Destino Remoto"
        if "wasabi" in target_url.lower():
            dest_label = "Wasabi S3 Cloud"
        elif "s3.amazonaws" in target_url.lower() or "s3://" in target_url.lower():
            dest_label = "Amazon S3 Cloud"
        elif "b2" in target_url.lower():
            dest_label = "Backblaze B2 Cloud"
        elif "azure" in target_url.lower():
            dest_label = "Azure Blob Cloud"
        elif "file://" in target_url.lower() or ":" in target_url:
            dest_label = "Disco Local / Pasta"

        def fix_iso_date(raw_val: Any) -> Optional[str]:
            if not raw_val:
                return None
            s = str(raw_val).strip()
            if len(s) == 16 and s[8] == 'T' and s[15] == 'Z':
                return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[9:11]}:{s[11:13]}:{s[13:15]}"
            return s

        last_run = fix_iso_date(meta.get("LastBackupDate") or raw_item.get("last_run")) or "Nunca"
        last_status = dup_last_status(meta, raw_item.get("last_status") or ("OK" if last_run != "Nunca" else "Pendente"))
        last_error_msg = meta.get("LastErrorMessage") if last_status == "Erro" else None

        source_size = meta.get("SourceFilesSize") or raw_item.get("source_size") or 0
        target_size = meta.get("TargetFilesSize") or raw_item.get("target_size") or 0
        versions_count = meta.get("BackupListCount") or raw_item.get("versions_count") or 1
        duration = meta.get("LastBackupDuration") or raw_item.get("duration") or "—"

        return {
            "id": b_id,
            "name": name,
            "description": desc,
            "target_url": target_url,
            "target_label": dest_label,
            "last_run": last_run,
            "last_status": last_status,
            "last_error": last_error_msg,
            "source_size": source_size,
            "target_size": target_size,
            "versions_count": versions_count,
            "duration": duration,
            "schedule": raw_item.get("Schedule") or raw_item.get("schedule") or {},
            "Backup": b,
            "Schedule": raw_item.get("Schedule") or raw_item.get("schedule") or {}
        }

    def list_backups(self) -> Dict[str, Any]:
        cfg = self.load_config()
        paths = ["api/v1/backups", "api/v1/backup"]
        last_error: Optional[str] = None
        for path in paths:
            try:
                resp = self._api_get(cfg, path)
                if resp.status_code == 200:
                    data = resp.json()
                    items_list = []
                    if isinstance(data, dict):
                        for key in ("Backups", "backups", "Items", "items"):
                            if key in data and isinstance(data[key], list):
                                items_list = data[key]
                                break
                        if not items_list:
                            items_list = [data]
                    elif isinstance(data, list):
                        items_list = data
                    
                    normalized = [self._normalize_backup_item(i) for i in items_list]
                    return {"status": "success", "items": normalized, "source": self._build_url(cfg, path)}
            except Exception as e:
                last_error = str(e)

        # Fallback: tentar ler diretamente do SQLite local do Duplicati
        db_items = self._read_duplicati_server_db()
        if db_items:
            normalized = [self._normalize_backup_item(i) for i in db_items]
            return {
                "status": "success",
                "items": normalized,
                "source": "sqlite_local_db"
            }

        return {
            "status": "error",
            "message": "Não foi possível listar backups no Duplicati",
            "error": last_error or "Nenhum backup encontrado no servidor HTTP nem no banco SQLite",
            "items": [],
        }

    def list_filesets(self, backup_id: str) -> List[Dict[str, Any]]:
        """Lista os filesets (snapshots / pontos no tempo) reais de um backup do Duplicati."""
        cfg = self.load_config()

        # 1. Tentar via API HTTP do Duplicati
        try:
            resp = self._api_get(cfg, f"api/v1/backup/{backup_id}/filesets")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    snapshots = []
                    for idx, fs in enumerate(data):
                        ver = str(fs.get("Version", idx))
                        ts = fs.get("Time") or fs.get("Timestamp")
                        filecount = fs.get("FileCount", 0)
                        size = fs.get("FileSizes", 0)
                        size_str = f"{round(size/1024/1024, 2)} MB" if size else ""
                        snapshots.append({
                            "id": f"v{ver}",
                            "full_id": f"v{ver}",
                            "short_id": f"v{ver}",
                            "version": ver,
                            "time": str(ts),
                            "hostname": "Duplicati",
                            "username": "Duplicati",
                            "paths": [f"{filecount} arquivos {size_str}".strip()],
                            "engine": "duplicati",
                            "size_bytes": int(size or 0),
                            "files_count": int(filecount or 0),
                        })
                    if snapshots:
                        return snapshots
        except Exception as e:
            logger.warning(f"Erro ao obter filesets via HTTP: {e}")

        # 2. Fallback via SQLite local do backup (DBPath)
        try:
            import sqlite3
            from datetime import datetime
            db_items = self._read_duplicati_server_db()
            db_path = ""
            for item in db_items:
                b = item.get("Backup", {})
                if str(b.get("ID")) == str(backup_id) or str(item.get("id")) == str(backup_id):
                    db_path = b.get("DBPath") or item.get("DBPath", "")
                    break

            if db_path and os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT ID, Timestamp, OperationID FROM Fileset ORDER BY Timestamp DESC")
                rows = cur.fetchall()
                snapshots = []
                for idx, r in enumerate(rows):
                    ver = str(idx)
                    ts = r["Timestamp"]
                    if isinstance(ts, (int, float)):
                        ts_str = datetime.fromtimestamp(ts).isoformat()
                    else:
                        ts_str = str(ts)
                    snapshots.append({
                        "id": f"v{ver}",
                        "full_id": f"v{ver}",
                        "short_id": f"v{ver}",
                        "version": ver,
                        "time": ts_str,
                        "hostname": "Duplicati Native",
                        "username": "Duplicati",
                        "paths": ["Backup Completo Duplicati"],
                        "engine": "duplicati"
                    })
                conn.close()
                if snapshots:
                    return snapshots
        except Exception as e:
            logger.warning(f"Erro ao ler filesets do SQLite do backup: {e}")

        return []

    # ──────────────────────────────────────────────
    # Controle de Jobs (run / stop / progress)
    # ──────────────────────────────────────────────

    def run_backup(self, backup_id: str) -> Dict[str, Any]:
        """Inicia um job de backup manualmente."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/run")
            if resp.status_code == 200:
                return {"status": "success", "message": f"Backup {backup_id} iniciado"}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def stop_backup(self, backup_id: str, abort: bool = False) -> Dict[str, Any]:
        """Para ou aborta um job de backup em execução."""
        cfg = self.load_config()
        action = "abort" if abort else "stop"
        try:
            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/{action}")
            if resp.status_code == 200:
                return {"status": "success", "message": f"Backup {backup_id} {action}"}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_progress(self) -> Dict[str, Any]:
        """Retorna o estado de progresso atual do Duplicati."""
        cfg = self.load_config()
        try:
            resp = self._api_get(cfg, "api/v1/progressstate")
            if resp.status_code == 200:
                return {"status": "success", "progress": resp.json()}
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_server_state(self) -> Dict[str, Any]:
        """Retorna o estado atual do servidor Duplicati (programed, running, paused...)."""
        cfg = self.load_config()
        try:
            resp = self._api_get(cfg, "api/v1/serverstate")
            if resp.status_code == 200:
                return {"status": "success", "state": resp.json()}
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_backup_log(self, backup_id: str, page_size: int = 20) -> Dict[str, Any]:
        """Retorna o log de execuções de um job específico."""
        cfg = self.load_config()
        try:
            resp = self._api_get(cfg, f"api/v1/backup/{backup_id}/log?pagesize={page_size}")
            if resp.status_code == 200:
                return {"status": "success", "log": resp.json()}
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def pause_server(self) -> Dict[str, Any]:
        """Pausa o agendador do Duplicati."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, "api/v1/serverstate/pause")
            return {"status": "success" if resp.status_code == 200 else "error",
                    "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def resume_server(self) -> Dict[str, Any]:
        """Retoma o agendador do Duplicati."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, "api/v1/serverstate/resume")
            return {"status": "success" if resp.status_code == 200 else "error",
                    "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ──────────────────────────────────────────────
    # Agendamento
    # ──────────────────────────────────────────────

    def set_schedule(self, backup_id: str, schedule: Dict[str, Any]) -> Dict[str, Any]:
        """Define ou atualiza o agendamento de um job de backup.

        Parâmetros esperados em ``schedule``:
        - time (str)           : horário no formato "HH:MM" (ex: "02:00")
        - repeat (str)         : intervalo no formato Duplicati (ex: "1D", "1W")
        - allowed_days (list)  : dias permitidos ["mon","tue","wed","thu","fri","sat","sun"]
        - tags (list)          : lista de tags opcionais
        """
        cfg = self.load_config()
        try:
            # Obter agendamento atual do backup para preservar campos não informados
            resp_get = self._api_get(cfg, f"api/v1/backup/{backup_id}")
            if resp_get.status_code != 200:
                return {"status": "error", "message": f"Backup {backup_id} não encontrado (HTTP {resp_get.status_code})"}
            current = resp_get.json()
            current_schedule = current.get("Schedule") or {}

            # Montar payload de agendamento
            time_str = schedule.get("time", current_schedule.get("Time", "02:00"))
            # Normalizar "HH:MM" para formato ISO com data fictícia esperada pelo Duplicati
            if len(time_str) == 5:  # "HH:MM"
                time_str = f"1970-01-01T{time_str}:00"

            new_schedule = {
                "ID": current_schedule.get("ID", 0),
                "Tags": schedule.get("tags", current_schedule.get("Tags", [f"ID={backup_id}"])),
                "Time": time_str,
                "Repeat": schedule.get("repeat", current_schedule.get("Repeat", "1D")),
                "LastRun": current_schedule.get("LastRun", "0001-01-01T00:00:00"),
                "Rule": schedule.get("rule", current_schedule.get("Rule", "")),
                "AllowedDays": schedule.get("allowed_days", current_schedule.get("AllowedDays", [])),
            }

            payload = {
                "Backup": current.get("Backup", {}),
                "Schedule": new_schedule,
            }

            resp = self._api_put(cfg, f"api/v1/backup/{backup_id}", payload)
            if resp.status_code == 200:
                return {"status": "success", "message": f"Agendamento do backup {backup_id} atualizado", "schedule": new_schedule}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ──────────────────────────────────────────────
    # Restauração
    # ──────────────────────────────────────────────

    def restore_backup(self, backup_id: str, restore_options: Dict[str, Any]) -> Dict[str, Any]:
        """Inicia uma restauração de arquivos de um backup.

        Parâmetros em ``restore_options``:
        - paths (list)          : caminhos a restaurar (vazio = tudo)
        - restore_path (str)    : destino da restauração
        - overwrite (bool)      : sobrescrever arquivos existentes (padrão False)
        - time (str)            : versão a restaurar, ex: "now" ou ISO datetime
        - passphrase (str)      : senha de decriptação (se necessário)
        """
        cfg = self.load_config()
        try:
            paths = restore_options.get("paths", [])
            restore_path = restore_options.get("restore_path", "")
            overwrite = restore_options.get("overwrite", False)
            time_ver = restore_options.get("time", "now")
            passphrase = restore_options.get("passphrase", "")

            if not restore_path:
                return {"status": "error", "message": "restore_path é obrigatório"}

            payload: Dict[str, Any] = {
                "paths": paths,
                "time": time_ver,
                "restore-path": restore_path,      # Duplicati 2.0.x
                "restore_path": restore_path,      # Duplicati 2.1+ (sem ele restaurava no LOCAL ORIGINAL)
                "overwrite": overwrite,
            }
            if passphrase:
                payload["passphrase"] = passphrase

            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/restore", payload)
            if resp.status_code == 200:
                data = resp.json() if resp.text else {}
                return {"status": "success", "message": f"Restauração do backup {backup_id} iniciada", "task": data}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ──────────────────────────────────────────────
    # Monitor de Resultado (para alertas automáticos)
    # ──────────────────────────────────────────────

    def get_last_result(self, backup_id: str) -> Dict[str, Any]:
        """Retorna o resultado (ParsedResult) da última execução do backup."""
        cfg = self.load_config()
        try:
            resp = self._api_get(cfg, f"api/v1/backup/{backup_id}/log?pagesize=1")
            if resp.status_code != 200:
                return {"status": "error", "message": f"HTTP {resp.status_code}"}
            entries = resp.json()
            if not entries:
                return {"status": "success", "result": None, "message": "Sem execuções registradas"}
            entry = entries[0]
            msg_raw = entry.get("Message", "")
            parsed_result = None
            error_messages: List[str] = []
            test_result = None
            tested = 0
            try:
                import json as _json
                data = _json.loads(msg_raw)
                parsed_result = data.get("ParsedResult")  # None = log sem resultado (o monitor trata como sem erro)
                error_messages = data.get("Errors", []) or []
                # Teste de amostras que o Duplicati faz ao fim do backup (backup-test-samples)
                tr = data.get("TestResults") or {}
                if isinstance(tr, dict) and tr:
                    test_result = tr.get("ParsedResult")
                    tested = len(tr.get("Verifications") or [])
            except Exception:
                pass
            return {
                "status": "success",
                "backup_id": backup_id,
                "parsed_result": parsed_result,
                "errors": error_messages,
                "test_result": test_result,
                "tested_volumes": tested,
                "timestamp": entry.get("Timestamp"),
                "raw_type": entry.get("Type"),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def find_backup_for_task(self, task_name: str) -> Optional[Dict[str, str]]:
        """Backup do Duplicati Server que corresponde a uma tarefa do GBOC (mesma regra usada na execução)."""
        task_name = str(task_name or '')
        for item in self.list_backups().get("items", []):
            b_obj = item.get("Backup", {}) if isinstance(item, dict) else {}
            b_id = str(item.get("id") or b_obj.get("ID") or "")
            b_name = str(item.get("name") or b_obj.get("Name") or "")
            if b_id and (b_name == task_name or f"Nativo_Duplicati_{b_name}" == task_name or
                         (b_name and b_name in task_name) or (b_id in task_name and "duplicati" in task_name.lower())):
                return {"id": b_id, "name": b_name}
        return None

    # ──────────────────────────────────────────────
    # Gerenciamento Completo de Backups (Create, Delete, Repair, Verify, Compact)
    # ──────────────────────────────────────────────

    def delete_backup(self, backup_id: str, delete_remote_files: bool = False) -> Dict[str, Any]:
        """Exclui um job de backup do Duplicati."""
        cfg = self.load_config()
        try:
            url_path = f"api/v1/backup/{backup_id}?delete-remote-files={'true' if delete_remote_files else 'false'}"
            self._ensure_authenticated(cfg)
            headers = {"X-XSRF-Token": self._xsrf_token or ""}
            resp = self._session.delete(self._build_url(cfg, url_path), headers=headers, timeout=cfg.timeout_seconds, verify=cfg.verify_tls)
            if resp.status_code in (200, 204):
                return {"status": "success", "message": f"Backup {backup_id} excluído com sucesso."}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def repair_backup(self, backup_id: str) -> Dict[str, Any]:
        """Executa a reconstrução/reparo do banco local do backup."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/repair")
            if resp.status_code == 200:
                return {"status": "success", "message": f"Reparo do banco de dados do backup {backup_id} iniciado."}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def verify_backup(self, backup_id: str) -> Dict[str, Any]:
        """Verifica a integridade e a conexão com o destino remoto."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/verify")
            if resp.status_code == 200:
                return {"status": "success", "message": f"Verificação do destino do backup {backup_id} disparada com sucesso!"}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def compact_backup(self, backup_id: str) -> Dict[str, Any]:
        """Compacta e limpa blocos órfãos no destino do backup."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/compact")
            if resp.status_code == 200:
                return {"status": "success", "message": f"Compactação do backup {backup_id} iniciada."}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ──────────────────────────────────────────────
    # Exportar / importar definições dos jobs (pacote de recuperação do GBOC)
    # ──────────────────────────────────────────────

    def is_configured(self) -> bool:
        return os.path.exists(CONFIG_FILE)

    def export_backup_config(self, backup_id: str) -> Dict[str, Any]:
        """Definição completa do job COM as senhas (destino, passphrase), como o "Exportar" do Duplicati.
        v2.1+: token de uso único (POST auth/issuetoken/export); versões antigas: GET direto."""
        cfg = self.load_config()
        token = None
        try:
            t = self._api_post(cfg, "api/v1/auth/issuetoken/export")
            if t.status_code == 200:
                token = (t.json() or {}).get("Token")
        except Exception:
            token = None
        path = f"api/v1/backup/{backup_id}/export?export-passwords=true" + (f"&token={token}" if token else "")
        r = self._api_get(cfg, path)
        if r.status_code != 200:
            raise RuntimeError(f"Duplicati não exportou o job {backup_id}: HTTP {r.status_code} {r.text[:200]}")
        data = r.json()
        if not isinstance(data, dict) or not isinstance(data.get("Backup"), dict):
            raise RuntimeError(f"Exportação do job {backup_id} em formato inesperado")
        return data

    def export_all_backups(self) -> Dict[str, Any]:
        """{"jobs": [exportação de cada job], "errors": [...]} — usado no pacote de recuperação."""
        items = (self.list_backups() or {}).get("items") or []
        jobs, errors = [], []
        for it in items:
            bid = str(it.get("id") or it.get("ID") or "")
            if not bid:
                continue
            try:
                jobs.append(self.export_backup_config(bid))
            except Exception as e:
                errors.append(f"{it.get('name') or bid}: {e}")
        return {"jobs": jobs, "errors": errors}

    def import_backup_config(self, exported: Dict[str, Any], repair: bool = True) -> Dict[str, Any]:
        """Recria um job exportado (instalação nova do Duplicati). Job com o mesmo nome já existente é mantido.
        repair=True: dispara o reparo, que reconstrói o banco local a partir dos arquivos do destino — sem ele o
        próximo backup falha por arquivos remotos desconhecidos."""
        cfg = self.load_config()
        b = dict(exported.get("Backup") or {})
        name = str(b.get("Name") or "").strip()
        if not name:
            return {"status": "error", "message": "Job sem nome"}
        existing = {str(i.get("name") or "").strip().lower(): i for i in ((self.list_backups() or {}).get("items") or [])}
        if name.lower() in existing:
            return {"status": "skipped", "name": name, "message": "Job com o mesmo nome já existe no Duplicati"}
        for k in ("ID", "DBPath", "Metadata", "ExternalID", "IsTemporary"):
            b.pop(k, None)
        sched = exported.get("Schedule")
        if isinstance(sched, dict):
            sched = {k: v for k, v in sched.items() if k not in ("ID", "LastRun", "Tags")}
        r = self._api_post(cfg, "api/v1/backups", json_body={"Backup": b, "Schedule": sched})
        if r.status_code not in (200, 201):
            return {"status": "error", "name": name, "message": f"HTTP {r.status_code}: {r.text[:200]}"}
        data = r.json() if r.content else {}
        new_id = str(data.get("ID") or data.get("Id") or (data.get("Backup") or {}).get("ID") or "")
        out = {"status": "created", "name": name, "id": new_id}
        if repair and new_id:
            out["repair"] = self.repair_backup(new_id).get("status")
        return out

    def create_backup(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria uma nova rotina de backup no Duplicati Server nativo e sincroniza com o GBOC.
        Cria automaticamente o repositório em 'repositories' e vincula em 'tasks'.
        """
        cfg = self.load_config()

        name = payload.get("name") or "Backup_GBOC"
        desc = payload.get("description") or ""
        # destino padrao dentro da pasta do Agente (antes: C:\\GBOC-Backups)
        from core.gboc_paths import REPOSITORIES_DIR as _gboc_repos
        target_url = str(payload.get("target_url") or f"file://{_gboc_repos / 'duplicati'}").strip()
        if not ("://" in target_url):
            target_url = f"file://{target_url}"

        sources = payload.get("sources") or []
        if isinstance(sources, str):
            sources = [s.strip() for s in sources.split(",") if s.strip()]
        passphrase = payload.get("passphrase") or ""
        repeat = payload.get("schedule_repeat") or "1D"

        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        sched_time = (now + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:00Z')

        settings = [
            {"Name": "dblock-size", "Value": "50MB"},
            {"Name": "compression-module", "Value": "zip"},
        ]
        if passphrase:
            settings.extend([
                {"Name": "encryption-module", "Value": "aes"},
                {"Name": "passphrase", "Value": passphrase}
            ])
        else:
            settings.append({"Name": "--no-encryption", "Value": "true"})

        dup_payload = {
            "Backup": {
                "Name": name,
                "Description": desc,
                "TargetURL": target_url,
                "Sources": sources,
                "Settings": settings,
                "Filters": []
            },
            "Schedule": {
                "Repeat": repeat,
                "Time": sched_time,
                "AllowedDays": None
            }
        }

        # Extrair caminho físico se for local
        repo_path = target_url
        if target_url.startswith("file://"):
            repo_path = target_url[7:].lstrip("/") if sys.platform != "win32" else target_url[7:]
        
        is_cloud = any(cloud_p in target_url.lower() for cloud_p in ("s3:", "wasabi", "b2:", "azure", "sftp"))
        if not is_cloud:
            try:
                os.makedirs(repo_path, exist_ok=True)
            except Exception:
                pass

        # 1. Enviar para API do Duplicati
        new_id = None
        try:
            resp = self._api_post(cfg, "api/v1/backups", json_body=dup_payload)
            if resp.status_code in (200, 201):
                data = resp.json()
                new_id = data.get("ID") or data.get("Id") or (data.get("Backup", {}).get("ID"))
            else:
                err_detail = resp.text[:400]
                try:
                    err_json = resp.json()
                    err_detail = err_json.get("Error") or err_json.get("message") or err_detail
                except Exception:
                    pass
                return {
                    "status": "error",
                    "message": f"Erro do Duplicati: {err_detail}",
                    "detail": err_detail
                }
        except Exception as e:
            logger.error(f"Exceção ao criar backup Duplicati: {e}")
            return {"status": "error", "message": f"Erro de conexão com o Duplicati: {str(e)}"}

        # 2. Criar / Garantir repositório local ou nuvem na tabela 'repositories' do GBOC
        try:
            from shared_core import get_shared_core
            core = get_shared_core()
            with core.get_db_connection() as conn:
                cur = conn.cursor()
                repo_name = f"Repo_Duplicati_{name}"
                cur.execute("SELECT id FROM repositories WHERE name = %s OR path = %s", (repo_name, repo_path))
                repo_row = cur.fetchone()
                now_str = datetime.now().isoformat()
                if repo_row:
                    repo_id = repo_row[0]
                else:
                    repo_type = "cloud" if is_cloud else "local"
                    cur.execute("""
                        INSERT INTO repositories (name, type, path, engine, status, enabled, initialized, created_at, updated_at)
                        VALUES (%s, %s, %s, 'duplicati', 'active', true, true, %s, %s)
                        RETURNING id
                    """, (repo_name, repo_type, repo_path, now_str, now_str))
                    repo_id = cur.fetchone()[0]

                # Criar / Garantir tarefa na tabela 'tasks'
                task_name = f"Nativo_Duplicati_{name}"
                cron_str = "0 */2 * * *" if "2h" in repeat.lower() else ("0 2 * * *" if "1d" in repeat.lower() else "0 * * * *")
                sources_json = json.dumps(sources)
                cur.execute("SELECT id FROM tasks WHERE name = %s OR name = %s", (task_name, name))
                task_row = cur.fetchone()
                if task_row:
                    cur.execute("""
                        UPDATE tasks SET repository_id = %s, engine = 'duplicati', source_paths = %s, status = 'idle', enabled = true, schedule_enabled = true, schedule_cron = %s, updated_at = %s
                        WHERE id = %s
                    """, (repo_id, sources_json, cron_str, now_str, task_row[0]))
                else:
                    cur.execute("""
                        INSERT INTO tasks (name, repository_id, engine, source_paths, status, enabled, schedule_enabled, schedule_cron, created_at, updated_at)
                        VALUES (%s, %s, 'duplicati', %s, 'idle', true, true, %s, %s, %s)
                    """, (task_name, repo_id, sources_json, cron_str, now_str, now_str))
                conn.commit()
        except Exception as e_gboc:
            logger.warning(f"Erro ao registrar repositório/tarefa no GBOC: {e_gboc}")

        # Sincronizar imediatamente com o GBOC
        try:
            self.sync_to_gboc(force=True)
        except Exception as _sync_err:
            logger.warning(f"Erro no sync imediato pós-criação de backup Duplicati: {_sync_err}")

        return {
            "status": "success",
            "message": f"Backup Duplicati '{name}' criado com sucesso!",
            "id": new_id
        }

    def sync_to_gboc(self, core: Any = None, force: bool = False) -> Dict[str, Any]:
        """
        Sincroniza os backups e execuções reais do Duplicati Native com o banco de dados do GBOC.
        Garante que cada backup tenha seu repositório criado em 'repositories' e vinculado via 'repository_id' em 'tasks'.
        """
        import time as _py_time
        if not force and hasattr(self, '_last_sync_ts'):
            if _py_time.time() - self._last_sync_ts < 15.0:
                return getattr(self, '_last_sync_result', {"status": "success", "cached": True})

        if core is None:
            try:
                from shared_core import get_shared_core
                core = get_shared_core()
            except Exception as e:
                logger.warning(f"Não foi possível obter shared_core para sync Duplicati: {e}")
                return {"status": "error", "message": "shared_core indisponível"}

        # Obter backups detalhados com todas as credenciais decifradas e configurações completas
        items = self.extract_all_duplicati_backups_detailed()
        if not items:
            backups_res = self.list_backups()
            items = backups_res.get("items", [])

        if not items:
            res = {"status": "success", "synced_tasks": 0, "synced_executions": 0, "message": "Nenhum backup Duplicati detectado"}
            self._last_sync_ts = _py_time.time()
            self._last_sync_result = res
            return res

        from datetime import datetime, timedelta, timezone

        def _parse_time(raw_val: Any) -> Optional[datetime]:
            if not raw_val:
                return None
            s = str(raw_val).strip()
            if len(s) == 16 and s[8] == 'T' and s[15] == 'Z':
                try:
                    return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                except Exception:
                    pass
            try:
                return datetime.fromisoformat(s)
            except Exception:
                pass
            return None

        synced_tasks = 0
        total_new_executions = 0

        try:
            with core.get_db_connection() as conn:
                cur = conn.cursor()

                failures = []
                for item in items:
                    try:
                        b_obj = item.get("Backup", {}) if isinstance(item.get("Backup"), dict) else item
                        b_id = str(item.get("id") or b_obj.get("ID") or "")
                        b_name = item.get("name") or b_obj.get("Name") or f"Duplicati #{b_id}"
                        meta = item.get("metadata") or b_obj.get("Metadata") or {}
                        schedule = item.get("schedule") or item.get("Schedule") or b_obj.get("Schedule") or {}
                        raw_target = str(item.get("target_url") or b_obj.get("TargetURL") or "")
                        passphrase = str(item.get("passphrase") or "")
                        settings = item.get("settings") or {}
                        sources = item.get("sources") or b_obj.get("Sources") or []

                        creds_info = parse_duplicati_target_and_creds(raw_target, passphrase, settings)
                        repo_type = creds_info["repo_type"]
                        clean_path = creds_info["clean_path"]
                        config_json = json.dumps(creds_info["config"])
                        pwd = creds_info["password"] or None
                        m_pwd = creds_info["motor_password"] or None
                        enc_pwd = creds_info["encryption_password"] or None
                        c_pwd = creds_info["cloud_password"] or None

                        repo_name = f"Repo_Duplicati_{b_name}"
                        now_str = datetime.now().isoformat()

                        # Criar ou atualizar repositório com credenciais e configs 100% completas
                        cur.execute("""
                            SELECT id FROM repositories 
                            WHERE name = %s OR path = %s OR path = %s OR id = (
                                SELECT repository_id FROM tasks WHERE name IN (%s, %s, %s) LIMIT 1
                            )
                        """, (repo_name, clean_path, raw_target, f"Nativo_Duplicati_{b_name}", b_name, f"Duplicati_{b_name}"))
                        r_row = cur.fetchone()

                        if r_row:
                            repo_id = r_row[0]
                            cur.execute("""
                                UPDATE repositories 
                                SET name = %s, type = %s, path = %s, engine = 'duplicati',
                                    status = 'active', enabled = true, initialized = true,
                                    password = COALESCE(%s, password),
                                    motor_password = COALESCE(%s, motor_password),
                                    encryption_password = COALESCE(%s, encryption_password),
                                    cloud_password = COALESCE(%s, cloud_password),
                                    config = %s, updated_at = %s
                                WHERE id = %s
                            """, (repo_name, repo_type, clean_path, pwd, m_pwd, enc_pwd, c_pwd, config_json, now_str, repo_id))
                        else:
                            cur.execute("""
                                INSERT INTO repositories (name, type, path, engine, status, enabled, initialized, password, motor_password, encryption_password, cloud_password, config, created_at, updated_at)
                                VALUES (%s, %s, %s, 'duplicati', 'active', true, true, %s, %s, %s, %s, %s, %s, %s)
                                RETURNING id
                            """, (repo_name, repo_type, clean_path, pwd, m_pwd, enc_pwd, c_pwd, config_json, now_str, now_str))
                            repo_id = cur.fetchone()[0]

                        clean_sources = normalize_sources_list(sources)
                        sources_json = json.dumps(clean_sources)

                        repeat = str(schedule.get("Repeat") or schedule.get("repeat") or "2h")
                        time_val = str(schedule.get("Time") or schedule.get("time") or "")
                        cron = convert_duplicati_repeat_to_cron(repeat, time_val)
                        _ret = map_duplicati_retention(settings)
                        logger.info(f"[Duplicati→GBOC] Retenção do job '{b_name}': {_ret['source']} -> "
                                    f"dias={_ret['days']} semanais={_ret['weekly']} mensais={_ret['monthly']} anuais={_ret['yearly']}")

                        last_run_dt = _parse_time(meta.get("LastBackupDate") or meta.get("LastBackupFinished") or item.get("last_run"))

                        # Buscar ou criar tarefa correspondente
                        cur.execute("""
                            SELECT id FROM tasks 
                            WHERE name IN (%s, %s, %s) OR repository_id = %s
                        """, (f"Nativo_Duplicati_{b_name}", b_name, f"Duplicati_{b_name}", repo_id))
                        task_row = cur.fetchone()

                        if task_row:
                            task_id = task_row[0]
                            cur.execute("""
                                UPDATE tasks 
                                SET repository_id = %s,
                                    engine = 'duplicati', 
                                    source_paths = %s, 
                                    status = 'idle', 
                                    enabled = true, 
                                    schedule_enabled = true, 
                                    schedule_cron = %s, 
                                    retention_days = %s, retention_weekly = %s, retention_monthly = %s, retention_yearly = %s,
                                    last_run = %s, 
                                    last_status = 'completed',
                                    updated_at = %s
                                WHERE id = %s
                            """, (repo_id, sources_json, cron, _ret['days'], _ret['weekly'], _ret['monthly'], _ret['yearly'],
                                  last_run_dt or now_str, now_str, task_id))
                        else:
                            task_name = f"Nativo_Duplicati_{b_name}"
                            cur.execute("""
                                INSERT INTO tasks (name, repository_id, engine, source_paths, status, enabled, schedule_enabled, schedule_cron,
                                                   retention_days, retention_weekly, retention_monthly, retention_yearly, last_run, last_status, created_at, updated_at)
                                VALUES (%s, %s, 'duplicati', %s, 'idle', true, true, %s, %s, %s, %s, %s, %s, 'completed', %s, %s)
                                RETURNING id
                            """, (task_name, repo_id, sources_json, cron, _ret['days'], _ret['weekly'], _ret['monthly'], _ret['yearly'],
                                  last_run_dt or now_str, now_str, now_str))
                            task_id = cur.fetchone()[0]

                        conn.commit()
                        synced_tasks += 1

                        # Sincronizar snapshots reais como task_executions
                        snapshots = self.list_filesets(b_id)
                        cur.execute("SELECT snapshot_id FROM task_executions WHERE task_id = %s AND snapshot_id IS NOT NULL", (task_id,))
                        existing_snaps = set(r[0] for r in cur.fetchall())

                        for s in snapshots:
                            s_id = s.get("id") or s.get("version")
                            full_snap_id = f"dup_{b_id}_{s_id}"
                            if full_snap_id in existing_snaps:
                                continue

                            snap_time = _parse_time(s.get("time"))
                            if not snap_time:
                                continue
                            # antes eram nomes inexistentes (NameError na 1ª versão nova: a sincronização inteira abortava)
                            try:
                                bytes_size = int(s.get("size_bytes") or 0)
                            except (TypeError, ValueError):
                                bytes_size = 0
                            try:
                                files_count = int(s.get("files_count") or 0)
                            except (TypeError, ValueError):
                                files_count = 0
                            # Duplicati devolve -1 quando não calculou: na versão mais recente usa os totais do backup
                            _latest = str(s.get("version")) == "0"
                            if bytes_size < 0:
                                bytes_size = int(meta.get("SourceFilesSize") or 0) if _latest else 0
                            if files_count < 0:
                                files_count = int(meta.get("SourceFilesCount") or 0) if _latest else 0

                            cur.execute("""
                                INSERT INTO task_executions (
                                    task_id, status, started_at, completed_at, duration_seconds,
                                    bytes_processed, files_processed, progress, snapshot_id, created_at
                                ) VALUES (
                                    %s, 'completed', %s, %s, %s,
                                    %s, %s, 100, %s, %s
                                )
                            """, (
                                task_id,
                                snap_time,
                                snap_time + timedelta(seconds=36),
                                36,
                                bytes_size,
                                files_count,
                                full_snap_id,
                                snap_time
                            ))
                            existing_snaps.add(full_snap_id)
                            total_new_executions += 1

                        conn.commit()
                    except Exception as _item_err:
                        conn.rollback()
                        _nm = (item.get("name") or (item.get("Backup") or {}).get("Name") or "?") if isinstance(item, dict) else "?"
                        failures.append(f"{_nm}: {_item_err}")
                        logger.error(f"Sync Duplicati: falha no backup '{_nm}': {_item_err}", exc_info=True)

            res = {
                "status": "success" if not failures else ("partial" if synced_tasks else "error"),
                "synced_tasks": synced_tasks,
                "synced_executions": total_new_executions,
                "message": f"Sincronização Duplicati concluída com sucesso ({synced_tasks} tarefa(s), {total_new_executions} nova(s) execução(ões))."
                if not failures else f"Sincronização Duplicati: {synced_tasks} tarefa(s) ok, {len(failures)} com falha.",
            }
            if failures:
                res["failures"] = failures
            self._last_sync_ts = _py_time.time()
            self._last_sync_result = res
            return res
        except Exception as e:
            logger.error(f"Erro ao sincronizar Duplicati com PostgreSQL: {e}")
            return {"status": "error", "message": str(e)}


_service: Optional[DuplicatiNativeService] = None


def get_duplicati_native_service() -> DuplicatiNativeService:
    global _service
    if _service is None:
        _service = DuplicatiNativeService()
    return _service
