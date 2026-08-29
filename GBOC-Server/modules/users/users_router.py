# GBOC System v13.2.0 Enterprise Edition
# Module: Users & Auth Management Router (5-Level Roles CRUD)

import logging
import hashlib
import secrets
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:
    from database import db_manager
    def get_db(): return db_manager.get_connection()
    def release_db(conn): db_manager.release_connection(conn)
except Exception:
    def get_db(): return None
    def release_db(conn): pass

logger = logging.getLogger("gboc_users_module")
router = APIRouter(prefix="/api/v1/users", tags=["Usuários"])

def _hash_password(password: str) -> str:
    salt = "gboc_server_salt_2025"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

ROLES_HIERARCHY_MATRIX = [
    {"role": "admin", "label": "Administrator", "description": "Acesso total e irrestrito a todas as funções, configurações e nós.", "permissions": ["ALL"]},
    {"role": "operator", "label": "MSP Operator", "description": "Gerenciamento de agentes, execuções de RMM, disparo de backups e restauração.", "permissions": ["AGENTS_WRITE", "RMM_EXEC", "JOBS_EXEC", "REPORTS_READ"]},
    {"role": "specialist", "label": "Backup Specialist", "description": "Criação, edição e execução de rotinas de backup, CBT e SureRestore.", "permissions": ["JOBS_WRITE", "CBT_WRITE", "RESTORE_EXEC", "REPORTS_READ"]},
    {"role": "auditor", "label": "Auditor", "description": "Acesso completo a logs de auditoria, eventos do Ransomware Guardian e compliance.", "permissions": ["LOGS_READ", "AUDIT_READ", "GUARDIAN_READ", "COMPLIANCE_READ"]},
    {"role": "readonly", "label": "ReadOnly", "description": "Visualização de dashboards, estatísticas e relatórios sem permissão de alteração.", "permissions": ["DASHBOARD_READ", "REPORTS_READ"]}
]

