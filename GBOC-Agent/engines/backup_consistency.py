"""
GBOC Agent - Consistência do backup no Windows: VSS (cópia de sombra) e arquivos abertos no compartilhamento.

VSS ("auto", padrão): o backup lê uma cópia de sombra do disco, congelada no instante do início. Arquivos abertos
ou em uso (Excel, Word, bancos em arquivo, PST...) são copiados sem erro de "arquivo em uso" e de forma
consistente, sem derrubar ninguém.
  * restic: --use-fs-snapshot     * Kopia: --enable-volume-shadow-copy=when-available
  * Duplicati: --snapshot-policy=Auto     * motor nativo: cria a cópia (Win32_ShadowCopy), lê dela e apaga no fim
  Só discos locais (unidade fixa). Caminho UNC / unidade de rede não tem VSS a partir desta máquina.
  Precisa de administrador (o serviço GBOCAgent roda como LocalSystem).

Arquivos abertos no compartilhamento (close_open_share_files):
  * "never" (padrão): não fecha nada - com VSS isso não é necessário;
  * "on_vss_failure": fecha só se o VSS não estiver disponível ou falhar;
  * "always": fecha antes de todo backup.
  Fecha SÓ os arquivos abertos via rede (SMB) dentro das pastas do backup e registra quem/qual arquivo. Quem
  estava com o arquivo aberto pode perder o que não salvou. Testado: clientes Windows com SMB 2.1/3 reabrem o
  arquivo sozinhos em menos de 1 s (identificador durável) - o fechamento é registrado como "reaberto" e o
  arquivo segue em uso. Por isso o padrão é VSS e esta opção vem desligada.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("gboc_consistency")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_FILE = os.path.join(BASE_DIR, "data", "vss_sessions.json")
KEY = "backup_consistency"
DEFAULT = {"vss": "auto", "close_open_share_files": "never"}
_lock = threading.Lock()


def validate(cfg: Any) -> Dict[str, Any]:
    c = dict(DEFAULT)
    c.update({k: v for k, v in (cfg or {}).items() if k in DEFAULT})
    if c["vss"] not in ("auto", "off"):
        raise ValueError("vss deve ser 'auto' ou 'off'")
    if c["close_open_share_files"] not in ("never", "on_vss_failure", "always"):
        raise ValueError("close_open_share_files deve ser 'never', 'on_vss_failure' ou 'always'")
    return c


def _core():
    from shared_core import get_shared_core
    return get_shared_core()


def load_config() -> Dict[str, Any]:
    try:
        with _core().get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key = %s", (KEY,))
            row = cur.fetchone()
            cur.close()
        if row and row[0]:
            return validate(json.loads(row[0]) if isinstance(row[0], str) else row[0])
    except Exception as e:
        logger.debug(f"config de consistência indisponível: {e}")
    return dict(DEFAULT)


def save_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    c = validate(cfg)
    with _core().get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""INSERT INTO settings (category, key, value, type, description)
                       VALUES ('operation', %s, %s, 'json', 'VSS e arquivos abertos no compartilhamento')
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP""",
                    (KEY, json.dumps(c)))
        conn.commit()
        cur.close()
    return c


def _ps(script: str, env: Optional[Dict[str, str]] = None, timeout: int = 180) -> Tuple[int, str]:
    e = dict(os.environ, **(env or {}))
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=e,
                       encoding="utf-8", errors="replace")
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _drive_fixed(drive: str) -> bool:
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(drive) == 3        # DRIVE_FIXED
    except Exception:
        return False


def local_volume(path: str) -> Optional[str]:
    """'D:\\' para caminho em disco local fixo; None para UNC, unidade de rede, removível etc."""
    if os.name != "nt" or not path:
        return None
    p = os.path.abspath(path)
    if p.startswith("\\\\"):
        return None
    drive = os.path.splitdrive(p)[0]
    if len(drive) != 2 or drive[1] != ":":
        return None
    vol = drive.upper() + "\\"
    return vol if _drive_fixed(vol) else None


def vss_status(paths: List[str]) -> Tuple[bool, str]:
    """VSS pode ser usado para estas origens? (motivo quando não)"""
    if os.name != "nt":
        return False, "não é Windows"
    if load_config()["vss"] == "off":
        return False, "VSS desligado na configuração"
    if not is_admin():
        return False, "o Agente não está rodando como administrador/serviço"
    if not any(local_volume(p) for p in paths):
        return False, "nenhuma origem em disco local (UNC/unidade de rede não têm VSS a partir desta máquina)"
    return True, ""


