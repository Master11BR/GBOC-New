# GBOC System v14.0.0 Enterprise Edition
# Module: Multi-Tenant MSP Router

import logging
from typing import Optional
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

logger = logging.getLogger("gboc_multitenant_module")
router = APIRouter(prefix="/api/v1/tenant", tags=["Multi-Tenant MSP"])

class OrgCreateReq(BaseModel):
    id: str
    name: str
    plan: Optional[str] = "Standard"
    max_agents: Optional[int] = 25
    status: Optional[str] = "active"

class OrgUpdateReq(BaseModel):
    name: Optional[str] = None
    plan: Optional[str] = None
    max_agents: Optional[int] = None
    status: Optional[str] = None

@router.get("/organizations")
async def get_tenant_organizations():
    """Retorna lista de organizações MSP configuradas no banco PostgreSQL."""
    conn = None
    try:
        conn = get_db()
        if not conn:
            raise HTTPException(status_code=500, detail="Sem conexão com o banco de dados")
        cur = conn.cursor()
        cur.execute("SELECT org_id, name, plan, max_agents, status, created_at FROM msp_organizations ORDER BY name")
        rows = cur.fetchall()
        orgs = []
        for r in rows:
            orgs.append({
                "id": r[0],
                "name": r[1],
                "plan": r[2] or "Standard",
                "max_agents": r[3] or 25,
                "status": r[4] or "active",
                "created_at": str(r[5]) if r[5] else None
            })
        cur.close()
        return JSONResponse({"status": "success", "organizations": orgs})
    except Exception as e:
        logger.error(f"[MULTITENANT] Erro ao obter organizações: {e}")
        return JSONResponse({"status": "error", "message": f"Erro interno: {str(e)}"}, status_code=500)
    finally:
        if conn: release_db(conn)

@router.post("/organizations")
async def create_tenant_organization(req: OrgCreateReq, request: Request):
    """Cria uma nova organização MSP no banco PostgreSQL."""
    conn = None
    try:
        conn = get_db()
        if not conn:
            raise HTTPException(status_code=500, detail="Sem conexão com o banco de dados")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO msp_organizations (org_id, name, plan, max_agents, status) VALUES (%s, %s, %s, %s, %s) RETURNING org_id",
            (req.id, req.name, req.plan, req.max_agents, req.status)
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return JSONResponse({
            "status": "success", 
            "message": "Organização MSP criada com sucesso!", 
            "organization": {"id": new_id, "name": req.name, "plan": req.plan, "max_agents": req.max_agents, "status": req.status}
        })
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"[MULTITENANT] Erro ao criar organização: {e}")
        return JSONResponse({"status": "error", "message": f"Erro ao criar organização: {str(e)}"}, status_code=400)
    finally:
        if conn: release_db(conn)

@router.put("/organizations/{org_id}")
async def update_tenant_organization(org_id: str, req: OrgUpdateReq):
    """Atualiza dados e limites de uma organização MSP."""
    conn = None
    try:
        conn = get_db()
        if not conn:
            raise HTTPException(status_code=500, detail="Sem conexão com o banco de dados")
        cur = conn.cursor()
        
        updates = []
        params = []
        if req.name is not None:
            updates.append("name = %s")
            params.append(req.name)
        if req.plan is not None:
            updates.append("plan = %s")
            params.append(req.plan)
        if req.max_agents is not None:
            updates.append("max_agents = %s")
            params.append(req.max_agents)
        if req.status is not None:
            updates.append("status = %s")
            params.append(req.status)
            
        if not updates:
            return JSONResponse({"status": "error", "message": "Nenhum campo para atualizar"}, status_code=400)
            
        params.append(org_id)
        query = f"UPDATE msp_organizations SET {', '.join(updates)} WHERE org_id = %s"
        cur.execute(query, tuple(params))
        conn.commit()
        cur.close()
        
        return JSONResponse({"status": "success", "message": "Organização MSP atualizada com sucesso!"})
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"[MULTITENANT] Erro ao atualizar organização {org_id}: {e}")
        return JSONResponse({"status": "error", "message": f"Erro ao atualizar: {str(e)}"}, status_code=400)
    finally:
        if conn: release_db(conn)

@router.delete("/organizations/{org_id}")
async def delete_tenant_organization(org_id: str):
    """Exclui uma organização MSP do banco."""
    conn = None
    try:
        conn = get_db()
        if not conn:
            raise HTTPException(status_code=500, detail="Sem conexão com o banco de dados")
        cur = conn.cursor()
        cur.execute("DELETE FROM msp_organizations WHERE org_id = %s", (org_id,))
        conn.commit()
        cur.close()
        return JSONResponse({"status": "success", "message": "Organização MSP removida com sucesso!"})
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"[MULTITENANT] Erro ao remover organização {org_id}: {e}")
        return JSONResponse({"status": "error", "message": f"Erro ao remover: {str(e)}"}, status_code=400)
    finally:
        if conn: release_db(conn)
