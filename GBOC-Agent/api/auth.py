#!/usr/bin/env python3
"""
GBOC Agent - Authentication API & Access Levels (Roles & Permissions)
Token-based authentication with complete User CRUD, Role CRUD, custom levels, permissions and rate limiting.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
import hashlib
import secrets
import logging
import re
import time
import json
from datetime import datetime, timedelta
from collections import defaultdict
from api.audit_api import audit_login, audit_security_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# ============================================================================
# System Permissions Registry
# ============================================================================

AVAILABLE_PERMISSIONS = [
    {"id": "backups:read", "name": "Visualizar Tarefas de Backup", "module": "Backups"},
    {"id": "backups:write", "name": "Criar e Editar Tarefas", "module": "Backups"},
    {"id": "backups:execute", "name": "Executar Tarefas Manualmente", "module": "Backups"},
    {"id": "backups:delete", "name": "Excluir Tarefas de Backup", "module": "Backups"},

    {"id": "repositories:read", "name": "Visualizar Repositórios", "module": "Repositórios"},
    {"id": "repositories:write", "name": "Criar e Configurar Repositórios", "module": "Repositórios"},
    {"id": "repositories:delete", "name": "Remover Repositórios", "module": "Repositórios"},

    {"id": "restore:read", "name": "Visualizar Pontos e Histórico Restauração", "module": "Restauração"},
    {"id": "restore:execute", "name": "Executar Restauração de Arquivos", "module": "Restauração"},

    {"id": "reports:read", "name": "Visualizar Relatórios Executivos/IA", "module": "Relatórios"},
    {"id": "reports:export", "name": "Exportar Relatórios (PDF/CSV/JSON)", "module": "Relatórios"},

    {"id": "diagnostic:read", "name": "Visualizar Diagnóstico & Métricas", "module": "Diagnóstico"},
    {"id": "diagnostic:execute", "name": "Executar Integrity Check & Repairs", "module": "Diagnóstico"},

    {"id": "ransomware:read", "name": "Visualizar Dashboard Ransomware", "module": "Segurança"},
    {"id": "ransomware:write", "name": "Gerenciar Canários e Imutabilidade WORM", "module": "Segurança"},

    {"id": "settings:read", "name": "Visualizar Configurações do Agente", "module": "Configurações"},
    {"id": "settings:write", "name": "Alterar Configurações e Parâmetros", "module": "Configurações"},

    {"id": "users:read", "name": "Visualizar Lista de Usuários", "module": "Usuários & Níveis"},
    {"id": "users:write", "name": "Criar/Editar/Excluir Usuários", "module": "Usuários & Níveis"},
    {"id": "roles:read", "name": "Visualizar Níveis de Acesso", "module": "Usuários & Níveis"},
    {"id": "roles:write", "name": "Criar/Editar/Excluir Níveis Customizados", "module": "Usuários & Níveis"},

    {"id": "audit:read", "name": "Visualizar Trilha de Auditoria", "module": "Auditoria"}
]


# ============================================================================
# Token System & Rate Limiting
# ============================================================================

SECRET_KEY = None
TOKEN_EXPIRY_HOURS = 24
ACTIVE_TOKENS: Dict[str, Dict] = {}

_login_attempts: Dict[str, list] = defaultdict(list)
RATE_LIMIT_WINDOW = 300   # 5 minutes
RATE_LIMIT_MAX = 10       # max 10 attempts per window


def _check_rate_limit(ip: str):
    """Check and enforce login rate limiting per IP."""
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(_login_attempts[ip]) >= RATE_LIMIT_MAX:
        remaining = int(RATE_LIMIT_WINDOW - (now - _login_attempts[ip][0]))
        raise HTTPException(
            status_code=429,
            detail=f"Muitas tentativas de login. Tente novamente em {remaining}s."
        )
    _login_attempts[ip].append(now)


# ============================================================================
# Password Policy
# ============================================================================

PASSWORD_POLICY = {
    'min_length': 8,
    'require_uppercase': True,
    'require_lowercase': True,
    'require_digit': True,
    'require_special': True,
    'special_chars': '!@#$%^&*()_+-=[]{}|;:,.<>?',
}


def validate_password(password: str) -> tuple:
    """Validate password against policy. Returns (is_valid, errors)."""
    errors = []
    p = PASSWORD_POLICY

    if len(password) < p['min_length']:
        errors.append(f"Mínimo {p['min_length']} caracteres (tem {len(password)})")
    if p['require_uppercase'] and not re.search(r'[A-Z]', password):
        errors.append("Deve conter ao menos 1 letra maiúscula")
    if p['require_lowercase'] and not re.search(r'[a-z]', password):
        errors.append("Deve conter ao menos 1 letra minúscula")
    if p['require_digit'] and not re.search(r'[0-9]', password):
        errors.append("Deve conter ao menos 1 número")
    if p['require_special'] and not re.search(r'[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]', password):
        errors.append("Deve conter ao menos 1 caractere especial (!@#$%...)")

    return (len(errors) == 0, errors)


@router.get("/password-policy")
async def get_password_policy():
    """Returns the current password policy requirements."""
    return {
        "policy": PASSWORD_POLICY,
        "description": "A senha deve conter no mínimo 8 caracteres, incluindo maiúsculas, minúsculas, números e caracteres especiais."
    }


def _get_secret_key():
    global SECRET_KEY
    if SECRET_KEY:
        return SECRET_KEY
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key = 'auth_secret_key'")
            row = cur.fetchone()
            if row:
                SECRET_KEY = row[0]
            else:
                SECRET_KEY = secrets.token_hex(32)
                cur.execute(
                    "INSERT INTO settings (key, value, updated_at) VALUES (%s, %s, %s)",
                    ('auth_secret_key', SECRET_KEY, datetime.now().isoformat())
                )
                conn.commit()
    except Exception as e:
        logger.warning(f"Could not load secret key from DB, using ephemeral: {e}")
        SECRET_KEY = secrets.token_hex(32)
    return SECRET_KEY


def _hash_password(password: str, salt: str = None):
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return hashed.hex(), salt


def _verify_password(password: str, hashed: str, salt: str) -> bool:
    check_hash, _ = _hash_password(password, salt)
    return check_hash == hashed


def _generate_token(user_id: int, username: str) -> str:
    token = secrets.token_urlsafe(48)
    expires = datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)
    ACTIVE_TOKENS[token] = {
        'user_id': user_id,
        'username': username,
        'expires_at': expires
    }
    return token


def _validate_token(token: str) -> Optional[Dict]:
    if not token:
        return None
    info = ACTIVE_TOKENS.get(token)
    if not info:
        return None
    expires_at = info.get('expires_at')
    if isinstance(expires_at, (int, float)):
        if time.time() > expires_at:
            del ACTIVE_TOKENS[token]
            return None
    elif isinstance(expires_at, datetime):
        if datetime.now() > expires_at:
            del ACTIVE_TOKENS[token]
            return None
    return info


def get_current_user(request: Request) -> Optional[Dict]:
    token = request.cookies.get('gboc_token')
    if not token:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
    if not token:
        return None
    return _validate_token(token)


def is_auth_enabled() -> bool:
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM auth_users")
            count = cur.fetchone()[0]
            return count > 0
    except Exception:
        return False


def _ensure_auth_tables():
    """Cria tabelas de usuários, sessões e níveis de acesso (roles & permissions)."""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS auth_roles (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    description TEXT,
                    permissions TEXT NOT NULL,
                    is_system BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS auth_users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    display_name TEXT,
                    role TEXT DEFAULT 'admin',
                    is_active BOOLEAN DEFAULT TRUE,
                    last_login TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES auth_users(id),
                    token TEXT UNIQUE NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Preencher/Garantir os níveis de acesso nativos padrão (roles do sistema)
            default_roles = [
                ("admin", "Superusuário (Acesso Total)", "Administrador mestre com privilégios completos e irrestritos sobre todos os módulos e configurações.", json.dumps(["*"]), True),
                ("manager", "Gerente de Backup & TI", "Supervisão e gerenciamento de tarefas, repositórios, restaurações, relatórios e segurança.", json.dumps(["backups:read", "backups:write", "backups:execute", "repositories:read", "repositories:write", "reports:read", "reports:export", "diagnostic:read", "diagnostic:execute", "ransomware:read", "ransomware:write", "restore:read", "restore:execute", "audit:read"]), True),
                ("operator", "Operador de Backup", "Execução operacional de rotinas de backup, restauração de arquivos e leitura de relatórios.", json.dumps(["backups:read", "backups:write", "backups:execute", "repositories:read", "reports:read", "reports:export", "diagnostic:read", "restore:read", "restore:execute"]), True),
                ("auditor", "Auditor de Compliance", "Acesso de inspeção de logs, relatórios executivos, trilhas de segurança e conformidade LGPD.", json.dumps(["backups:read", "repositories:read", "reports:read", "reports:export", "diagnostic:read", "ransomware:read", "audit:read"]), True),
                ("viewer", "Visualizador (Somente Leitura)", "Acesso exclusivamente para consulta visual de dashboards, relatórios e status sem permissão de alteração.", json.dumps(["backups:read", "repositories:read", "reports:read", "diagnostic:read"]), True)
            ]
            for rname, dname, desc, perms, is_sys in default_roles:
                cur.execute("""
                    INSERT INTO auth_roles (name, display_name, description, permissions, is_system)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET display_name = EXCLUDED.display_name, description = EXCLUDED.description, is_system = TRUE
                """, (rname, dname, desc, perms, is_sys))

            conn.commit()
            logger.info("[OK] Auth tables and 5-Level Roles hierarchy ready")
    except Exception as e:
        logger.error(f"Error creating auth tables: {e}")


# Inicializa tabelas na carga do módulo
try:
    _ensure_auth_tables()
except Exception:
    pass


# ============================================================================
# Models
# ============================================================================

class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    role: Optional[str] = 'admin'


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    new_password: Optional[str] = None


class CreateRoleRequest(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None
    permissions: List[str] = []


class UpdateRoleRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None


# ============================================================================
# Endpoints de Autenticação Básica
# ============================================================================

@router.get("/status")
async def auth_status(request: Request):
    _ensure_auth_tables()
    enabled = is_auth_enabled()
    user = get_current_user(request)
    user_data = None
    if user:
        try:
            from shared_core import get_shared_core
            core = get_shared_core()
            with core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT username, display_name, role, last_login FROM auth_users WHERE id = %s",
                    (user['user_id'],)
                )
                row = cur.fetchone()
                if row:
                    user_data = {
                        "username": row[0],
                        "display_name": row[1],
                        "role": row[2],
                        "last_login": row[3].isoformat() if row[3] else None
                    }
        except Exception:
            user_data = {"username": user['username']}

    return {
        "status": "success",
        "auth_enabled": enabled,
        "authenticated": user is not None,
        "user": user_data
    }


@router.post("/login")
async def login(req: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    if not req.username or not req.password:
        audit_login(username=req.username or "empty", success=False, ip=client_ip, reason="dados_incompletos")
        raise HTTPException(status_code=400, detail="Usuário e senha são obrigatórios")

    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, username, password_hash, password_salt, display_name, role, is_active FROM auth_users WHERE username = %s",
                (req.username.strip(),)
            )
            user = cur.fetchone()

            if not user:
                audit_login(username=req.username, success=False, ip=client_ip, reason="usuario_nao_encontrado")
                raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")

            user_id, username, pw_hash, pw_salt, display_name, role, is_active = user

            if not is_active:
                audit_login(username=req.username, success=False, ip=client_ip, reason="usuario_inativo")
                raise HTTPException(status_code=403, detail="Conta inativa. Contate o administrador.")

            if not _verify_password(req.password, pw_hash, pw_salt):
                audit_login(username=req.username, success=False, ip=client_ip, reason="senha_incorreta")
                raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")

            # Atualizar last_login
            now = datetime.now().isoformat()
            cur.execute("UPDATE auth_users SET last_login = %s WHERE id = %s", (now, user_id))

            token = _generate_token(user_id, username)
            expires = datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)

            cur.execute(
                "INSERT INTO auth_sessions (user_id, token, ip_address, user_agent, expires_at) VALUES (%s, %s, %s, %s, %s)",
                (user_id, token, client_ip, request.headers.get("user-agent", ""), expires.isoformat())
            )
            conn.commit()

        audit_login(username=username, success=True, ip=client_ip)
        resp = JSONResponse({
            "status": "success",
            "token": token,
            "user": {
                "id": user_id,
                "username": username,
                "display_name": display_name or username,
                "role": role
            }
        })
        resp.set_cookie(key="gboc_token", value=token, httponly=True, max_age=86400, samesite="lax")
        return resp

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Erro interno no login")


@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get('gboc_token')
    if not token:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
    if token and token in ACTIVE_TOKENS:
        del ACTIVE_TOKENS[token]
    if token:
        try:
            from shared_core import get_shared_core
            core = get_shared_core()
            with core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM auth_sessions WHERE token = %s", (token,))
                conn.commit()
        except Exception:
            pass
    resp = JSONResponse({"status": "success", "message": "Logout realizado"})
    resp.delete_cookie("gboc_token")
    return resp


@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT password_hash, password_salt FROM auth_users WHERE id = %s", (user['user_id'],))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Usuário não encontrado")
            if not _verify_password(req.current_password, row[0], row[1]):
                audit_security_event('password_change_failed', username=user.get('username'), ip=request.client.host if request.client else None, detail={'reason': 'invalid_current_password'})
                raise HTTPException(status_code=400, detail="Senha atual incorreta")
            valid, pwd_errors = validate_password(req.new_password)
            if not valid:
                audit_security_event('password_change_failed', username=user.get('username'), ip=request.client.host if request.client else None, detail={'reason': 'weak_password'})
                raise HTTPException(status_code=400, detail="Senha fraca: " + "; ".join(pwd_errors))
            new_hash, new_salt = _hash_password(req.new_password)
            cur.execute(
                "UPDATE auth_users SET password_hash = %s, password_salt = %s, updated_at = %s WHERE id = %s",
                (new_hash, new_salt, datetime.now().isoformat(), user['user_id'])
            )
            conn.commit()
        audit_security_event('password_changed', username=user.get('username'), ip=request.client.host if request.client else None, detail={'user_id': user.get('user_id')})
        return {"status": "success", "message": "Senha alterada com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Change password error: {e}")
        raise HTTPException(status_code=500, detail="Erro ao alterar senha")


# ============================================================================
# ENDPOINTS: ROLES & PERMISSIONS (CRUD DE NÍVEIS DE ACESSO CUSTOMIZADOS)
# ============================================================================

@router.get("/permissions")
async def list_available_permissions():
    """Retorna o catálogo de todas as permissões granulares disponíveis no sistema."""
    modules = {}
    for p in AVAILABLE_PERMISSIONS:
        mod = p["module"]
        if mod not in modules:
            modules[mod] = []
        modules[mod].append(p)

    return {
        "status": "success",
        "total": len(AVAILABLE_PERMISSIONS),
        "permissions": AVAILABLE_PERMISSIONS,
        "grouped_by_module": modules
    }


@router.get("/roles")
async def list_roles(request: Request):
    """Lista todos os níveis de acesso (nativos do sistema e customizados) com contagem de usuários."""
    _ensure_auth_tables()
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT r.id, r.name, r.display_name, r.description, r.permissions, r.is_system, r.created_at,
                       COUNT(u.id) as user_count
                FROM auth_roles r
                LEFT JOIN auth_users u ON u.role = r.name
                GROUP BY r.id, r.name, r.display_name, r.description, r.permissions, r.is_system, r.created_at
                ORDER BY r.is_system DESC, r.id ASC
            """)
            rows = cur.fetchall()
            roles = []
            for r in rows:
                try:
                    perms = json.loads(r[4])
                except Exception:
                    perms = []
                roles.append({
                    "id": r[0],
                    "name": r[1],
                    "display_name": r[2],
                    "description": r[3] or "",
                    "permissions": perms,
                    "is_system": bool(r[5]),
                    "created_at": r[6].isoformat() if r[6] else None,
                    "user_count": int(r[7] or 0)
                })
        return {"status": "success", "roles": roles}
    except Exception as e:
        logger.error(f"List roles error: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/roles")
