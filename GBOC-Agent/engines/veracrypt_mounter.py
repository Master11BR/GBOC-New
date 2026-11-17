#!/usr/bin/env python3
"""
🔐 GBOC Agent 15.0.0 - VeraCrypt Volume Mounter Engine
Montagem e desmontagem automática e manual de volumes criptografados VeraCrypt (.hc, .tc, partições)
para execução transparente de tarefas de backup.

100% Real Host Integration (Zero-Mock Policy):
- Executa o binário real do VeraCrypt instalado no sistema operacional (Windows / Linux).
- Armazena a senha do volume criptografada em repouso (Fernet AES-128-CBC + HMAC-SHA256 via repo_secrets).
- Verifica a montagem real da letra de unidade / ponto de montagem no sistema operacional.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import shutil
import string
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil

from engines import repo_secrets

logger = logging.getLogger("gboc_agent.veracrypt")


def find_veracrypt_executable(custom_path: Optional[str] = None) -> Optional[str]:
    """Localiza o executável real do VeraCrypt instalado no host."""
    if custom_path:
        custom_clean = str(custom_path).strip().strip('"')
        if custom_clean and os.path.isfile(custom_clean):
            return os.path.abspath(custom_clean)

    env_path = os.environ.get("GBOC_VERACRYPT_PATH", "").strip()
    if env_path and os.path.isfile(env_path):
        return os.path.abspath(env_path)

    is_windows = platform.system().lower().startswith("win")
    candidates: List[str] = []

    if is_windows:
        which_vc = shutil.which("VeraCrypt.exe") or shutil.which("veracrypt")
        if which_vc and os.path.isfile(which_vc):
            return os.path.abspath(which_vc)

        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local_app = os.environ.get("LOCALAPPDATA", "")
        base_dir = Path(__file__).resolve().parent.parent

        candidates.extend([
            os.path.join(prog_files, "VeraCrypt", "VeraCrypt.exe"),
            os.path.join(prog_x86, "VeraCrypt", "VeraCrypt.exe"),
            os.path.join(local_app, "Programs", "VeraCrypt", "VeraCrypt.exe") if local_app else "",
            r"C:\Program Files\VeraCrypt\VeraCrypt.exe",
            r"C:\Program Files (x86)\VeraCrypt\VeraCrypt.exe",
            str(base_dir / "tools" / "veracrypt" / "VeraCrypt.exe"),
            str(base_dir / "bin" / "VeraCrypt.exe"),
        ])
    else:
        which_vc = shutil.which("veracrypt")
        if which_vc and os.path.isfile(which_vc):
            return os.path.abspath(which_vc)
        candidates.extend([
            "/usr/bin/veracrypt",
            "/usr/local/bin/veracrypt",
            "/snap/bin/veracrypt",
        ])

    for path in candidates:
        if path and os.path.isfile(path):
            return os.path.abspath(path)

    return None


def normalize_drive_letter(letter_or_mount: Optional[str]) -> str:
    """Normaliza a letra da unidade no Windows (ex: 'V:', 'v:\\', 'V' -> 'V') ou mount point no Linux."""
    if not letter_or_mount:
        return ""
    raw = str(letter_or_mount).strip()
    if platform.system().lower().startswith("win"):
        cleaned = raw.rstrip("\\/").rstrip(":").strip().upper()
        if len(cleaned) == 1 and cleaned in string.ascii_uppercase:
            return cleaned
        return cleaned[:1].upper() if cleaned else ""
    return raw


def get_drive_root_path(letter_or_mount: Optional[str]) -> str:
    """Retorna o caminho raiz correspondente à unidade montada (ex: 'V:\\' no Windows)."""
    norm = normalize_drive_letter(letter_or_mount)
    if not norm:
        return ""
    if platform.system().lower().startswith("win"):
        return f"{norm}:\\"
    return norm


def is_drive_mounted(letter_or_mount: Optional[str]) -> bool:
    """Verifica no sistema operacional se a unidade/ponto de montagem está realmente montado e acessível."""
    root_path = get_drive_root_path(letter_or_mount)
    if not root_path:
        return False

    if platform.system().lower().startswith("win"):
        letter = normalize_drive_letter(letter_or_mount)
        if not letter or len(letter) != 1:
            return False
        try:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            bit_index = ord(letter) - ord("A")
            if bit_index < 0 or bit_index > 25:
                return False
            if not (bitmask & (1 << bit_index)):
                return False
        except Exception:
            pass
        return os.path.isdir(root_path)

    return os.path.ismount(root_path) or (os.path.isdir(root_path) and bool(os.listdir(root_path)))


def _windows_dos_device(letter: str) -> str:
    """Retorna o dispositivo NT real por trás da letra (ex: '\\Device\\VeraCryptVolumeV')."""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.QueryDosDeviceW(f"{letter}:", buf, 1024)
        if n:
            return buf.value or ""
    except Exception:
        pass
    return ""


def is_veracrypt_drive(letter_or_mount: Optional[str]) -> Optional[bool]:
    """
    Confirma no SO se a unidade montada pertence ao VeraCrypt.
    True = volume VeraCrypt | False = outro disco ocupa a letra/ponto | None = não foi possível determinar.
    """
    if platform.system().lower().startswith("win"):
        letter = normalize_drive_letter(letter_or_mount)
        if not letter or len(letter) != 1:
            return None
        dev = _windows_dos_device(letter)
        if not dev:
            return None
        return "veracrypt" in dev.lower()
    root = get_drive_root_path(letter_or_mount).rstrip("/") or "/"
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[1].rstrip("/") == root.rstrip("/"):
                    return "veracrypt" in parts[0].lower()
    except Exception:
        return None
    return None


def get_system_drives_info() -> Dict[str, Any]:
    """Obtém do sistema operacional as unidades montadas e letras livres (D: até Z:)."""
    mounted_drives: List[Dict[str, Any]] = []
    used_letters = set()

    is_windows = platform.system().lower().startswith("win")
    if is_windows:
        try:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for idx, ch in enumerate(string.ascii_uppercase):
                if bitmask & (1 << idx):
                    used_letters.add(ch)
        except Exception:
            pass

    try:
        for part in psutil.disk_partitions(all=True):
            mountpoint = part.mountpoint or ""
            if is_windows and len(mountpoint) >= 2 and mountpoint[1] == ":":
                letter = mountpoint[0].upper()
                used_letters.add(letter)
            usage_info: Dict[str, Any] = {}
            try:
                if os.path.isdir(mountpoint):
                    u = psutil.disk_usage(mountpoint)
                    usage_info = {
                        "total_bytes": u.total,
                        "used_bytes": u.used,
                        "free_bytes": u.free,
                        "percent": u.percent,
                    }
            except Exception:
                pass
            mounted_drives.append({
                "device": part.device,
                "mountpoint": mountpoint,
                "letter": mountpoint[0].upper() if (is_windows and len(mountpoint) >= 2 and mountpoint[1] == ":") else mountpoint,
                "fstype": part.fstype,
                **usage_info,
            })
    except Exception as exc:
        logger.debug(f"Aviso ao listar partições: {exc}")

    available_letters: List[str] = []
    if is_windows:
        for ch in string.ascii_uppercase[3:]:  # D..Z
            if ch not in used_letters:
                available_letters.append(ch)

    return {
        "mounted_drives": mounted_drives,
        "used_letters": sorted(list(used_letters)),
        "available_letters": available_letters,
    }


def is_device_path(volume_path: Optional[str]) -> bool:
    """True quando o volume é uma partição/dispositivo (e não um arquivo container)."""
    vp = str(volume_path or "").strip().strip('"')
    if not vp:
        return False
    low = vp.lower()
    return (
        low.startswith("\\device\\")
        or low.startswith("\\\\?\\volume{")
        or low.startswith("\\\\.\\")
        or low.startswith("/dev/")
    )


_PS_LIST_DEVICES = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = @()
foreach ($d in (Get-Disk)) {
  if ([string]$d.PartitionStyle -eq 'RAW') {
    $out += [pscustomobject]@{ kind='disk'; disk=[int]$d.Number; partition=0; size=[int64]$d.Size;
      model=[string]$d.FriendlyName; bus=[string]$d.BusType; letter=''; fs=''; label=''; guid=''; ptype='';
      is_system=[bool]$d.IsSystem; is_boot=[bool]$d.IsBoot; offline=[bool]$d.IsOffline }
    continue
  }
  foreach ($p in (Get-Partition -DiskNumber $d.Number)) {
    $v = $null; try { $v = $p | Get-Volume } catch {}
    $g = ($p.AccessPaths | Where-Object { $_ -like '\\?\Volume*' } | Select-Object -First 1)
    $out += [pscustomobject]@{ kind='partition'; disk=[int]$d.Number; partition=[int]$p.PartitionNumber; size=[int64]$p.Size;
      model=[string]$d.FriendlyName; bus=[string]$d.BusType; letter=([string]$p.DriveLetter).Trim([char]0).Trim();
      fs=[string]$v.FileSystem; label=[string]$v.FileSystemLabel; guid=[string]$g; ptype=[string]$p.Type;
      is_system=([bool]$p.IsSystem -or [bool]$p.IsBoot); is_boot=[bool]$p.IsBoot; offline=[bool]$d.IsOffline }
  }
}
ConvertTo-Json -InputObject @($out) -Depth 3 -Compress
"""


