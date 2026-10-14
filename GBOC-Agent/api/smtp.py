#!/usr/bin/env python3
"""
GBOC Agent - API SMTP Configuration
Endpoints para configuração e teste de SMTP para notificações por email
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import psycopg2
import logging
import asyncio
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/smtp", tags=["smtp"])


class SMTPConfig(BaseModel):
    server: str
    port: int = 587
    username: str
    password: str
    use_tls: bool = True
    from_email: str
    from_name: str = "GBOC Backup System"


class SMTPTest(BaseModel):
    test_email: str


@router.post("/configure")
def configure_smtp(config: SMTPConfig) -> Dict[str, Any]:
    """Salva configuração SMTP no banco de dados"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        from engines import smtp_store
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            smtp_store.ensure_schema(cursor)
            password = config.password
            if not password or password == "********":          # senha em branco na tela: mantém a atual
                password = (smtp_store.load(cursor) or {}).get("password") or ""
            # Bancos com a tabela do migrador (coluna "host") passam a ter também "server" (nada é apagado)
            smtp_store.save(cursor, config.server, config.port, config.username, password, config.use_tls,
                            config.from_email, config.from_name)
            conn.commit()

        logger.info("✅ SMTP configuration saved")
        return {"status": "success", "message": "Configuração SMTP salva com sucesso"}

    except Exception as e:
        logger.error(f"❌ SMTP configure: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.post("/test")
async def test_smtp(test: SMTPTest) -> Dict[str, Any]:
    """Testa configuração SMTP enviando um email de teste"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        # Carregar configuração SMTP
        from engines import smtp_store
        with core.get_db_connection() as conn:
            config_data = smtp_store.load(conn.cursor())        # tabela com "server" ou "host"
        if not config_data or not config_data.get("server"):
            return {"status": "error", "message": "Configuração SMTP não encontrada. Configure primeiro."}

        # Criar mensagem de teste
        msg = MIMEMultipart()
        msg['From'] = f"{config_data['from_name']} <{config_data['from_email']}>"
        msg['To'] = test.test_email
        msg['Subject'] = "GBOC - Teste de Configuração SMTP"

        body = """
        <html>
        <body>
            <h2>Teste de Configuração SMTP - GBOC</h2>
            <p>Este é um email de teste enviado pelo sistema GBOC.</p>
            <p>Se você recebeu este email, a configuração SMTP está funcionando corretamente!</p>
            <br>
            <p><small>Enviado em: {datetime}</small></p>
        </body>
        </html>
        """.format(datetime="Agora")

        msg.attach(MIMEText(body, 'html'))

        # Enviar email (465 = SSL direto; demais portas = STARTTLS) fora do event loop
        try:
            await asyncio.to_thread(smtp_store.deliver, config_data, [test.test_email], msg)
        except Exception as send_err:
            logger.error(f"❌ SMTP test: {send_err}")
            return {"status": "error", "message": smtp_store.friendly_error(send_err)}

        logger.info(f"✅ SMTP test email sent to {test.test_email}")
        return {"status": "success", "message": "Email de teste enviado com sucesso"}

    except Exception as e:
        logger.error(f"❌ SMTP test: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def send_email_async(server: str, port: int, username: str, password: str, 
                          use_tls: bool, from_email: str, to_email: str, message) -> None:
    """Envia email de forma assíncrona usando aiosmtplib"""
    try:
        # Conectar ao servidor SMTP
        if use_tls:
            # STARTTLS
            smtp = aiosmtplib.SMTP(hostname=server, port=port, use_tls=False)
            await smtp.connect()
            await smtp.starttls()
            await smtp.login(username, password)
        else:
            # SMTP over SSL/TLS
            smtp = aiosmtplib.SMTP(hostname=server, port=port, use_tls=True)
            await smtp.connect()
            await smtp.login(username, password)

        # Enviar email
        await smtp.sendmail(from_email, to_email, message.as_string())
        await smtp.quit()

    except Exception as e:
        logger.error(f"❌ Send email async: {e}")
        raise


@router.get("/config")
def get_smtp_config() -> Dict[str, Any]:
    """Retorna configuração SMTP atual (sem senha)"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        from engines import smtp_store
        with core.get_db_connection() as conn:
            full = smtp_store.load(conn.cursor())               # tabela com "server" ou "host"
        if not full:
            return {"status": "success", "config": None}
        config_data = {k: full.get(k) for k in ("server", "port", "username", "use_tls", "from_email",
                                                "from_name", "updated_at")}
        config_data["password_set"] = bool(full.get("password"))

        return {"status": "success", "config": config_data}

    except Exception as e:
        logger.error(f"❌ Get SMTP config: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}