async def create_role(req: CreateRoleRequest, request: Request):
    """Cria um novo Nível de Acesso Customizado com permissões personalizadas."""
    caller = get_current_user(request)
    if not caller:
        raise HTTPException(status_code=401, detail="Não autenticado")

    if not req.name or not req.display_name:
        raise HTTPException(status_code=400, detail="Identificador e Nome de Exibição são obrigatórios")

    # Sanitizar identificador (slug)
    slug_name = re.sub(r'[^a-z0-9_]', '_', req.name.strip().lower())
    if not slug_name:
        raise HTTPException(status_code=400, detail="Identificador de nível inválido")

    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()

            # Verificar unicidade
            cur.execute("SELECT id FROM auth_roles WHERE name = %s", (slug_name,))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail=f"Já existe um nível com o identificador '{slug_name}'")

            now = datetime.now().isoformat()
            perms_json = json.dumps(req.permissions or [])

            cur.execute("""
                INSERT INTO auth_roles (name, display_name, description, permissions, is_system, created_at, updated_at)
                VALUES (%s, %s, %s, %s, FALSE, %s, %s) RETURNING id
            """, (slug_name, req.display_name.strip(), req.description or "", perms_json, now, now))
            new_id = cur.fetchone()[0]
            conn.commit()

        logger.info(f"Role customizada criada: {slug_name} por {caller['username']}")
        audit_security_event('role_created', username=caller.get('username'), ip=request.client.host if request.client else None, detail={'role_name': slug_name, 'display_name': req.display_name})
        return {"status": "success", "id": new_id, "name": slug_name, "message": f"Nível de acesso '{req.display_name}' criado com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create role error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/roles/{role_id}")
