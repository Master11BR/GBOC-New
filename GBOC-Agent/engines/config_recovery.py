"""
GBOC Agent — recuperação automática da configuração (repositórios, tarefas, chaves e configurações).

Para reinstalar o Agente do zero (computador novo, disco perdido) basta a nuvem + a CHAVE DE RECUPERAÇÃO:

  * O pacote de recuperação é a configuração completa do Agente, INCLUSIVE as chaves dos repositórios
    (senha do motor e chave secreta da nuvem), criptografado com AES-256-GCM. A chave AES é derivada da
    chave de recuperação (frase definida pelo administrador) com scrypt. Sem a frase o pacote é inútil.
  * A chave de recuperação fica guardada neste computador criptografada (mesma proteção das chaves de
    nuvem, data/.repo_secrets.key) e NUNCA é gravada na nuvem nem enviada por e-mail.
  * O pacote é enviado para todos os repositórios do motor nativo em  gboc-dr/<agente>/<data>.gbocdr
    sempre que a configuração muda (verificação a cada 5 min) e conferido 1x por dia; ficam as últimas 30
    versões. Opcionalmente, o pacote criptografado também é enviado por e-mail quando muda.
  * Recuperação: instalação limpa → Primeiro acesso → Config Export/Import → Recuperar da nuvem
    (dados do bucket + chave de recuperação) ou do arquivo recebido por e-mail.

Formato do arquivo .gbocdr:  "GBOCDR01" | log2(N) | r | p | salt(16) | nonce(12) | AES-GCM(zlib(JSON))
(o cabeçalho inteiro é autenticado como dado associado).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import struct
import threading
import time
import zlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SETTINGS_KEY = "config_recovery"
MAGIC = b"GBOCDR01"
DR_PREFIX = "gboc-dr"
EXT = ".gbocdr"
KEEP_VERSIONS = 30
MIN_PASSPHRASE = 12
CHECK_INTERVAL_S = 300          # procura alterações a cada 5 min
DAILY_S = 24 * 3600
EMAIL_MAX_BYTES = 15 * 1024 * 1024
_SCRYPT = (15, 8, 1)            # N = 2^15 (32 MiB de memória), r, p
NATIVE_ENGINES = ("native", "gboc_native", "gboc")

_lock = threading.Lock()        # um envio por vez (automático x "Enviar agora")
_thread: Optional[threading.Thread] = None


# ─── Criptografia do pacote ───────────────────────────────────────

def _derive(passphrase: str, salt: bytes, n_log2: int, r: int, p: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=1 << n_log2, r=r, p=p).derive(passphrase.encode("utf-8"))


def seal(payload: Dict[str, Any], passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    n_log2, r, p = _SCRYPT
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + struct.pack("<BBB", n_log2, r, p) + salt + nonce
    raw = zlib.compress(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"), 9)
    return header + AESGCM(_derive(passphrase, salt, n_log2, r, p)).encrypt(nonce, raw, header)


def open_package(blob: bytes, passphrase: str) -> Dict[str, Any]:
    """Descriptografa um .gbocdr. ValueError com mensagem clara se não for um pacote ou a chave estiver errada."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    hlen = len(MAGIC) + 3 + 16 + 12
    if len(blob) <= hlen or not blob.startswith(MAGIC):
        raise ValueError("O arquivo não é um pacote de recuperação do GBOC (.gbocdr)")
    n_log2, r, p = struct.unpack("<BBB", blob[8:11])
    if not (10 <= n_log2 <= 22 and 1 <= r <= 32 and 1 <= p <= 16):
        raise ValueError("Cabeçalho do pacote de recuperação inválido")
    salt, nonce, header = blob[11:27], blob[27:39], blob[:hlen]
    try:
        raw = AESGCM(_derive(passphrase, salt, n_log2, r, p)).decrypt(nonce, blob[hlen:], header)
    except InvalidTag:
        raise ValueError("Chave de recuperação incorreta (ou pacote corrompido)")
    return json.loads(zlib.decompress(raw).decode("utf-8"))


