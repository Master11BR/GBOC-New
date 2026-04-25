#!/usr/bin/env python3
"""
GBOC Agent - Authentication API
Token-based authentication with user management, password policy, rate limiting
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict
import hashlib
import secrets
import logging
import re
import time
from datetime import datetime, timedelta
from collections import defaultdict
from api.audit_api import audit_login, audit_security_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# ============================================================================

# ============================================================================
# Token System
# ============================================================================

SECRET_KEY = None
TOKEN_EXPIRY_HOURS = 24
ACTIVE_TOKENS: Dict[str, Dict] = {}

# ============================================================================
# Rate Limiting
# ============================================================================

_login_attempts: Dict[str, list] = defaultdict(list)  # ip -> [timestamp, ...]
RATE_LIMIT_WINDOW = 300   # 5 minutes
RATE_LIMIT_MAX = 10       # max 10 attempts per window


def _check_rate_limit(ip: str):
    """Check and enforce login rate limiting per IP."""
    now = time.time()
    # Clean old entries
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
    if datetime.now() > info['expires_at']:
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
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
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
            conn.commit()
            logger.info("[OK] Auth tables ready")
    except Exception as e:
        logger.error(f"Error creating auth tables: {e}")


# Initialize on module load
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


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/status")
async def auth_status(request: Request):
    _ensure_auth_tables()
    enabled = is_auth_enabled()
    user = get_current_user(request)
    user_data = None
    if user:
        # Buscar dados completos do usuário
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


@router.post("/setup")
async def setup_first_user(reg: RegisterRequest):
    _ensure_auth_tables()
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM auth_users")
            count = cur.fetchone()[0]
            if count > 0:
                raise HTTPException(status_code=400, detail="Usuário já existe. Use login.")
            valid, pwd_errors = validate_password(reg.password)
            if not valid:
                raise HTTPException(status_code=400, detail="Senha fraca: " + "; ".join(pwd_errors))
            password_hash, salt = _hash_password(reg.password)
            now = datetime.now().isoformat()
            cur.execute("""
                INSERT INTO auth_users (username, password_hash, password_salt, display_name, role, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'admin', %s, %s)
            """, (reg.username, password_hash, salt, reg.display_name or reg.username, now, now))
            conn.commit()
        logger.info(f"First admin user created: {reg.username}")
        return {"status": "success", "message": f"Usuário '{reg.username}' criado com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating first user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login")
async def login(req: LoginRequest, request: Request):
    _ensure_auth_tables()
    client_ip = request.client.host if request.client else 'unknown'
    _check_rate_limit(client_ip)
    try:
        from api.audit_api import audit_login
    except Exception:
        audit_login = None
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, username, password_hash, password_salt, display_name, role, is_active FROM auth_users WHERE username = %s",
                (req.username,)
            )
            row = cur.fetchone()
            if not row:
                if audit_login:
                    try: audit_login(req.username, client_ip, False)
                    except Exception: pass
                raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")
            user_id, username, pw_hash, pw_salt, display_name, role, is_active = row
            if not is_active:
                if audit_login:
                    try: audit_login(username, client_ip, False)
                    except Exception: pass
                raise HTTPException(status_code=403, detail="Conta desativada")
            if not _verify_password(req.password, pw_hash, pw_salt):
                if audit_login:
                    try: audit_login(username, client_ip, False)
                    except Exception: pass
                raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")
            token = _generate_token(user_id, username)
            cur.execute("UPDATE auth_users SET last_login = %s WHERE id = %s",
                        (datetime.now().isoformat(), user_id))
            ip = request.client.host if request.client else 'unknown'
            ua = request.headers.get('User-Agent', 'unknown')[:200]
            expires = datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)
            cur.execute("""
                INSERT INTO auth_sessions (user_id, token, ip_address, user_agent, expires_at)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, token, ip, ua, expires.isoformat()))
            conn.commit()

        if audit_login:
            try: audit_login(username, ip, True)
            except Exception: pass

        resp = JSONResponse({
            "status": "success",
            "token": token,
            "user": {
                "username": username,
                "display_name": display_name,
                "role": role
            }
        })
        resp.set_cookie(
            key="gboc_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=TOKEN_EXPIRY_HOURS * 3600
        )
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


@router.get("/users")
async def list_users(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, username, display_name, role, is_active, last_login, created_at FROM auth_users ORDER BY id"
            )
            rows = cur.fetchall()
            users = []
            for row in rows:
                users.append({
                    "id": row[0], "username": row[1], "display_name": row[2],
                    "role": row[3], "is_active": row[4],
                    "last_login": row[5].isoformat() if row[5] else None,
                    "created_at": row[6].isoformat() if row[6] else None
                })
        return {"status": "success", "users": users}
    except Exception as e:
        logger.error(f"List users error: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/users")
async def create_user(req: CreateUserRequest, request: Request):
    """Cria um novo usuário (requer autenticação)"""
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

        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM auth_users WHERE username = %s", (req.username.strip(),))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Usuário já existe")
            password_hash, salt = _hash_password(req.password)
            now = datetime.now().isoformat()
            cur.execute("""
                INSERT INTO auth_users (username, password_hash, password_salt, display_name, role, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (req.username.strip(), password_hash, salt,
                  req.display_name or req.username.strip(),
                  req.role or 'admin', now, now))
            new_id = cur.fetchone()[0]
            conn.commit()
        logger.info(f"User created: {req.username} (ID: {new_id}) by {caller['username']}")
        audit_security_event('user_created', username=caller.get('username'), ip=request.client.host if request.client else None, detail={'target_user': req.username, 'target_user_id': new_id, 'role': req.role or 'admin'})
        return {"status": "success", "id": new_id, "message": f"Usuário '{req.username}' criado com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create user error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{user_id}")
async def update_user(user_id: int, req: UpdateUserRequest, request: Request):
    """Atualiza um usuário existente"""
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
                values.append(req.display_name)
            if req.role is not None:
                updates.append("role = %s")
                values.append(req.role)
            if req.is_active is not None:
                updates.append("is_active = %s")
                values.append(req.is_active)
            if req.new_password is not None:
                if len(req.new_password) < 6:
                    raise HTTPException(status_code=400, detail="Senha deve ter no mínimo 6 caracteres")
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
        audit_security_event('user_updated', username=caller.get('username'), ip=request.client.host if request.client else None, detail={'target_user_id': user_id, 'fields': [k for k,v in req.dict(exclude_unset=True).items() if v is not None]})
        return {"status": "success", "message": "Usuário atualizado com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update user error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, request: Request):
    """Remove um usuário"""
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

            # Remover sessões do usuário
            cur.execute("DELETE FROM auth_sessions WHERE user_id = %s", (user_id,))
            # Remover tokens em memória
            tokens_to_remove = [t for t, info in ACTIVE_TOKENS.items() if info.get('user_id') == user_id]
            for t in tokens_to_remove:
                del ACTIVE_TOKENS[t]
            # Remover usuário
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