async def update_role(role_id: int, req: UpdateRoleRequest, request: Request):
    """Atualiza as propriedades e permissões de um Nível de Acesso."""
    caller = get_current_user(request)
    if not caller:
        raise HTTPException(status_code=401, detail="Não autenticado")

    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, is_system FROM auth_roles WHERE id = %s", (role_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Nível de acesso não encontrado")

            rid, rname, is_sys = row

            updates = []
            values = []

            if req.display_name is not None:
                updates.append("display_name = %s")
                values.append(req.display_name.strip())
            if req.description is not None:
                updates.append("description = %s")
                values.append(req.description.strip())
            if req.permissions is not None:
                updates.append("permissions = %s")
                values.append(json.dumps(req.permissions))

            if not updates:
                return {"status": "noop", "message": "Nenhum campo para atualizar"}

            updates.append("updated_at = %s")
            values.append(datetime.now().isoformat())
            values.append(role_id)

            cur.execute(f"UPDATE auth_roles SET {', '.join(updates)} WHERE id = %s", tuple(values))
            conn.commit()

        logger.info(f"Role {role_id} ({rname}) atualizada por {caller['username']}")
        audit_security_event('role_updated', username=caller.get('username'), ip=request.client.host if request.client else None, detail={'role_id': role_id, 'role_name': rname})
        return {"status": "success", "message": f"Nível de acesso '{rname}' atualizado com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update role error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/roles/{role_id}")