# ─── Preferências (tabela settings) ───────────────────────────────

def _core():
    from shared_core import get_shared_core
    return get_shared_core()


def load_settings() -> Dict[str, Any]:
    try:
        with _core().get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key = %s", (SETTINGS_KEY,))
            row = cur.fetchone()
        if row and row[0]:
            v = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return v if isinstance(v, dict) else {}
    except Exception as e:
        logger.debug(f"[RECUPERAÇÃO] preferências indisponíveis: {e}")
    return {}


def _save_settings(s: Dict[str, Any]) -> None:
    val = json.dumps(s, default=str)
    with _core().get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s",
                    (SETTINGS_KEY, val, val))
        conn.commit()


def _update_settings(**kw) -> Dict[str, Any]:
    s = load_settings()
    s.update(kw)
    _save_settings(s)
    return s


def _passphrase(s: Dict[str, Any]) -> str:
    from engines import repo_secrets
    return repo_secrets.decrypt(s.get("passphrase_enc")) or "" if s.get("passphrase_enc") else ""


def configure(enabled: bool, passphrase: Optional[str] = None, email_enabled: bool = False,
              email_to: str = "") -> Dict[str, Any]:
    """Salva as preferências. passphrase vazia/None mantém a chave atual."""
    from engines import repo_secrets
    s = load_settings()
    if passphrase:
        if len(passphrase) < MIN_PASSPHRASE:
            raise ValueError(f"A chave de recuperação precisa ter pelo menos {MIN_PASSPHRASE} caracteres")
        s["passphrase_enc"] = repo_secrets.encrypt(passphrase)
        s["passphrase_set_at"] = _now()
        s.pop("last_hash", None)            # chave nova: envia um pacote novo na próxima verificação
        s.pop("last_email_hash", None)
    if enabled and not s.get("passphrase_enc"):
        raise ValueError("Defina a chave de recuperação para ativar")
    s.update(enabled=bool(enabled), email_enabled=bool(email_enabled), email_to=(email_to or "").strip())
    _save_settings(s)
    return public_status(s)