def _get_current_user_from_req(request: Request) -> Optional[Dict[str, Any]]:
    """Obtém o usuário logado com base no token da requisição."""
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.cookies.get("gboc_server_token")
    
    if not token:
        return None
        
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT u.id, u.username, u.display_name, u.role, u.tenant_id
            FROM server_auth_tokens t
            JOIN server_auth_users u ON t.user_id = u.id
            WHERE t.token = %s AND t.expires_at > LOCALTIMESTAMP
        """, (token,))
        row = cur.fetchone()
        cur.close()
        if row:
            return {"id": row[0], "username": row[1], "display_name": row[2], "role": row[3], "tenant_id": row[4]}
    except Exception as e:
        logger.warning(f"[USERS] Erro ao autenticar via token local: {e}")
    finally:
        if conn: release_db(conn)
    return None

class UserCreateReq(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    role: str = "admin"
    tenant_id: Optional[str] = None

class UserUpdateReq(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    tenant_id: Optional[str] = None
    status: Optional[str] = None

class UserPasswordReq(BaseModel):
    new_password: str

@router.get("")
async def get_users_list():
    """Retorna a lista completa de usuários cadastrados no Servidor, incluindo o tenant."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT u.id, u.username, u.display_name, u.role, u.status, u.created_at, u.last_login, u.tenant_id, o.name 
            FROM server_auth_users u 
            LEFT JOIN msp_organizations o ON u.tenant_id = o.org_id 
            ORDER BY u.username
        """)
        rows = cur.fetchall()
        users = []
        for r in rows:
            status = r[4] or "active"
            users.append({
                "id": r[0],
                "username": r[1],
                "display_name": r[2] or r[1],
                "role": r[3] or "admin",
                "status": status,
                "is_active": (status != "inactive"),
                "created_at": str(r[5]) if r[5] else None,
                "last_login": str(r[6]) if r[6] else None,
                "tenant_id": r[7],
                "tenant_name": r[8] or "Global Admin"
            })
        cur.close()
        
        # Calcular sessões ativas fictícias com base nos tokens válidos
        cur_sessions = 1
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(DISTINCT user_id) FROM server_auth_tokens WHERE expires_at > LOCALTIMESTAMP")
            row = cur.fetchone()
            if row and row[0] > 0:
                cur_sessions = row[0]
            cur.close()
        except:
            pass
            
        return JSONResponse({"status": "success", "total": len(users), "users": users, "active_sessions": cur_sessions})
    except Exception as e:
        logger.warning(f"[USERS MODULE] Erro ao buscar usuários do banco: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
    finally:
        if conn: release_db(conn)

@router.get("/roles")
async def get_roles_matrix():
    """Retorna a matriz oficial dos 5 níveis de acesso e hierarquia de permissões."""
    roles = []
    for r in ROLES_HIERARCHY_MATRIX:
        roles.append({
            "id": len(roles) + 1,
            "name": r["role"],
            "display_name": r["label"],
            "description": r["description"],
            "is_system": True,
            "user_count": 0,  # Calculado dinamicamente
            "permissions": r["permissions"]
        })
    
    # Calcular contagem real de usuários por perfil
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT role, COUNT(*) FROM server_auth_users GROUP BY role")
        counts = dict(cur.fetchall())
        for r in roles:
            r["user_count"] = counts.get(r["name"], 0)
        cur.close()
    except Exception as e:
        logger.warning(f"[USERS] Erro ao calcular contagem de perfis: {e}")
    finally:
        if conn: release_db(conn)
        
    return JSONResponse({"status": "success", "roles": roles})

@router.get("/status")
async def get_current_user_status(request: Request):
    """Retorna as informações do perfil do usuário atualmente autenticado."""
    u = _get_current_user_from_req(request)
    if not u:
        u = {"id": 1, "username": "admin", "display_name": "Administrador Master", "role": "admin", "tenant_id": None}
    
    return JSONResponse({
        "status": "success",
        "user": {
            "id": u["id"],
            "username": u["username"],
            "display_name": u["display_name"] or u["username"],
            "role": u["role"] or "admin",
            "tenant_id": u.get("tenant_id")
        },
        "auth_enabled": True
    })

@router.get("/permissions")
async def get_permissions_catalog():
    """Retorna o catálogo de permissões disponíveis no sistema."""
    perms = [
        {"id": "ALL", "name": "Acesso Total"},
        {"id": "AGENTS_WRITE", "name": "Escrita em Agentes"},
        {"id": "RMM_EXEC", "name": "Executar RMM"},
        {"id": "JOBS_EXEC", "name": "Disparar Backups"},
        {"id": "JOBS_WRITE", "name": "Configurar Backups"},
        {"id": "CBT_WRITE", "name": "Configurar CBT"},
        {"id": "RESTORE_EXEC", "name": "Executar Restaurações"},
        {"id": "LOGS_READ", "name": "Leitura de Logs"},
        {"id": "AUDIT_READ", "name": "Leitura de Auditoria"},
        {"id": "GUARDIAN_READ", "name": "Ransomware Guardian"},
        {"id": "COMPLIANCE_READ", "name": "Visualizar Compliance"},
        {"id": "DASHBOARD_READ", "name": "Acesso ao Painel"},
        {"id": "REPORTS_READ", "name": "Leitura de Relatórios"}
    ]
    grouped = {
        "Geral": [
            {"id": "ALL", "name": "Acesso Total (ALL)"},
            {"id": "DASHBOARD_READ", "name": "Acesso ao Painel (DASHBOARD_READ)"}
        ],
        "Agentes & RMM": [
            {"id": "AGENTS_WRITE", "name": "Alterar Agentes (AGENTS_WRITE)"},
            {"id": "RMM_EXEC", "name": "Executar RMM (RMM_EXEC)"}
        ],
        "Backup & Restauração": [
            {"id": "JOBS_WRITE", "name": "Configurar Backups (JOBS_WRITE)"},
            {"id": "JOBS_EXEC", "name": "Disparar Backups (JOBS_EXEC)"},
            {"id": "CBT_WRITE", "name": "Configurar CBT (CBT_WRITE)"},
            {"id": "RESTORE_EXEC", "name": "Executar Restaurações (RESTORE_EXEC)"}
        ],
        "Segurança & Compliance": [
            {"id": "LOGS_READ", "name": "Leitura de Logs (LOGS_READ)"},
            {"id": "AUDIT_READ", "name": "Leitura de Auditoria (AUDIT_READ)"},
            {"id": "GUARDIAN_READ", "name": "Ransomware Guardian (GUARDIAN_READ)"},
            {"id": "COMPLIANCE_READ", "name": "Visualizar Compliance (COMPLIANCE_READ)"}
        ],
        "Relatórios": [
            {"id": "REPORTS_READ", "name": "Leitura de Relatórios (REPORTS_READ)"}
        ]
    }
    return JSONResponse({"status": "success", "permissions": perms, "grouped_by_module": grouped})

@router.get("/audit")
async def get_audit_trail():
    """Retorna a trilha de auditoria cadastrada no banco PostgreSQL."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT username, action, details, ip_address, timestamp 
            FROM server_auth_audit 
            ORDER BY timestamp DESC 
            LIMIT 50
        """)
        rows = cur.fetchall()
        logs = []
        for r in rows:
            logs.append({
                "username": r[0] or "sistema",
                "action": r[1],
                "details": r[2] or "",
                "ip": r[3] or "127.0.0.1",
                "timestamp": str(r[4])
            })
        cur.close()
        return JSONResponse({"status": "success", "logs": logs, "entries": logs})
    except Exception as e:
        logger.error(f"[USERS] Erro ao obter trilha de auditoria: {e}")
        return JSONResponse({"status": "success", "logs": []})
    finally:
        if conn: release_db(conn)

@router.post("")
async def create_user_endpoint(req: UserCreateReq, request: Request):
    """Cria um novo usuário associado ou não a um tenant."""
    if len(req.password) < 4:
        raise HTTPException(400, "Senha deve ter pelo menos 4 caracteres")
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        pw_hash = _hash_password(req.password)
        
        # Validar se o tenant existe se for especificado
        if req.tenant_id:
            cur.execute("SELECT 1 FROM msp_organizations WHERE org_id = %s", (req.tenant_id,))
            if not cur.fetchone():
                raise HTTPException(400, f"Organização '{req.tenant_id}' não existe no banco de dados.")

        cur.execute(
            "INSERT INTO server_auth_users (username, password_hash, display_name, role, tenant_id, status) VALUES (%s,%s,%s,%s,%s,'active') RETURNING id",
            (req.username, pw_hash, req.display_name or req.username, req.role, req.tenant_id)
        )
        new_id = cur.fetchone()[0]
        
        # Gravar na trilha de auditoria
        try:
            creator = _get_current_user_from_req(request) or {"username": "admin", "id": 1}
            cur.execute(
                "INSERT INTO server_auth_audit (user_id, username, action, ip_address, details) VALUES (%s, %s, %s, %s, %s)",
                (creator["id"], creator["username"], "CREATE_USER", request.client.host, f"Criado usuário {req.username} com perfil {req.role} no tenant {req.tenant_id}")
            )
        except Exception as audit_err:
            logger.warning(f"[USERS] Falha ao registrar log de auditoria: {audit_err}")

        conn.commit()
        cur.close()
        return JSONResponse({"status": "success", "message": f"Usuário '{req.username}' criado com sucesso", "user_id": new_id})
    except HTTPException:
        if conn: conn.rollback()
        raise
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"[USERS] Erro ao criar usuário: {e}")
        raise HTTPException(500, f"Falha ao criar usuário: {str(e)}")
    finally:
        if conn: release_db(conn)

@router.put("/{user_id}")
async def update_user_endpoint(user_id: int, req: UserUpdateReq, request: Request):
    """Atualiza dados de exibição, perfil, empresa (tenant) e status de um usuário."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Verificar se usuário existe
        cur.execute("SELECT username FROM server_auth_users WHERE id = %s", (user_id,))
        user_row = cur.fetchone()
        if not user_row:
            raise HTTPException(404, "Usuário não encontrado")
        username = user_row[0]
        
        updates = []
        params = []
        if req.display_name is not None:
            updates.append("display_name = %s")
            params.append(req.display_name)
        if req.role is not None:
            updates.append("role = %s")
            params.append(req.role)
        if req.tenant_id is not None:
            if req.tenant_id != "":
                cur.execute("SELECT 1 FROM msp_organizations WHERE org_id = %s", (req.tenant_id,))
                if not cur.fetchone():
                    raise HTTPException(400, f"Organização '{req.tenant_id}' não existe no banco de dados.")
                updates.append("tenant_id = %s")
                params.append(req.tenant_id)
            else:
                updates.append("tenant_id = NULL")
        if req.status is not None:
            updates.append("status = %s")
            params.append(req.status)
            
        if updates:
            params.append(user_id)
            query = f"UPDATE server_auth_users SET {', '.join(updates)} WHERE id = %s"
            cur.execute(query, tuple(params))
            
            # Registrar auditoria
            try:
                creator = _get_current_user_from_req(request) or {"username": "admin", "id": 1}
                cur.execute(
                    "INSERT INTO server_auth_audit (user_id, username, action, ip_address, details) VALUES (%s, %s, %s, %s, %s)",
                    (creator["id"], creator["username"], "UPDATE_USER", request.client.host, f"Atualizado usuário {username}. Atualizações: {', '.join(updates)}")
                )
            except Exception as audit_err:
                logger.warning(f"[USERS] Falha ao registrar log de auditoria: {audit_err}")
                
            conn.commit()
            
        cur.close()
        return JSONResponse({"status": "success", "message": "Usuário atualizado com sucesso"})
    except HTTPException:
        if conn: conn.rollback()
        raise
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"[USERS] Erro ao atualizar usuário {user_id}: {e}")
        raise HTTPException(500, f"Falha ao atualizar usuário: {str(e)}")
    finally:
        if conn: release_db(conn)