async def delete_role(role_id: int, request: Request):
    """Remove um Nível de Acesso customizado (impede remoção de níveis do sistema ou em uso)."""
    caller = get_current_user(request)
    if not caller:
        raise HTTPException(status_code=401, detail="Não autenticado")

    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, display_name, is_system FROM auth_roles WHERE id = %s", (role_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Nível de acesso não encontrado")

            rid, rname, dname, is_sys = row
            if is_sys:
                raise HTTPException(status_code=400, detail=f"O nível nativo '{dname}' é do sistema e não pode ser excluído")

            # Verificar se existem usuários atribuídos a este nível
            cur.execute("SELECT COUNT(*) FROM auth_users WHERE role = %s", (rname,))
            ucount = (cur.fetchone() or [0])[0]
            if ucount > 0:
                raise HTTPException(status_code=400, detail=f"Não é possível excluir o nível '{dname}' pois existem {ucount} usuários vinculados a ele")

            cur.execute("DELETE FROM auth_roles WHERE id = %s", (role_id,))
            conn.commit()

        logger.info(f"Role customizada '{rname}' excluída por {caller['username']}")
        audit_security_event('role_deleted', username=caller.get('username'), ip=request.client.host if request.client else None, detail={'role_id': role_id, 'role_name': rname})
        return {"status": "success", "message": f"Nível de acesso '{dname}' removido com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete role error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS: USER CRUD COMPLETO
# ============================================================================

@router.get("/users")
async def list_users(request: Request):
    """Lista todos os usuários cadastrados juntamente com o nome de exibição do seu Nível de Acesso."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT u.id, u.username, u.display_name, u.role, u.is_active, u.last_login, u.created_at,
                       COALESCE(r.display_name, u.role) as role_display_name,
                       COALESCE(r.permissions, '[]') as role_permissions
                FROM auth_users u
                LEFT JOIN auth_roles r ON r.name = u.role
                ORDER BY u.id ASC
            """)
            rows = cur.fetchall()
            users = []
            for row in rows:
                try:
                    perms = json.loads(row[7])
                except Exception:
                    perms = []
                users.append({
                    "id": row[0],
                    "username": row[1],
                    "display_name": row[2] or row[1],
                    "role": row[3],
                    "role_display_name": row[4] if False else row[7] if False else (row[7] and row[7] != '[]' and row[3] or row[3]),
                    "role_title": row[7] if False else row[3].title(),
                    "role_name": row[3],
                    "is_active": bool(row[4]),
                    "last_login": row[5].isoformat() if row[5] else None,
                    "created_at": row[6].isoformat() if row[6] else None,
                    "permissions": perms
                })

            # Buscar total de sessões ativas
            cur.execute("SELECT COUNT(*) FROM auth_sessions WHERE expires_at > CURRENT_TIMESTAMP")
            active_sessions = (cur.fetchone() or [0])[0]

        return {"status": "success", "users": users, "active_sessions": active_sessions}
    except Exception as e:
        logger.error(f"List users error: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/users")
