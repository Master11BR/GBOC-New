from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from shared_core import get_shared_core

router = APIRouter(prefix="/api/tasksops", tags=["Tasks Operations"])

class ForceStopRequest(BaseModel):
    execution_id: int

@router.post("/force-stop")
async def force_stop_endpoint(request: ForceStopRequest):
    """
    Força a parada de uma tarefa que pode estar travada.
    - Se o processo estiver rodando, ele é terminado.
    - Se for um registro órfão no banco (zumbi), ele é marcado como cancelado.
    """
    core = get_shared_core()
    if not core.task_manager:
        raise HTTPException(status_code=503, detail="Task Manager não inicializado")
    
    result = core.task_manager.force_stop_task(request.execution_id)
    
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
        
    return result