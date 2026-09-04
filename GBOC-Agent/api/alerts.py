#!/usr/bin/env python3
"""
⚠️ GBOC Agent 14.0.0 - API ALERTS
Responsável por: Rotas para sistema de alertas e notificações
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any, List
import json
from datetime import datetime, timedelta
import logging

from shared_core import get_shared_core
from models import AlertCreate

logger = logging.getLogger("API-Alerts")
router = APIRouter(prefix="/api/alerts", tags=["alerts"])

@router.get("/")
async def list_alerts(
    severity: str = None, 
    resolved: bool = None, 
    limit: int = 50
) -> Dict[str, Any]:
    """Lista alertas do sistema"""
    try:
        core = get_shared_core()
        
        with core.get_db_connection() as conn:
            query = "SELECT id, timestamp, type, severity, title, message, source, acknowledged, resolved, details FROM alerts"
            params = []
            
            conditions = []
            if severity:
                conditions.append("severity = %s")
                params.append(severity)
            if resolved is not None:
                conditions.append("resolved = %s")
                params.append(resolved)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY timestamp DESC LIMIT %s"
            params.append(limit)

            cursor = conn.cursor()
            cursor.execute(query, params)
            
            alerts = []
            for row in cursor.fetchall():
                alert = {
                    "id": row[0],
                    "timestamp": row[1],
                    "type": row[2],
                    "severity": row[3],
                    "title": row[4],
                    "message": row[5],
                    "source": row[6],
                    "acknowledged": bool(row[7]),
                    "resolved": bool(row[8]),
                    "details": row[9]
                }
                alerts.append(alert)
            
            # Estatísticas
            stats = await _get_alert_statistics(core)
            
            return {
                "alerts": alerts,
                "stats": stats,
                "total": len(alerts),
                "severity_levels": {
                    "info": "Informativo",
                    "warning": "Aviso", 
                    "error": "Erro",
                    "critical": "Crítico"
                }
            }
    
    except Exception as e:
        logger.error(f"Error listing alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
async def create_alert(request: Request) -> Dict[str, Any]:
    """Cria novo alerta"""
    try:
        data = await request.json()
        core = get_shared_core()
        
        # Validar dados obrigatórios
        required_fields = ["type", "severity", "title", "message"]
        for field in required_fields:
            if field not in data:
                raise HTTPException(status_code=400, detail=f"Campo obrigatório: {field}")
        
        # Validar severity
        valid_severities = ["info", "warning", "error", "critical"]
        if data["severity"] not in valid_severities:
            raise HTTPException(status_code=400, detail=f"Severity inválida. Use: {', '.join(valid_severities)}")
        
        now = datetime.now().isoformat()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alerts (
                    timestamp, type, severity, title, message, source, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                now,
                data["type"],
                data["severity"],
                data["title"],
                data["message"],
                data.get("source", "manual"),
                data.get("details", "")
            ))
            
            alert_id = cursor.fetchone()[0]
            conn.commit()
        
        core.log_system_event("INFO", "alerts", f"Alert created: {data['title']}")
        
        # Processar notificações se configuradas
        await _process_alert_notifications(core, {
            "id": alert_id,
            "severity": data["severity"],
            "title": data["title"],
            "message": data["message"]
        })
        
        return {
            "success": True,
            "id": alert_id,
            "message": "Alerta criado com sucesso"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating alert: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{alert_id}")
async def get_alert(alert_id: int) -> Dict[str, Any]:
    """Obtém detalhes de um alerta"""
    try:
        core = get_shared_core()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, timestamp, type, severity, title, message, source, acknowledged, resolved, details FROM alerts WHERE id = %s", (alert_id,))
            row = cursor.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail="Alerta não encontrado")
            
            alert = {
                "id": row[0],
                "timestamp": row[1],
                "type": row[2],
                "severity": row[3],
                "title": row[4],
                "message": row[5],
                "source": row[6],
                "acknowledged": bool(row[7]),
                "resolved": bool(row[8]),
                "details": row[9]
            }
            
            return alert
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int) -> Dict[str, Any]:
    """Marca alerta como reconhecido"""
    try:
        core = get_shared_core()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title FROM alerts WHERE id = %s", (alert_id,))
            existing = cursor.fetchone()

            if not existing:
                raise HTTPException(status_code=404, detail="Alerta não encontrado")

            cursor.execute("""
                UPDATE alerts SET acknowledged = true WHERE id = %s
            """, (alert_id,))
            conn.commit()
        
        core.log_system_event("INFO", "alerts", f"Alert acknowledged: {existing[0]}")
        
        return {
            "success": True,
            "message": "Alerta marcado como reconhecido"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error acknowledging alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{alert_id}/resolve")
async def resolve_alert(alert_id: int) -> Dict[str, Any]:
    """Marca alerta como resolvido"""
    try:
        core = get_shared_core()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title FROM alerts WHERE id = %s", (alert_id,))
            existing = cursor.fetchone()

            if not existing:
                raise HTTPException(status_code=404, detail="Alerta não encontrado")

            cursor.execute("""
                UPDATE alerts SET resolved = true, acknowledged = true WHERE id = %s
            """, (alert_id,))
            conn.commit()
        
        core.log_system_event("INFO", "alerts", f"Alert resolved: {existing[0]}")
        
        return {
            "success": True,
            "message": "Alerta marcado como resolvido"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{alert_id}")
async def delete_alert(alert_id: int) -> Dict[str, Any]:
    """Remove alerta"""
    try:
        core = get_shared_core()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title FROM alerts WHERE id = %s", (alert_id,))
            existing = cursor.fetchone()

            if not existing:
                raise HTTPException(status_code=404, detail="Alerta não encontrado")

            cursor.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
            conn.commit()
        
        core.log_system_event("INFO", "alerts", f"Alert deleted: {existing[0]}")
        
        return {
            "success": True,
            "message": f"Alerta '{existing[0]}' removido com sucesso"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/bulk-action")
async def bulk_alert_action(request: Request) -> Dict[str, Any]:
    """Ação em lote para alertas"""
    try:
        data = await request.json()
        core = get_shared_core()

        alert_ids = data.get("alert_ids", [])
        action = data.get("action")  # acknowledge, resolve, delete

        if action not in ["acknowledge", "resolve", "delete"]:
            raise HTTPException(status_code=400, detail="Ação inválida")

        affected_count = 0

        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            # Suportar "all" para aplicar a todos os alertas
            if alert_ids == "all":
                if action == "acknowledge":
                    cursor.execute("UPDATE alerts SET acknowledged = true WHERE acknowledged = false")
                elif action == "resolve":
                    cursor.execute("UPDATE alerts SET resolved = true, acknowledged = true WHERE resolved = false")
                elif action == "delete":
                    cursor.execute("DELETE FROM alerts")
                affected_count = cursor.rowcount
            else:
                if not alert_ids:
                    raise HTTPException(status_code=400, detail="Lista de IDs de alertas é obrigatória")
                for alert_id in alert_ids:
                    cursor.execute("SELECT id FROM alerts WHERE id = %s", (alert_id,))
                    if cursor.fetchone():
                        if action == "acknowledge":
                            cursor.execute("UPDATE alerts SET acknowledged = true WHERE id = %s", (alert_id,))
                        elif action == "resolve":
                            cursor.execute("UPDATE alerts SET resolved = true, acknowledged = true WHERE id = %s", (alert_id,))
                        elif action == "delete":
                            cursor.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
                        affected_count += 1

            conn.commit()
        
        core.log_system_event("INFO", "alerts", f"Bulk action '{action}' applied to {affected_count} alerts")
        
        return {
            "success": True,
            "affected_count": affected_count,
            "message": f"Ação '{action}' aplicada a {affected_count} alertas"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk alert action: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/statistics/summary")
async def get_alert_summary() -> Dict[str, Any]:
    """Resumo estatístico dos alertas"""
    try:
        core = get_shared_core()
        stats = await _get_alert_statistics(core)
        
        # Alertas recentes (últimas 24h)
        cutoff_24h = (datetime.now() - timedelta(days=1)).isoformat()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT severity, COUNT(*) 
                FROM alerts 
                WHERE timestamp > %s 
                GROUP BY severity
            """, (cutoff_24h,))
            
            recent_by_severity = {}
            for row in cursor.fetchall():
                recent_by_severity[row[0]] = row[1]
        
        return {
            "overall": stats,
            "last_24h": {
                "total": sum(recent_by_severity.values()),
                "by_severity": recent_by_severity
            },
            "active_critical": stats["by_severity"].get("critical", 0) - stats["resolved_by_severity"].get("critical", 0),
            "pending_resolution": stats["total"] - stats["resolved_count"]
        }
        
    except Exception as e:
        logger.error(f"Error getting alert summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trends/{period}")