def engine_args(engine: str, paths: List[str]) -> List[str]:
    ok, why = vss_status(paths)
    if not ok:
        if load_config()["vss"] != "off":
            logger.info(f"🧊 [VSS] {engine}: sem cópia de sombra ({why})")
        return []
    logger.info(f"🧊 [VSS] {engine}: lendo de cópia de sombra (arquivos abertos são copiados)")
    return {"restic": ["--use-fs-snapshot"], "duplicati": ["--snapshot-policy=Auto"],
            "kopia": ["--enable-volume-shadow-copy=when-available"]}.get(engine, [])


# ───────────────────────── cópia de sombra para o motor nativo ─────────────────────────

_CREATE = r"""
$ErrorActionPreference = 'Stop'
$r = Invoke-CimMethod -ClassName Win32_ShadowCopy -MethodName Create -Arguments @{ Volume = $env:GBOC_VOL; Context = 'ClientAccessible' }
if ($r.ReturnValue -ne 0) { "ERRO $($r.ReturnValue)"; exit 2 }
$s = Get-CimInstance Win32_ShadowCopy -Filter "ID='$($r.ShadowID)'"
@{ id = [string]$r.ShadowID; device = [string]$s.DeviceObject } | ConvertTo-Json -Compress
"""
_DELETE = r"""
$ErrorActionPreference = 'Stop'
foreach ($id in ($env:GBOC_IDS -split ';')) { if ($id) { Get-CimInstance Win32_ShadowCopy -Filter "ID='$id'" | Remove-CimInstance } }
"""
_VSS_ERRORS = {1: "acesso negado", 2: "parâmetro inválido", 3: "volume não encontrado", 4: "volume não suportado",
               5: "contexto não suportado", 6: "espaço insuficiente para a cópia de sombra", 7: "volume em uso",
               8: "limite de cópias de sombra atingido", 9: "outra cópia de sombra em andamento",
               10: "falha do provedor VSS", 11: "provedor VSS desconhecido", 12: "erro desconhecido"}


def _save_sessions(ids: List[str]) -> None:
    with _lock:
        try:
            os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
            with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(ids, f)
        except OSError:
            pass


def _load_sessions() -> List[str]:
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            return list(json.load(f) or [])
    except Exception:
        return []


def cleanup_leftovers() -> None:
    """Cópias de sombra que ficaram quando o Agente parou no meio de um backup (ocupam espaço no disco)."""
    left = _load_sessions()
    if not left or not is_admin():
        return
    code, out = _ps(_DELETE, {"GBOC_IDS": ";".join(left)})
    logger.info(f"🧊 [VSS] {len(left)} cópia(s) de sombra de backup interrompido apagada(s)" if code == 0
                else f"[VSS] limpeza de cópias antigas: {out[-200:]}")
    if code == 0:
        _save_sessions([])


class ShadowSession:
    """Cria uma cópia de sombra por volume das origens; translate() dá o caminho de leitura dentro dela."""

    def __init__(self):
        self.devices: Dict[str, str] = {}
        self.ids: List[str] = []
        self.errors: List[str] = []

    def create(self, paths: List[str]) -> "ShadowSession":
        cleanup_leftovers()
        vols = []
        for p in paths:
            v = local_volume(p)
            if v and v not in vols:
                vols.append(v)
        for v in vols:
            try:
                code, out = _ps(_CREATE, {"GBOC_VOL": v})
                if code == 0 and out.strip().startswith("{"):
                    d = json.loads(out.strip().splitlines()[-1])
                    self.devices[v] = d["device"].rstrip("\\")
                    self.ids.append(d["id"])
                    _save_sessions(_load_sessions() + [d["id"]])
                    logger.info(f"🧊 [VSS] cópia de sombra de {v} criada ({d['device']})")
                else:
                    num = int(out.split()[-1]) if out.startswith("ERRO") and out.split()[-1].isdigit() else None
                    self.errors.append(f"{v}: {_VSS_ERRORS.get(num, out[-200:])}")
            except Exception as e:
                self.errors.append(f"{v}: {e}")
        for e in self.errors:
            logger.warning(f"[VSS] cópia de sombra não criada - {e}; esse volume será lido direto do disco")
        return self

    def translate(self, path: str) -> str:
        v = local_volume(path)
        dev = self.devices.get(v) if v else None
        if not dev:
            return path
        rest = os.path.abspath(path)[2:]                              # "\pasta\sub" (sem "D:")
        return dev + (rest if rest else "\\")

    def ok_for(self, path: str) -> bool:
        v = local_volume(path)
        return bool(v and v in self.devices)

    def close(self) -> None:
        if not self.ids:
            return
        code, out = _ps(_DELETE, {"GBOC_IDS": ";".join(self.ids)})
        if code == 0:
            logger.info(f"🧊 [VSS] {len(self.ids)} cópia(s) de sombra apagada(s)")
            _save_sessions([i for i in _load_sessions() if i not in self.ids])
        else:
            logger.warning(f"[VSS] não foi possível apagar a cópia de sombra (será tentado no próximo backup): {out[-200:]}")
        self.ids = []