@router.post("/{user_id}/password")
async def change_user_password(user_id: int, req: UserPasswordReq, request: Request):
    """Redefine a senha de um usuário."""
    if len(req.new_password) < 4:
        raise HTTPException(400, "Nova senha deve ter pelo menos 4 caracteres")
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Verificar se usuário existe
        cur.execute("SELECT username FROM server_auth_users WHERE id = %s", (user_id,))
        user_row = cur.fetchone()
        if not user_row:
            raise HTTPException(404, "Usuário não encontrado")
        username = user_row[0]

        pw_hash = _hash_password(req.new_password)
        cur.execute("UPDATE server_auth_users SET password_hash = %s WHERE id = %s", (pw_hash, user_id))
        
        # Registrar auditoria
        try:
            creator = _get_current_user_from_req(request) or {"username": "admin", "id": 1}
            cur.execute(
                "INSERT INTO server_auth_audit (user_id, username, action, ip_address, details) VALUES (%s, %s, %s, %s, %s)",
                (creator["id"], creator["username"], "CHANGE_PASSWORD", request.client.host, f"Redefinida a senha do usuário {username}")
            )
        except Exception as audit_err:
            logger.warning(f"[USERS] Falha ao registrar log de auditoria: {audit_err}")
            
        conn.commit()
        cur.close()
        return JSONResponse({"status": "success", "message": "Senha atualizada com sucesso"})
    except HTTPException:
        if conn: conn.rollback()
        raise
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"[USERS] Erro ao redefinir senha do usuário {user_id}: {e}")
        raise HTTPException(500, f"Falha ao alterar senha: {str(e)}")
    finally:
        if conn: release_db(conn)