async def get_alert_trends(period: str) -> Dict[str, Any]:
    """Tendências de alertas por período"""
    try:
        core = get_shared_core()
        
        # Definir período
        if period == "24h":
            hours = 24
            interval = "1 hour"
        elif period == "7d":
            hours = 24 * 7
            interval = "1 day"
        elif period == "30d":
            hours = 24 * 30
            interval = "1 day"
        else:
            raise HTTPException(status_code=400, detail="Período inválido. Use: 24h, 7d, 30d")
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    DATE(timestamp) as date,
                    severity,
                    COUNT(*) as count
                FROM alerts 
                WHERE timestamp > %s
                GROUP BY DATE(timestamp), severity
                ORDER BY date, severity
            """, (cutoff_time.isoformat(),))
            
            trends = {}
            for row in cursor.fetchall():
                date = row[0]
                severity = row[1]
                count = row[2]
                
                if date not in trends:
                    trends[date] = {}
                trends[date][severity] = count
        
        return {
            "period": period,
            "trends": trends,
            "generated_at": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting alert trends: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/test")
async def create_test_alerts() -> Dict[str, Any]:
    """Cria alertas de teste para demonstração"""
    try:
        core = get_shared_core()
        
        test_alerts = [
            {
                "type": "system",
                "severity": "warning",
                "title": "Alto uso de CPU",
                "message": "CPU acima de 80% nos últimos 5 minutos",
                "source": "monitor"
            },
            {
                "type": "backup",
                "severity": "error",
                "title": "Falha no backup noturno",
                "message": "Backup da tarefa 'Documentos' falhou às 02:30",
                "source": "scheduler"
            },
            {
                "type": "repository",
                "severity": "critical",
                "title": "Repositório inacessível",
                "message": "Não foi possível conectar ao repositório S3",
                "source": "connectivity"
            },
            {
                "type": "system",
                "severity": "info",
                "title": "Backup concluído",
                "message": "Backup de 'Fotos' concluído com sucesso (2.3 GB)",
                "source": "scheduler"
            }
        ]
        
        created_count = 0
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            for alert_data in test_alerts:
                cursor.execute("""
                    INSERT INTO alerts (
                        timestamp, type, severity, title, message, source
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    datetime.now().isoformat(),
                    alert_data["type"],
                    alert_data["severity"],
                    alert_data["title"],
                    alert_data["message"],
                    alert_data["source"]
                ))
                created_count += 1
            
            conn.commit()
        
        core.log_system_event("INFO", "alerts", f"Created {created_count} test alerts")
        
        return {
            "success": True,
            "created_count": created_count,
            "message": f"{created_count} alertas de teste criados com sucesso"
        }
        
    except Exception as e:
        logger.error(f"Error creating test alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Funções auxiliares
async def _get_alert_statistics(core) -> Dict[str, Any]:
    """Estatísticas dos alertas"""
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            # Total de alertas
            cursor.execute("SELECT COUNT(*) FROM alerts")
            total = cursor.fetchone()[0]

            # Por severity
            cursor.execute("SELECT severity, COUNT(*) FROM alerts GROUP BY severity")
            by_severity = {}
            for row in cursor.fetchall():
                by_severity[row[0]] = row[1]

            # Por tipo
            cursor.execute("SELECT type, COUNT(*) FROM alerts GROUP BY type")
            by_type = {}
            for row in cursor.fetchall():
                by_type[row[0]] = row[1]

            # Resolvidos (com tratamento de erro se coluna não existir)
            resolved_count = 0
            acknowledged_count = 0
            resolved_by_severity = {}

            try:
                cursor.execute("SELECT COUNT(*) FROM alerts WHERE resolved = true")
                resolved_count = cursor.fetchone()[0]

                # Reconhecidos
                cursor.execute("SELECT COUNT(*) FROM alerts WHERE acknowledged = true")
                acknowledged_count = cursor.fetchone()[0]

                # Resolvidos por severity
                cursor.execute("""
                    SELECT severity, COUNT(*) FROM alerts 
                    WHERE resolved = true 
                    GROUP BY severity
                """)
                for row in cursor.fetchall():
                    resolved_by_severity[row[0]] = row[1]
            except Exception as col_error:
                logger.warning(f"Colunas resolved/acknowledged não disponíveis ainda: {col_error}")

            return {
                "total": total,
                "by_severity": by_severity,
                "by_type": by_type,
                "resolved_count": resolved_count,
                "acknowledged_count": acknowledged_count,
                "resolved_by_severity": resolved_by_severity,
                "resolution_rate": (resolved_count / total * 100) if total > 0 else 0
            }

    except Exception as e:
        logger.error(f"Error getting alert statistics: {e}")
        return {
            "total": 0,
            "by_severity": {},
            "by_type": {},
            "resolved_count": 0,
            "acknowledged_count": 0,
            "resolved_by_severity": {},
            "resolution_rate": 0,
            "error": str(e)
        }

async def _process_alert_notifications(core, alert: Dict[str, Any]):
    """Processa notificações para o alerta"""
    try:
        # Verificar configurações de notificação
        agent_state = get_shared_core().get_agent_state()
        notifications_config = agent_state.get("settings", {}).get("notifications", {})
        
        if not notifications_config.get("enabled", False):
            return
        
        # Filtrar por severity
        severity = alert["severity"]
        should_notify = False
        
        if severity == "critical":
            should_notify = True
        elif severity == "error" and notifications_config.get("notify_failure", True):
            should_notify = True
        elif severity == "warning" and notifications_config.get("notify_warning", False):
            should_notify = True
        elif severity == "info" and notifications_config.get("notify_success", False):
            should_notify = True
        
        if should_notify:
            # Webhook notification
            if notifications_config.get("webhook_enabled", False):
                await _send_webhook_notification(notifications_config, alert)
            
            # Email notification (se configurado)
            if notifications_config.get("email_enabled", False):
                await _send_email_notification(notifications_config, alert)
        
    except Exception as e:
        logger.error(f"Error processing alert notifications: {e}")

async def _send_webhook_notification(config: Dict, alert: Dict):
    """Envia notificação via webhook"""
    try:
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            return
        
        import aiohttp
        
        payload = {
            "alert_id": alert["id"],
            "severity": alert["severity"],
            "title": alert["title"],
            "message": alert["message"],
            "timestamp": datetime.now().isoformat(),
            "source": "GBOC Agent"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url, 
                json=payload, 
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    logger.info(f"Webhook notification sent for alert {alert['id']}")
                else:
                    logger.warning(f"Webhook notification failed: {response.status}")
                    
    except Exception as e:
        logger.error(f"Error sending webhook notification: {e}")

async def _send_email_notification(config: Dict, alert: Dict):
    """Envia notificação via email usando SMTP real"""
    try:
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        # Configurações SMTP
        smtp_server = config.get("smtp_server", "smtp.gmail.com")
        smtp_port = config.get("smtp_port", 587)
        smtp_username = config.get("smtp_username")
        smtp_password = config.get("smtp_password")
        from_email = config.get("from_email", smtp_username)
        to_emails = config.get("to_emails", [])

        if not all([smtp_username, smtp_password, to_emails]):
            logger.warning("Configuração de email incompleta - pulando envio")
            return

        # Criar mensagem
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = ", ".join(to_emails)
        msg['Subject'] = f"GBOC Alert: {alert.get('title', 'System Alert')}"

        # Corpo do email
        body = f"""
        <html>
        <body>
            <h2>GBOC System Alert</h2>
            <p><strong>Type:</strong> {alert.get('type', 'Unknown')}</p>
            <p><strong>Message:</strong> {alert.get('message', 'No message')}</p>
            <p><strong>Timestamp:</strong> {alert.get('timestamp', datetime.now().isoformat())}</p>
            <p><strong>Severity:</strong> {alert.get('severity', 'info')}</p>
            {f"<p><strong>Details:</strong> {alert.get('details', '')}</p>" if alert.get('details') else ""}
        </body>
        </html>
        """

        msg.attach(MIMEText(body, 'html'))

        # Enviar email
        await aiosmtplib.send(
            msg,
            hostname=smtp_server,
            port=smtp_port,
            username=smtp_username,
            password=smtp_password,
            use_tls=True
        )

        logger.info(f"Email enviado com sucesso para {len(to_emails)} destinatários")

    except ImportError:
        logger.warning("Biblioteca aiosmtplib não instalada - pulando envio de email")
    except Exception as e:
        logger.error(f"Erro ao enviar email: {e}")


@router.post("/test-notifications")
async def test_notifications():
    """Testa todas as configurações de notificação ativas"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        # Criar alerta de teste
        test_alert = {
            "id": "test-notification",
            "type": "test",
            "severity": "info",
            "title": "Teste de Notificações GBOC",
            "message": "Esta é uma notificação de teste para verificar se suas configurações estão funcionando corretamente.",
            "timestamp": datetime.now().isoformat(),
            "details": {
                "test_type": "manual_test",
                "source": "settings_interface"
            }
        }

        # Processar notificações
        await _process_alert_notifications(core, test_alert)

        return {
            "status": "success",
            "message": "Notificações de teste enviadas com sucesso"
        }

    except Exception as e:
        logger.error(f"Erro no teste de notificações: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