def public_status(s: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    s = s if s is not None else load_settings()
    dests = []
    try:
        dests = [{"name": d["name"], "type": d["type"]} for d in _destinations()]
    except Exception as e:
        logger.debug(f"[RECUPERAÇÃO] destinos: {e}")
    d = s.get("destination") or {}
    return {
        "destination": {k: d.get(k) for k in ("type", "endpoint", "bucket", "region", "access_key", "path")} | {
            "secret_set": bool(d.get("secret_enc"))} if d else None,
        "enabled": bool(s.get("enabled")),
        "passphrase_set": bool(s.get("passphrase_enc")),
        "passphrase_set_at": s.get("passphrase_set_at"),
        "email_enabled": bool(s.get("email_enabled")),
        "email_to": s.get("email_to") or "",
        "agent": agent_name(),
        "keep_versions": KEEP_VERSIONS,
        "destinations": dests,
        "last_upload_at": s.get("last_upload_at"),
        "last_check_at": s.get("last_check_at"),
        "last_result": s.get("last_result"),
        "last_email_at": s.get("last_email_at"),
    }


# ─── Pacote e destinos ────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def agent_name() -> str:
    name = os.environ.get("GBOC_AGENT_ID") or socket.gethostname() or "agente"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "agente"


def _duplicati_section() -> Optional[Dict[str, Any]]:
    """Conexão com o Duplicati Server + definição completa de cada job (com destino e passphrase).
    None quando o Duplicati não está configurado neste Agente."""
    try:
        from core.integrations.duplicati_native import get_duplicati_native_service
        svc = get_duplicati_native_service()
        if not svc.is_configured():
            return None
        c = svc.load_config()
        out = svc.export_all_backups()
        out["connection"] = {"base_url": c.base_url, "username": c.username, "password": c.password,
                             "verify_tls": c.verify_tls, "timeout_seconds": c.timeout_seconds}
        return out
    except Exception as e:
        logger.warning(f"[RECUPERAÇÃO] jobs do Duplicati não incluídos: {e}")
        return {"jobs": [], "errors": [f"{type(e).__name__}: {e}"]}


def _duplicati_stable(d: Optional[Dict[str, Any]]) -> Any:
    """Parte dos jobs que identifica alteração (sem datas da última execução/próxima execução)."""
    if not d:
        return None
    jobs = []
    for j in d.get("jobs") or []:
        b = {k: v for k, v in (j.get("Backup") or {}).items() if k not in ("ID", "DBPath", "Metadata")}
        sc = {k: v for k, v in (j.get("Schedule") or {}).items() if k not in ("ID", "LastRun", "Time")} \
            if isinstance(j.get("Schedule"), dict) else None
        jobs.append({"Backup": b, "Schedule": sc})
    return sorted(jobs, key=lambda x: str(x["Backup"].get("Name")))


def build_payload() -> Tuple[Dict[str, Any], str]:
    """(conteúdo do pacote, hash da configuração — sem a data, para detectar alteração)."""
    from engines.config_manager import export_config, _Enc
    cfg = export_config(include_sensitive=True, include_secrets=True)
    dup = _duplicati_section()
    stable = {k: v for k, v in cfg.items() if k != "_meta"}
    stable["_duplicati"] = _duplicati_stable(dup)
    digest = hashlib.sha256(json.dumps(stable, cls=_Enc, sort_keys=True).encode("utf-8")).hexdigest()
    s = load_settings()
    payload = {"_gbocdr": {"format": 1, "agent": agent_name(), "created_at": _now(), "config_hash": digest},
               "config": json.loads(json.dumps(cfg, cls=_Enc)),
               # preferências da recuperação (o pacote é criptografado: o destino próprio vai com a chave secreta)
               "recovery": {"destination": _dedicated_source(s), "email_enabled": bool(s.get("email_enabled")),
                            "email_to": s.get("email_to") or ""}}
    if dup is not None:
        payload["duplicati"] = dup
    return payload, digest


def _destinations() -> List[Dict[str, Any]]:
    """Repositórios do motor nativo (ativos), um por local físico (mesmo bucket/pasta só recebe uma vez)."""
    rm = getattr(_core(), "repository_manager", None)
    if rm is None:
        from engines.repository_manager import RepositoryManager
        rm = RepositoryManager(_core())
    out, seen = [], set()
    for r in rm.list_repositories():
        if str(r.get("engine") or "").lower() not in NATIVE_ENGINES or r.get("enabled") is False:
            continue
        rtype = str(r.get("type") or "local").lower()
        loc = (rtype, str(r.get("endpoint") or ""), str(r.get("bucket") or r.get("path") or ""),
               str(r.get("prefix") or ""), str(r.get("aws_access_key") or r.get("access_key") or r.get("b2_account_id") or ""))
        if loc in seen:
            continue
        seen.add(loc)
        out.append({"id": r.get("id"), "name": r.get("name"), "type": rtype, "repo": r})
    ext = _dedicated_source()
    if ext:                                      # destino próprio: vale para qualquer motor (restic, Kopia, Duplicati...)
        label = ext.get("bucket") or ext.get("path") or ""
        out.insert(0, {"id": None, "name": f"Destino próprio ({label})", "type": ext.get("type") or "s3", "source": ext})
    return out


def _dedicated_source(s: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Destino próprio configurado (com a chave secreta descriptografada) ou None."""
    from engines import repo_secrets
    d = (s if s is not None else load_settings()).get("destination") or {}
    if not d or not (d.get("bucket") or d.get("path")):
        return None
    src = {k: d.get(k) for k in ("type", "endpoint", "bucket", "region", "access_key", "path")}
    if d.get("secret_enc"):
        src["secret_key"] = repo_secrets.decrypt(d["secret_enc"]) or ""
    return src


def set_destination(dest: Optional[Dict[str, Any]], test: bool = True) -> Dict[str, Any]:
    """Grava (ou remove, dest vazio) o destino próprio do pacote. Chave secreta vazia/máscara mantém a atual.
    test=True: confere acesso gravando, lendo e apagando um arquivo de teste antes de salvar."""
    from engines import repo_secrets
    s = load_settings()
    if not dest or not (str(dest.get("bucket") or "").strip() or str(dest.get("path") or "").strip()):
        s.pop("destination", None)
        _save_settings(s)
        return public_status(s)
    old = s.get("destination") or {}
    new = {k: (str(dest.get(k) or "").strip() or None) for k in ("type", "endpoint", "bucket", "region", "access_key", "path")}
    new["type"] = (new["type"] or "s3").lower()
    secret = str(dest.get("secret_key") or "")
    if secret and secret != repo_secrets.MASK:
        new["secret_enc"] = repo_secrets.encrypt(secret)
    elif old.get("secret_enc"):
        new["secret_enc"] = old["secret_enc"]
    if test:
        be = backend_from_source(_dedicated_source({"destination": new}) or {})
        probe = f"{DR_PREFIX}/.teste-{int(time.time())}"
        _put(be, probe, b"gboc")
        try:
            if _get(be, probe) != b"gboc":
                raise RuntimeError("leitura do arquivo de teste não confere")
        finally:
            try:
                be.delete_file(probe)
            except Exception:
                pass
    s["destination"] = new
    s.pop("last_verify_ts", None)                  # próxima verificação envia o pacote ao destino novo
    _save_settings(s)
    return public_status(s)


def _backend_for(dest: Dict[str, Any]):
    from engines.repository_manager import RepositoryManager
    if dest.get("source"):
        return backend_from_source(dest["source"])
    rm = getattr(_core(), "repository_manager", None) or RepositoryManager(_core())
    return rm._create_backend_from_config(dict(dest["repo"]))


def _put(be, name: str, data: bytes) -> None:
    from native_engine.store_v4 import _backend_put
    r = _backend_put(be, name, data)
    if not r.get("success", False):
        raise RuntimeError(r.get("error") or r.get("message") or "falha no envio")


def _get(be, name: str) -> bytes:
    from native_engine.store_v4 import _backend_get
    return _backend_get(be, name)


def list_packages(be, agent: Optional[str] = None) -> List[Dict[str, Any]]:
    """Pacotes no destino (mais novo primeiro). agent=None: de todos os agentes."""
    sub = f"{DR_PREFIX}/{agent}" if agent else DR_PREFIX
    names = [str(f).replace("\\", "/") for f in (be.list_files(sub) or [])]
    out = []
    for n in names:
        if not n.endswith(EXT):
            continue
        parts = n.split("/")
        if len(parts) < 3 or parts[0] != DR_PREFIX:
            continue
        out.append({"name": n, "agent": parts[1], "file": parts[-1], "created_at": _ts_from_name(parts[-1])})
    return sorted(out, key=lambda x: x["file"], reverse=True)


def _ts_from_name(fname: str) -> str:
    m = re.match(r"(\d{8})T(\d{6})Z", fname)
    if not m:
        return ""
    d, t = m.groups()
    return f"{d[:4]}-{d[4:6]}-{d[6:]}T{t[:2]}:{t[2:4]}:{t[4:]}+00:00"


def _rotate(be, agent: str) -> int:
    removed = 0
    for p in list_packages(be, agent)[KEEP_VERSIONS:]:
        try:
            if (be.delete_file(p["name"]) or {}).get("success", False):
                removed += 1
        except Exception as e:      # bucket com Object Lock: a versão some quando a retenção vencer
            logger.debug(f"[RECUPERAÇÃO] não removeu {p['name']}: {e}")
    return removed


# ─── E-mail (somente o pacote criptografado, nunca a chave) ──────

def _email_targets(s: Dict[str, Any]) -> List[str]:
    raw = s.get("email_to") or ""
    if not raw:
        try:
            from engines.notification_service import _load_notification_settings
            raw = _load_notification_settings().get("email_to", "") or ""
        except Exception:
            raw = ""
    return [e.strip() for e in re.split(r"[,;\s]+", raw) if "@" in e]


def _load_smtp() -> Optional[Dict[str, Any]]:
    """SMTP do Agente (tabela com coluna server ou host — engines/smtp_store.py)."""
    from engines import smtp_store
    return smtp_store.load_from_core()


def send_email(blob: bytes, fname: str, s: Dict[str, Any], payload_meta: Dict[str, Any]) -> Dict[str, Any]:
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    to = _email_targets(s)
    if not to:
        return {"sent": False, "error": "Nenhum destinatário (informe o e-mail ou configure Notificações)"}
    if len(blob) > EMAIL_MAX_BYTES:
        return {"sent": False, "error": f"Pacote grande demais para e-mail ({len(blob) // 1024} KB)"}
    smtp = _load_smtp()
    if not smtp or not smtp.get("server") or not smtp.get("from_email"):
        return {"sent": False, "error": "SMTP não configurado"}
    agent = payload_meta.get("agent") or agent_name()
    msg = MIMEMultipart()
    msg["From"] = f"{smtp.get('from_name') or 'GBOC'} <{smtp['from_email']}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = f"GBOC — pacote de recuperação da configuração ({agent})"
    body = (
        f"Pacote de recuperação da configuração do Agente GBOC \"{agent}\" gerado em {payload_meta.get('created_at')}.\n\n"
        "Guarde este e-mail. O anexo contém a configuração completa (repositórios, tarefas e as chaves dos "
        "repositórios) CRIPTOGRAFADA com AES-256. Ele só pode ser aberto com a CHAVE DE RECUPERAÇÃO, que NÃO "
        "está neste e-mail e nunca é enviada pelo sistema — guarde-a em local separado (cofre de senhas).\n\n"
        "Para recuperar em uma instalação limpa: instale o Agente, crie o administrador no Primeiro acesso e "
        "abra Config Export/Import > Recuperação > Recuperar de arquivo; selecione o anexo e informe a chave "
        "de recuperação. A mesma cópia também fica na nuvem, em gboc-dr/ dentro do bucket dos repositórios do "
        "motor nativo.\n"
    )
    msg.attach(MIMEText(body, "plain", "utf-8"))
    att = MIMEApplication(blob, Name=fname)
    att["Content-Disposition"] = f'attachment; filename="{fname}"'
    msg.attach(att)
    try:
        from engines import smtp_store
        smtp_store.deliver(smtp, to, msg, timeout=60)     # 465 = SSL direto; demais portas = STARTTLS
        return {"sent": True, "to": to}
    except Exception as e:
        from engines import smtp_store
        return {"sent": False, "error": smtp_store.friendly_error(e)}


# ─── Envio ────────────────────────────────────────────────────────

def run_backup(force: bool = False, reason: str = "manual") -> Dict[str, Any]:
    """Gera o pacote e envia para os destinos se a configuração mudou (ou force/verificação diária).
    Retorna o resultado (também gravado em last_result)."""
    with _lock:
        s = load_settings()
        if not s.get("enabled") and not force:
            return {"ok": False, "skipped": "recuperação automática desativada"}
        phrase = _passphrase(s)
        if not phrase:
            return {"ok": False, "error": "Chave de recuperação não definida (ou data/.repo_secrets.key trocada)"}
        payload, digest = build_payload()
        changed = digest != s.get("last_hash")
        dests = _destinations()
        agent = agent_name()
        now_ts = time.time()
        daily_due = now_ts - float(s.get("last_verify_ts") or 0) >= DAILY_S
        result: Dict[str, Any] = {"ok": True, "at": _now(), "reason": reason, "changed": changed,
                                  "destinations": [], "uploaded": 0}
        if not dests:
            result.update(ok=False, error="Nenhum destino: configure o destino próprio ou um repositório do motor nativo")
            _update_settings(last_check_at=_now(), last_result=result)
            return result
        if not (changed or force or daily_due):
            _update_settings(last_check_at=_now())
            return {"ok": True, "skipped": "sem alterações", "at": _now()}

        fname = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{digest[:8]}{EXT}"
        remote = f"{DR_PREFIX}/{agent}/{fname}"
        blob = seal(payload, phrase)
        for d in dests:
            item = {"repository": d["name"], "ok": False}
            try:
                be = _backend_for(d)
                existing = list_packages(be, agent)
                # Sem alteração: só envia onde o pacote atual ainda não existe (repositório novo, bucket limpo)
                if not (changed or force) and existing and existing[0]["file"].endswith(f"-{digest[:8]}{EXT}"):
                    item.update(ok=True, action="já atualizado")
                else:
                    _put(be, remote, blob)
                    if _get(be, remote) != blob:            # confere o que foi gravado
                        raise RuntimeError("conteúdo gravado difere do enviado")
                    item.update(ok=True, action="enviado", removed_old=_rotate(be, agent))
                    result["uploaded"] += 1
            except Exception as e:
                item["error"] = f"{type(e).__name__}: {e}"[:300]
                logger.warning(f"[RECUPERAÇÃO] falha ao enviar pacote para '{d['name']}': {item['error']}")
            result["destinations"].append(item)
        result["ok"] = all(i["ok"] for i in result["destinations"])
        upd: Dict[str, Any] = {"last_check_at": _now(), "last_result": result, "last_attempt_ts": now_ts}
        if result["ok"] or result["uploaded"]:
            upd["last_hash"] = digest        # destino com falha é tentado de novo na conferência (1x/hora)
        if result["ok"]:
            upd["last_verify_ts"] = now_ts
        if result["uploaded"]:
            upd["last_upload_at"] = _now()
            upd["last_package"] = remote
        if s.get("email_enabled") and (digest != s.get("last_email_hash") or (force and reason == "manual")):
            em = send_email(blob, fname, s, payload["_gbocdr"])
            result["email"] = em
            if em.get("sent"):
                upd.update(last_email_hash=digest, last_email_at=_now())
            else:
                logger.warning(f"[RECUPERAÇÃO] e-mail do pacote não enviado: {em.get('error')}")
        _update_settings(**upd)
        logger.info(f"[RECUPERAÇÃO] pacote de configuração ({reason}): {result['uploaded']} destino(s) atualizado(s)"
                    f"{'' if result['ok'] else ' — com falhas'}")
        return result


def _tick(pending: Optional[str]) -> Optional[str]:
    """Uma verificação automática. Retorna o hash pendente (alteração vista, aguardando estabilizar)."""
    s = load_settings()
    if not (s.get("enabled") and s.get("passphrase_enc")):
        return None
    _, digest = build_payload()
    if digest != s.get("last_hash"):
        if pending == digest:                       # nada mudou desde a verificação anterior: envia
            run_backup(reason="alteração")
            return None
        return digest
    daily_due = time.time() - float(s.get("last_verify_ts") or 0) >= DAILY_S
    if daily_due and time.time() - float(s.get("last_attempt_ts") or 0) >= 3600:
        run_backup(reason="diária")                 # também repete, de hora em hora, destino que falhou
    return None


def _loop() -> None:
    time.sleep(90)                                  # deixa o Agente terminar de subir
    pending: Optional[str] = None
    while True:
        try:
            pending = _tick(pending)
        except Exception as e:
            logger.warning(f"[RECUPERAÇÃO] verificação automática falhou: {e}")
        time.sleep(CHECK_INTERVAL_S)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, name="gboc-config-recovery", daemon=True)
    _thread.start()
    logger.info("[RECUPERAÇÃO] backup automático da configuração ativo (alterações + 1x/dia)")


# ─── Recuperação ──────────────────────────────────────────────────

def backend_from_source(src: Dict[str, Any]):
    """Backend a partir dos dados digitados na tela de recuperação (instalação limpa: nada no banco ainda)."""
    from engines.repository_manager import RepositoryManager
    rtype = str(src.get("type") or "s3").lower()
    if rtype == "local":
        path = str(src.get("path") or "").strip()
        if not path:
            raise ValueError("Informe a pasta do repositório")
        cfg = {"type": "local", "path": path}
    else:
        bucket = str(src.get("bucket") or "").strip()
        access = str(src.get("access_key") or "").strip()
        secret = str(src.get("secret_key") or "")
        if not (bucket and access and secret):
            raise ValueError("Informe bucket, access key e chave secreta")
        cfg = {"type": rtype, "path": bucket, "bucket": bucket, "region": (src.get("region") or "").strip() or None,
               "endpoint": (src.get("endpoint") or "").strip() or None, "cloud_password": secret}
        if rtype == "b2":
            cfg.update(b2_account_id=access, b2_account_key=secret)
        else:
            cfg.update(aws_access_key=access, access_key=access, aws_secret_key=secret, secret_key=secret)
    cfg = {k: v for k, v in cfg.items() if v is not None}
    rm = getattr(_core(), "repository_manager", None) or RepositoryManager(_core())
    return rm._create_backend_from_config(cfg)


def read_package(be, name: str) -> bytes:
    name = str(name or "").replace("\\", "/")
    if not (name.startswith(DR_PREFIX + "/") and name.endswith(EXT)) or ".." in name:
        raise ValueError("Pacote inválido")
    return _get(be, name)


def restore(blob: bytes, passphrase: str, dry_run: bool = True) -> Dict[str, Any]:
    """Descriptografa e importa. Depois de aplicar, ativa a recuperação automática com a mesma chave
    (se ainda não estiver configurada neste Agente)."""
    from engines.config_manager import import_config
    data = open_package(blob, passphrase)
    meta = data.get("_gbocdr") or {}
    cfg = data.get("config") or {}
    report = import_config(cfg, dry_run=dry_run)
    report["package"] = {"agent": meta.get("agent"), "created_at": meta.get("created_at"),
                         "repositories": len(cfg.get("repositories") or []), "tasks": len(cfg.get("tasks") or [])}
    dup = data.get("duplicati")
    if dup:
        report["duplicati"] = _restore_duplicati(dup, dry_run)
    if not dry_run and not report.get("errors"):
        try:
            rec = data.get("recovery") or {}
            if not load_settings().get("passphrase_enc"):
                configure(True, passphrase, bool(rec.get("email_enabled")), rec.get("email_to") or "")
                report["recovery_enabled"] = True
            if rec.get("destination") and not load_settings().get("destination"):
                set_destination(rec["destination"], test=False)      # mesmo destino próprio do computador antigo
                report["recovery_destination"] = rec["destination"].get("bucket") or rec["destination"].get("path")
        except Exception as e:
            report.setdefault("warnings", []).append(f"Recuperação automática não ativada: {e}")
    return report


def _restore_duplicati(dup: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
    """Recria no Duplicati Server deste computador os jobs do pacote (com destino e passphrase) e dispara o
    reparo de cada um (reconstrói o banco local a partir do destino). Job de mesmo nome existente é mantido."""
    jobs = dup.get("jobs") or []
    out: Dict[str, Any] = {"jobs": len(jobs), "results": [], "package_errors": dup.get("errors") or []}
    if dry_run or not jobs:
        out["names"] = [str((j.get("Backup") or {}).get("Name")) for j in jobs]
        return out
    try:
        from core.integrations.duplicati_native import get_duplicati_native_service
        svc = get_duplicati_native_service()
        conn = dup.get("connection") or {}
        if not svc.is_configured() and conn.get("base_url"):
            svc.save_config(conn)                    # mesma conexão do computador antigo (ajustável na tela Duplicati)
        if not svc.probe().get("ok", True) and not svc._login(svc.load_config()):
            raise RuntimeError("Duplicati Server não respondeu: instale/inicie o Duplicati e recupere de novo")
        for j in jobs:
            try:
                out["results"].append(svc.import_backup_config(j))
            except Exception as e:
                out["results"].append({"status": "error", "name": (j.get("Backup") or {}).get("Name"), "message": str(e)})
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out