def _fmt_size(n: Any) -> str:
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} B"
        v /= 1024
    return ""


def list_block_devices(timeout_seconds: int = 30) -> Dict[str, Any]:
    """
    Lista partições e discos reais do host para montagem VeraCrypt de partição/dispositivo.
    Marca como `likely_veracrypt` o que o SO enxerga sem sistema de arquivos (RAW) — que é como
    uma partição/dispositivo criptografado pelo VeraCrypt aparece antes de ser montado.
    """
    is_windows = platform.system().lower().startswith("win")
    devices: List[Dict[str, Any]] = []

    if is_windows:
        ps = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
        if not ps:
            return {"success": False, "error": "PowerShell não encontrado para listar partições do Windows.", "devices": []}
        try:
            proc = subprocess.run(
                [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PS_LIST_DEVICES],
                capture_output=True, text=True, timeout=timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            raw = (proc.stdout or "").strip()
            items = json.loads(raw) if raw else []
            if isinstance(items, dict):
                items = [items]
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Tempo limite ({timeout_seconds}s) ao listar partições.", "devices": []}
        except Exception as exc:
            return {"success": False, "error": f"Falha ao listar partições: {exc}", "devices": []}

        for it in items or []:
            disk_n = int(it.get("disk", 0) or 0)
            part_n = int(it.get("partition", 0) or 0)
            dev_path = f"\\Device\\Harddisk{disk_n}\\Partition{part_n}"
            guid = str(it.get("guid") or "").strip()
            fs = str(it.get("fs") or "").strip()
            letter = str(it.get("letter") or "").strip()
            ptype = str(it.get("ptype") or "").strip()
            is_system = bool(it.get("is_system"))
            ptl = ptype.lower()
            # Só bloqueia o que sustenta o Windows em execução (C:/boot e EFI). RAW reservada/desconhecida pode ser escolhida.
            blocked = is_system or ptl == "system"
            reserved = ptl in ("reserved", "recovery")
            likely = (not fs) and (not letter) and not blocked and not reserved
            type_label = {
                "reserved": "Reservada Microsoft (MSR)",
                "recovery": "Recuperação do Windows",
                "system": "EFI",
                "unknown": "Tipo desconhecido",
            }.get(ptl, "")
            devices.append({
                "kind": it.get("kind") or "partition",
                "disk": disk_n,
                "partition": part_n,
                # Caminho estável (GUID do volume) quando existir; senão \Device\HarddiskN\PartitionM
                "path": guid or dev_path,
                "device_path": dev_path,
                "volume_guid": guid,
                "size_bytes": int(it.get("size", 0) or 0),
                "size_human": _fmt_size(it.get("size")),
                "model": str(it.get("model") or "").strip(),
                "bus": str(it.get("bus") or "").strip(),
                "letter": letter,
                "filesystem": fs,
                "label": str(it.get("label") or "").strip(),
                "partition_type": ptype,
                "type_label": type_label,
                "is_system": is_system,
                "selectable": not blocked,
                "likely_veracrypt": likely,
            })
    else:
        lsblk = shutil.which("lsblk")
        if not lsblk:
            return {"success": False, "error": "Comando 'lsblk' não encontrado para listar dispositivos.", "devices": []}
        try:
            proc = subprocess.run(
                [lsblk, "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT,MODEL"],
                capture_output=True, text=True, timeout=timeout_seconds,
            )
            data = json.loads(proc.stdout or "{}")
        except Exception as exc:
            return {"success": False, "error": f"Falha ao listar dispositivos: {exc}", "devices": []}

        def walk(nodes: List[Dict[str, Any]], model: str = "") -> None:
            for n in nodes or []:
                typ = str(n.get("type") or "")
                mdl = str(n.get("model") or model or "").strip()
                children = n.get("children") or []
                if typ in ("disk", "part") and not str(n.get("path") or "").startswith("/dev/loop"):
                    fs = str(n.get("fstype") or "").strip()
                    mp = str(n.get("mountpoint") or "").strip()
                    is_sys = mp in ("/", "/boot", "/boot/efi") or fs == "swap"
                    devices.append({
                        "kind": "disk" if typ == "disk" else "partition",
                        "path": n.get("path"),
                        "device_path": n.get("path"),
                        "volume_guid": "",
                        "size_bytes": int(n.get("size") or 0),
                        "size_human": _fmt_size(n.get("size")),
                        "model": mdl,
                        "bus": "",
                        "letter": mp,
                        "filesystem": fs,
                        "label": str(n.get("label") or "").strip(),
                        "partition_type": typ,
                        "is_system": is_sys,
                        "selectable": not is_sys and not (typ == "disk" and children),
                        "likely_veracrypt": (not fs) and (not mp) and not children,
                    })
                walk(children, mdl)

        walk(data.get("blockdevices") or [])

    devices.sort(key=lambda d: (not d.get("likely_veracrypt"), not d.get("selectable"), d.get("disk", 0), d.get("partition", 0)))
    return {"success": True, "platform": platform.system(), "devices": devices}


def get_veracrypt_status(custom_executable: Optional[str] = None) -> Dict[str, Any]:
    """Retorna o status real do VeraCrypt no host e as unidades disponíveis."""
    exe = find_veracrypt_executable(custom_executable)
    drives = get_system_drives_info()
    return {
        "installed": bool(exe),
        "executable_path": exe,
        "platform": platform.system(),
        "mounted_drives": drives["mounted_drives"],
        "used_letters": drives["used_letters"],
        "available_letters": drives["available_letters"],
    }


def parse_veracrypt_config(raw: Any) -> Dict[str, Any]:
    """Converte o campo veracrypt_config (dict ou JSON string) em dicionário estruturado."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        raw_str = raw.strip()
        if not raw_str:
            return {}
        try:
            parsed = json.loads(raw_str)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def sanitize_and_encrypt_config(
    incoming: Any,
    existing_raw: Any = None,
) -> Optional[str]:
    """
    Normaliza a configuração VeraCrypt e criptografa a senha com Fernet (repo_secrets).
    Se a senha não for reenviada na edição, preserva `password_enc` existente no banco.
    Retorna string JSON pronta para gravação na coluna `tasks.veracrypt_config`.
    """
    cfg = parse_veracrypt_config(incoming)
    existing = parse_veracrypt_config(existing_raw)

    if not cfg and not existing:
        return None

    enabled = bool(cfg.get("enabled", False))
    volume_path = str(cfg.get("volume_path") or existing.get("volume_path") or "").strip()
    volume_type = str(cfg.get("volume_type") or existing.get("volume_type") or "").strip().lower()
    if volume_type not in ("file", "device"):
        volume_type = "device" if is_device_path(volume_path) else "file"
    drive_letter = normalize_drive_letter(cfg.get("drive_letter") or existing.get("drive_letter") or "V")
    keyfile = str(cfg.get("keyfile") or "").strip()
    executable_path = str(cfg.get("executable_path") or "").strip()

    pim_raw = cfg.get("pim")
    pim_val: Optional[int] = None
    if pim_raw not in (None, "", 0, "0"):
        try:
            pim_int = int(pim_raw)
            if pim_int > 0:
                pim_val = pim_int
        except (ValueError, TypeError):
            pass

    readonly = bool(cfg.get("readonly", True))
    auto_dismount = bool(cfg.get("auto_dismount", True))
    force_dismount = bool(cfg.get("force_dismount", False))

    # Criptografar senha em repouso (nunca salvar em texto puro)
    plain_password = cfg.get("password")
    password_enc = cfg.get("password_enc") or existing.get("password_enc") or ""
    if plain_password is not None and str(plain_password) != "":
        password_enc = repo_secrets.encrypt(str(plain_password))
    elif cfg.get("clear_password") is True:
        password_enc = ""

    stored = {
        "enabled": enabled,
        "volume_path": volume_path,
        "volume_type": volume_type,
        "drive_letter": drive_letter,
        "password_enc": password_enc,
        "pim": pim_val,
        "keyfile": keyfile,
        "readonly": readonly,
        "auto_dismount": auto_dismount,
        "force_dismount": force_dismount,
        "executable_path": executable_path,
    }
    return json.dumps(stored, ensure_ascii=False)


def mask_config_for_client(raw: Any) -> Dict[str, Any]:
    """Remove `password_enc` e `password` antes de retornar para a interface web, adicionando `has_password`."""
    cfg = parse_veracrypt_config(raw)
    if not cfg:
        return {
            "enabled": False,
            "volume_path": "",
            "volume_type": "file",
            "drive_letter": "V",
            "has_password": False,
            "pim": None,
            "keyfile": "",
            "readonly": True,
            "auto_dismount": True,
            "force_dismount": False,
            "executable_path": "",
            "currently_mounted": False,
        }

    drive_letter = normalize_drive_letter(cfg.get("drive_letter") or "V")
    has_pw = bool(cfg.get("password_enc") or cfg.get("password"))
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "volume_path": str(cfg.get("volume_path") or ""),
        "volume_type": str(cfg.get("volume_type") or ("device" if is_device_path(cfg.get("volume_path")) else "file")),
        "drive_letter": drive_letter,
        "mount_root": get_drive_root_path(drive_letter),
        "has_password": has_pw,
        "pim": cfg.get("pim"),
        "keyfile": str(cfg.get("keyfile") or ""),
        "readonly": bool(cfg.get("readonly", True)),
        "auto_dismount": bool(cfg.get("auto_dismount", True)),
        "force_dismount": bool(cfg.get("force_dismount", False)),
        "executable_path": str(cfg.get("executable_path") or ""),
        "currently_mounted": is_drive_mounted(drive_letter) if drive_letter else False,
    }


def decrypt_config_password(cfg: Dict[str, Any]) -> str:
    """Recupera a senha descriptografada em memória apenas no instante da montagem."""
    if cfg.get("password"):
        return str(cfg["password"])
    enc = cfg.get("password_enc")
    if enc:
        plain = repo_secrets.decrypt(str(enc))
        if plain is not None:
            return plain
    return ""


def mount_volume(cfg_input: Any, timeout_seconds: int = 60) -> Dict[str, Any]:
    """
    Monta um volume VeraCrypt real usando o CLI oficial do VeraCrypt.
    Se a unidade já estiver montada e acessível, retorna sucesso informando `already_mounted=True`.
    """
    cfg = parse_veracrypt_config(cfg_input)
    volume_path = str(cfg.get("volume_path") or "").strip().strip('"')
    drive_letter = normalize_drive_letter(cfg.get("drive_letter") or "V")
    keyfile = str(cfg.get("keyfile") or "").strip().strip('"')
    readonly = bool(cfg.get("readonly", True))
    pim = cfg.get("pim")
    custom_exe = str(cfg.get("executable_path") or "").strip() or None

    if not volume_path:
        return {
            "success": False,
            "error": "Volume VeraCrypt não informado (arquivo .hc / .tc ou partição/dispositivo).",
        }

    if not drive_letter:
        return {
            "success": False,
            "error": "Letra da unidade de montagem (ex: V:) não informada.",
        }

    mount_root = get_drive_root_path(drive_letter)

    # Verificar se já está montada (e se a letra realmente pertence a um volume VeraCrypt)
    if is_drive_mounted(drive_letter) and is_veracrypt_drive(drive_letter) is False:
        return {
            "success": False,
            "error": (
                f"A unidade {mount_root} está ocupada por outro disco que não é um volume VeraCrypt. "
                "Escolha outra letra de montagem na tarefa para não fazer backup da unidade errada."
            ),
        }
    if is_drive_mounted(drive_letter):
        logger.info(f"🔓 [VeraCrypt] Unidade {mount_root} já se encontra montada no sistema.")
        return {
            "success": True,
            "already_mounted": True,
            "mounted_by_gboc": False,
            "drive_letter": drive_letter,
            "mount_root": mount_root,
            "volume_path": volume_path,
            "message": f"Unidade {mount_root} já estava montada e pronta para leitura.",
        }

    # Validar existência do container quando for um caminho de arquivo local (e não \Device\Harddisk...)
    if not is_device_path(volume_path) and str(cfg.get("volume_type") or "").lower() != "device":
        if not os.path.exists(volume_path):
            return {
                "success": False,
                "error": f"Arquivo de volume VeraCrypt não encontrado no disco: {volume_path}",
            }

    if keyfile and not os.path.exists(keyfile):
        return {
            "success": False,
            "error": f"Arquivo-chave (Keyfile) do VeraCrypt não encontrado: {keyfile}",
        }

    exe = find_veracrypt_executable(custom_exe)
    if not exe:
        return {
            "success": False,
            "error": (
                "Executável do VeraCrypt não encontrado no servidor/agente. "
                "Instale o VeraCrypt em 'C:\\Program Files\\VeraCrypt\\VeraCrypt.exe' "
                "ou informe o caminho do executável nas opções avançadas da tarefa."
            ),
        }

    password = decrypt_config_password(cfg)
    if not password and not keyfile:
        return {
            "success": False,
            "error": "Senha ou Keyfile do volume VeraCrypt é obrigatório para montar a unidade.",
        }

    is_windows = platform.system().lower().startswith("win")
    cmd: List[str] = [exe]

    if is_windows:
        cmd.extend(["/volume", volume_path, "/letter", drive_letter])
        if password:
            cmd.extend(["/password", password])
        if pim not in (None, "", 0, "0"):
            try:
                pim_int = int(pim)
                if pim_int > 0:
                    cmd.extend(["/pim", str(pim_int)])
            except (ValueError, TypeError):
                pass
        if keyfile:
            cmd.extend(["/keyfile", keyfile])
        if readonly:
            cmd.extend(["/mountoption", "ro"])
        cmd.extend(["/quit", "/silent"])
    else:
        os.makedirs(mount_root, exist_ok=True)
        cmd.extend(["--text", "--non-interactive", f"--password={password}"])
        if pim not in (None, "", 0, "0"):
            cmd.append(f"--pim={int(pim)}")
        if keyfile:
            cmd.append(f"--keyfiles={keyfile}")
        if readonly:
            cmd.extend(["--mount-options=ro"])
        cmd.extend([volume_path, mount_root])

    logger.info(f"🔐 [VeraCrypt] Montando volume '{volume_path}' na unidade {mount_root} (readonly={readonly})...")
    t0 = time.monotonic()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if is_windows else 0,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Tempo limite excedido ({timeout_seconds}s) ao montar o volume VeraCrypt '{volume_path}'. Verifique se a senha/PIM estão corretos.",
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Erro ao executar VeraCrypt ({exe}): {exc}",
        }

    # Aguardar propagação do driver de volume no Windows (até 3 segundos)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if is_drive_mounted(drive_letter):
            break
        time.sleep(0.2)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if is_drive_mounted(drive_letter):
        logger.info(f"✅ [VeraCrypt] Volume '{volume_path}' montado com sucesso em {mount_root} ({elapsed_ms} ms)")
        return {
            "success": True,
            "already_mounted": False,
            "mounted_by_gboc": True,
            "drive_letter": drive_letter,
            "mount_root": mount_root,
            "volume_path": volume_path,
            "elapsed_ms": elapsed_ms,
            "message": f"Volume VeraCrypt montado com sucesso em {mount_root} ({elapsed_ms} ms).",
        }

    stderr_clean = (proc.stderr or proc.stdout or "").strip()
    detail = f" (código {proc.returncode}: {stderr_clean})" if stderr_clean else f" (código de saída {proc.returncode})"
    return {
        "success": False,
        "error": (
            f"Falha ao montar o volume VeraCrypt '{volume_path}' na unidade {mount_root}{detail}. "
            "Verifique se a senha, o PIM, o Keyfile e a letra da unidade estão corretos."
        ),
    }


def dismount_volume(
    drive_letter_or_mount: str,
    force: bool = False,
    custom_executable: Optional[str] = None,
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """Desmonta uma unidade VeraCrypt montada no sistema operacional."""
    drive_letter = normalize_drive_letter(drive_letter_or_mount)
    if not drive_letter:
        return {"success": False, "error": "Letra da unidade VeraCrypt não informada para desmontagem."}

    mount_root = get_drive_root_path(drive_letter)
    if not is_drive_mounted(drive_letter):
        return {
            "success": True,
            "already_dismounted": True,
            "drive_letter": drive_letter,
            "mount_root": mount_root,
            "message": f"Unidade {mount_root} já está desmontada.",
        }

    exe = find_veracrypt_executable(custom_executable)
    if not exe:
        return {
            "success": False,
            "error": "Executável do VeraCrypt não encontrado para desmontar a unidade.",
        }

    is_windows = platform.system().lower().startswith("win")
    if is_windows:
        cmd = [exe, "/dismount", drive_letter, "/quit", "/silent"]
        if force:
            cmd.append("/force")
    else:
        cmd = [exe, "--text", "--non-interactive", "-d", mount_root]
        if force:
            cmd.append("--force")

    logger.info(f"🔒 [VeraCrypt] Desmontando unidade {mount_root} (force={force})...")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if is_windows else 0,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Tempo limite excedido ao desmontar a unidade {mount_root}.",
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Erro ao desmontar unidade VeraCrypt {mount_root}: {exc}",
        }

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if not is_drive_mounted(drive_letter):
            break
        time.sleep(0.2)

    if not is_drive_mounted(drive_letter):
        logger.info(f"✅ [VeraCrypt] Unidade {mount_root} desmontada com segurança.")
        return {
            "success": True,
            "drive_letter": drive_letter,
            "mount_root": mount_root,
            "message": f"Unidade VeraCrypt {mount_root} desmontada com segurança.",
        }

    # Se não desmontou sem force, tentar com /force quando arquivos em cache do SO segurarem o handle
    if not force:
        logger.warning(f"⚠️ [VeraCrypt] Unidade {mount_root} permaneceu ocupada; tentando desmontagem forçada (/force)...")
        return dismount_volume(
            drive_letter,
            force=True,
            custom_executable=custom_executable,
            timeout_seconds=timeout_seconds,
        )

    stderr_clean = (proc.stderr or proc.stdout or "").strip()
    return {
        "success": False,
        "error": f"Não foi possível desmontar a unidade {mount_root} (código {proc.returncode}). {stderr_clean}".strip(),
    }


# ============================================================
# Uso do volume pelas tarefas de backup
# - Várias tarefas podem usar o mesmo volume ao mesmo tempo: só desmonta quando a última terminar.
# - Só desmonta automaticamente o que o próprio GBOC montou (volume aberto pelo usuário fica montado).
# ============================================================

_USAGE_LOCK = threading.Lock()
_USAGE: Dict[str, Dict[str, Any]] = {}


def get_volume_usage(letter_or_mount: Optional[str]) -> Dict[str, Any]:
    """Quantas tarefas estão usando a unidade agora e se foi o GBOC que montou."""
    key = normalize_drive_letter(letter_or_mount)
    with _USAGE_LOCK:
        info = _USAGE.get(key) or {}
        return {
            "drive_letter": key,
            "in_use": int(info.get("count", 0)),
            "mounted_by_gboc": bool(info.get("owned", False)),
            "task_ids": sorted(list(info.get("tasks", set()))),
        }


def acquire_for_task(cfg_input: Any, task_id: Optional[int] = None, timeout_seconds: int = 60) -> Dict[str, Any]:
    """Monta (se preciso) e registra a tarefa como usuária do volume."""
    cfg = parse_veracrypt_config(cfg_input)
    key = normalize_drive_letter(cfg.get("drive_letter") or "V")
    with _USAGE_LOCK:
        info = _USAGE.get(key)
        if info and info.get("count", 0) > 0 and is_drive_mounted(key):
            info["count"] += 1
            if task_id is not None:
                info["tasks"].add(int(task_id))
            root = get_drive_root_path(key)
            logger.info(f"🔓 [VeraCrypt] Unidade {root} já montada e em uso por outra tarefa — compartilhando ({info['count']} em uso).")
            return {
                "success": True,
                "already_mounted": True,
                "mounted_by_gboc": bool(info.get("owned")),
                "drive_letter": key,
                "mount_root": root,
                "message": f"Unidade {root} já montada e em uso por outra tarefa.",
            }

        res = mount_volume(cfg, timeout_seconds=timeout_seconds)
        if not res.get("success"):
            return res
        _USAGE[key] = {
            "count": 1,
            "owned": bool(res.get("mounted_by_gboc")),
            "tasks": {int(task_id)} if task_id is not None else set(),
        }
        return res


def release_for_task(cfg_input: Any, task_id: Optional[int] = None) -> Dict[str, Any]:
    """Libera o uso da tarefa; desmonta quando for a última e o volume tiver sido montado pelo GBOC."""
    cfg = parse_veracrypt_config(cfg_input)
    key = normalize_drive_letter(cfg.get("drive_letter") or "V")
    root = get_drive_root_path(key)
    with _USAGE_LOCK:
        info = _USAGE.get(key)
        if not info:
            return {"success": True, "dismounted": False, "drive_letter": key, "message": f"Unidade {root} não estava registrada para esta tarefa."}
        info["count"] = max(0, int(info.get("count", 0)) - 1)
        if task_id is not None:
            info["tasks"].discard(int(task_id))
        if info["count"] > 0:
            logger.info(f"🔓 [VeraCrypt] Unidade {root} mantida montada: ainda em uso por {info['count']} tarefa(s).")
            return {"success": True, "dismounted": False, "drive_letter": key, "message": f"Unidade {root} ainda em uso por outra tarefa."}

        owned = bool(info.get("owned"))
        _USAGE.pop(key, None)
        if not owned:
            logger.info(f"🔓 [VeraCrypt] Unidade {root} já estava montada antes do backup — mantida montada.")
            return {"success": True, "dismounted": False, "drive_letter": key, "message": f"Unidade {root} já estava montada antes do backup e foi mantida."}
        if not bool(cfg.get("auto_dismount", True)):
            return {"success": True, "dismounted": False, "drive_letter": key, "message": f"Desmontagem automática desativada: unidade {root} mantida montada."}

        res = dismount_volume(
            key,
            force=bool(cfg.get("force_dismount", False)),
            custom_executable=str(cfg.get("executable_path") or "").strip() or None,
        )
        res["dismounted"] = bool(res.get("success"))
        return res