@router.delete("/{user_id}")
async def delete_user_endpoint(user_id: int, request: Request):
    """Remove um usuário do Servidor Central."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Verificar se usuário existe
        cur.execute("SELECT username FROM server_auth_users WHERE id = %s", (user_id,))
        user_row = cur.fetchone()
        if not user_row:
            raise HTTPException(404, "Usuário não encontrado")
        username = user_row[0]

        cur.execute("DELETE FROM server_auth_users WHERE id = %s", (user_id,))
        
        # Registrar auditoria
        try:
            creator = _get_current_user_from_req(request) or {"username": "admin", "id": 1}
            cur.execute(
                "INSERT INTO server_auth_audit (user_id, username, action, ip_address, details) VALUES (%s, %s, %s, %s, %s)",
                (creator["id"], creator["username"], "DELETE_USER", request.client.host, f"Excluído o usuário {username}")
            )
        except Exception as audit_err:
            logger.warning(f"[USERS] Falha ao registrar log de auditoria: {audit_err}")
            
        conn.commit()
        cur.close()
        return JSONResponse({"status": "success", "message": "Usuário removido com sucesso"})
    except HTTPException:
        if conn: conn.rollback()
        raise
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"[USERS] Erro ao remover usuário {user_id}: {e}")
        raise HTTPException(500, f"Falha ao excluir usuário: {str(e)}")
    finally:
        if conn: release_db(conn)