async def create_user(req: CreateUserRequest, request: Request):
    """Cria um novo usuário com nível de acesso configurado."""
    caller = get_current_user(request)
    if not caller:
        raise HTTPException(status_code=401, detail="Não autenticado")
    try:
        if not req.username or not req.username.strip():
            raise HTTPException(status_code=400, detail="Nome de usuário é obrigatório")
        if not req.password:
            raise HTTPException(status_code=400, detail="Senha é obrigatória")
        valid, pwd_errors = validate_password(req.password)
        if not valid:
            raise HTTPException(status_code=400, detail="Senha fraca: " + "; ".join(pwd_errors))

        user_role = (req.role or 'admin').strip().lower()

        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM auth_users WHERE username = %s", (req.username.strip(),))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Nome de usuário já cadastrado")

            # Validar se a role existe
            cur.execute("SELECT id FROM auth_roles WHERE name = %s", (user_role,))
            if not cur.fetchone():
                user_role = 'admin'

            password_hash, salt = _hash_password(req.password)
            now = datetime.now().isoformat()
            cur.execute("""
                INSERT INTO auth_users (username, password_hash, password_salt, display_name, role, is_active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s) RETURNING id
            """, (req.username.strip(), password_hash, salt,
                  req.display_name or req.username.strip(),
                  user_role, now, now))
            new_id = cur.fetchone()[0]
            conn.commit()

        logger.info(f"User created: {req.username} (ID: {new_id}, Role: {user_role}) by {caller['username']}")
        audit_security_event('user_created', username=caller.get('username'), ip=request.client.host if request.client else None, detail={'target_user': req.username, 'target_user_id': new_id, 'role': user_role})
        return {"status": "success", "id": new_id, "message": f"Usuário '{req.username}' criado com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create user error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{user_id}")
