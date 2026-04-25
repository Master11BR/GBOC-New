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
async def configure_smtp(config: SMTPConfig) -> Dict[str, Any]:
    """Salva configuração SMTP no banco de dados"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Criar tabela se não existir
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS smtp_config (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    server TEXT NOT NULL,
                    port INTEGER NOT NULL DEFAULT 587,
                    username TEXT NOT NULL,
                    password TEXT NOT NULL,
                    use_tls BOOLEAN NOT NULL DEFAULT TRUE,
                    from_email TEXT NOT NULL,
                    from_name TEXT NOT NULL DEFAULT 'GBOC Backup System',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Inserir ou atualizar configuração (PostgreSQL upsert)
            cursor.execute("""
                INSERT INTO smtp_config 
                (id, server, port, username, password, use_tls, from_email, from_name, updated_at)
                VALUES (1, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    server = EXCLUDED.server,
                    port = EXCLUDED.port,
                    username = EXCLUDED.username,
                    password = EXCLUDED.password,
                    use_tls = EXCLUDED.use_tls,
                    from_email = EXCLUDED.from_email,
                    from_name = EXCLUDED.from_name,
                    updated_at = NOW()
            """, (
                config.server,
                config.port,
                config.username,
                config.password,
                config.use_tls,
                config.from_email,
                config.from_name
            ))
            
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
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM smtp_config WHERE id = 1")
            row = cursor.fetchone()
            
            if not row:
                return {"status": "error", "message": "Configuração SMTP não encontrada. Configure primeiro."}
            
            columns = [desc[0] for desc in cursor.description]
            config_data = dict(zip(columns, row))

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

        # Enviar email
        await send_email_async(
            server=config_data['server'],
            port=config_data['port'],
            username=config_data['username'],
            password=config_data['password'],
            use_tls=config_data['use_tls'],
            from_email=config_data['from_email'],
            to_email=test.test_email,
            message=msg
        )

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
async def get_smtp_config() -> Dict[str, Any]:
    """Retorna configuração SMTP atual (sem senha)"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT server, port, username, use_tls, from_email, from_name, updated_at 
                FROM smtp_config WHERE id = 1
            """)
            row = cursor.fetchone()
            
            if not row:
                return {"status": "success", "config": None}
            
            columns = [desc[0] for desc in cursor.description]
            config_data = dict(zip(columns, row))

        return {"status": "success", "config": config_data}

    except Exception as e:
        logger.error(f"❌ Get SMTP config: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}