# ───────────────────────── arquivos abertos no compartilhamento ─────────────────────────

_CLOSE = r"""
$ErrorActionPreference = 'Stop'
$roots = @($env:GBOC_PATHS -split '\|' | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('\') + '\' })
$open = @(Get-SmbOpenFile -ErrorAction SilentlyContinue | Where-Object {
    $p = [string]$_.Path; $hit = $false
    foreach ($r in $roots) { if ($p.StartsWith($r, [StringComparison]::OrdinalIgnoreCase) -or ($p + '\') -ieq $r) { $hit = $true; break } }
    $hit -and -not $_.Path.EndsWith('\') })
$res = @()
foreach ($f in $open) {
    try { Close-SmbOpenFile -FileId $f.FileId -Force -ErrorAction Stop; $ok = $true } catch { $ok = $false }
    $res += [pscustomobject]@{ user = [string]$f.ClientUserName; host = [string]$f.ClientComputerName; path = [string]$f.Path; closed = $ok; reopened = $false }
}
if ($res.Count -gt 0) {
    # cliente SMB 2.1/3 (identificador duravel): o servidor guarda o bloqueio para ele reconectar. Confere do
    # jeito que o backup leria: abrir para leitura
    Start-Sleep -Seconds 2
    foreach ($r in $res) {
        try { $h = [IO.File]::Open($r.path, 'Open', 'Read', 'ReadWrite'); $h.Close() } catch { $r.reopened = $true }
    }
}
ConvertTo-Json -InputObject @($res) -Compress -Depth 3
"""


def close_open_share_files(paths: List[str], reason: str) -> List[Dict[str, Any]]:
    """Fecha arquivos abertos via rede (SMB) dentro das origens do backup. Retorna o que foi fechado."""
    roots = [os.path.abspath(p) for p in paths if local_volume(p)]
    if not roots or os.name != "nt":
        return []
    if not is_admin():
        logger.warning("[COMPARTILHAMENTO] fechar arquivos abertos exige administrador/serviço")
        return []
    try:
        code, out = _ps(_CLOSE, {"GBOC_PATHS": "|".join(roots)}, timeout=120)
        items = json.loads(out.strip().splitlines()[-1]) if code == 0 and out.strip() else []
    except Exception as e:
        logger.warning(f"[COMPARTILHAMENTO] não foi possível verificar arquivos abertos: {e}")
        return []
    if isinstance(items, dict):
        items = [items]
    for it in items:
        if it.get("closed") and it.get("reopened"):
            state = "fechado, mas CONTINUA BLOQUEADO (o computador do usuário mantém o arquivo - SMB durável); o VSS é o que resolve"
        else:
            state = "fechado" if it.get("closed") else "NÃO fechado"
        logger.warning(f"🔒 [COMPARTILHAMENTO] arquivo aberto {state} ({reason}): {it.get('path')} - "
                       f"usuário {it.get('user')} em {it.get('host')}")
    if items:
        try:
            from api.audit_api import record_audit
            record_audit(action="backup.close_open_files", resource_type="share", resource_name=reason,
                         username="system", detail={"files": items[:200], "at": datetime.now().isoformat(timespec="seconds")})
        except Exception:
            pass
    return items


def before_backup(engine: str, paths: List[str]) -> Dict[str, Any]:
    """Motores externos: decide sobre fechar arquivos abertos antes do início (VSS vai pelos argumentos)."""
    mode = load_config()["close_open_share_files"]
    vss_ok, why = vss_status(paths)
    closed: List[Dict[str, Any]] = []
    if mode == "always":
        closed = close_open_share_files(paths, f"{engine}: configurado para fechar sempre")
    elif mode == "on_vss_failure" and not vss_ok:
        closed = close_open_share_files(paths, f"{engine}: VSS indisponível ({why})")
    return {"vss": vss_ok, "vss_reason": why, "closed_files": closed}