async def update_user(user_id: int, req: UpdateUserRequest, request: Request):
    """Atualiza um usuário existente (nome, nível de acesso, status ativo/inativo, nova senha)."""
    caller = get_current_user(request)
    if not caller:
        raise HTTPException(status_code=401, detail="Não autenticado")
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, username FROM auth_users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Usuário não encontrado")

            updates = []
            values = []
            if req.display_name is not None:
                updates.append("display_name = %s")
                values.append(req.display_name.strip())
            if req.role is not None:
                updates.append("role = %s")
                values.append(req.role.strip().lower())
            if req.is_active is not None:
                updates.append("is_active = %s")
                values.append(req.is_active)
            if req.new_password is not None and req.new_password != "":
                valid, pwd_errors = validate_password(req.new_password)
                if not valid:
                    raise HTTPException(status_code=400, detail="Senha fraca: " + "; ".join(pwd_errors))
                pw_hash, pw_salt = _hash_password(req.new_password)
                updates.append("password_hash = %s")
                values.append(pw_hash)
                updates.append("password_salt = %s")
                values.append(pw_salt)

            if not updates:
                return {"status": "noop", "message": "Nenhum campo para atualizar"}

            updates.append("updated_at = %s")
            values.append(datetime.now().isoformat())
            values.append(user_id)

            cur.execute(f"UPDATE auth_users SET {', '.join(updates)} WHERE id = %s", tuple(values))
            conn.commit()

        logger.info(f"User {user_id} updated by {caller['username']}")
        audit_security_event('user_updated', username=caller.get('username'), ip=request.client.host if request.client else None, detail={'target_user_id': user_id})
        return {"status": "success", "message": "Usuário atualizado com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update user error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, request: Request):
    """Remove um usuário do sistema."""
    caller = get_current_user(request)
    if not caller:
        raise HTTPException(status_code=401, detail="Não autenticado")
    if caller['user_id'] == user_id:
        raise HTTPException(status_code=400, detail="Você não pode excluir a si mesmo")

    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, username FROM auth_users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Usuário não encontrado")
            username = row[1]

            cur.execute("DELETE FROM auth_sessions WHERE user_id = %s", (user_id,))
            tokens_to_remove = [t for t, info in ACTIVE_TOKENS.items() if info.get('user_id') == user_id]
            for t in tokens_to_remove:
                del ACTIVE_TOKENS[t]
            cur.execute("DELETE FROM auth_users WHERE id = %s", (user_id,))
            conn.commit()

        logger.info(f"User '{username}' (ID: {user_id}) deleted by {caller['username']}")
        audit_security_event('user_deleted', username=caller.get('username'), ip=request.client.host if request.client else None, detail={'target_user': username, 'target_user_id': user_id})
        return {"status": "success", "message": f"Usuário '{username}' removido com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete user error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
