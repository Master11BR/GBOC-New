"""
GBOC Server - Autenticação JWT Melhorada
Suporta access tokens e refresh tokens com segurança aprimorada
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import hashlib
import secrets
import jwt
import os
from config import (
    SECRET_KEY, ALGORITHM, JWT_EXPIRATION, JWT_REFRESH_EXPIRATION,
    MAX_LOGIN_ATTEMPTS, LOCKOUT_DURATION_MINUTES, PASSWORD_MIN_LENGTH
)
from logger import setup_logger

logger = setup_logger(__name__)

class JWTHandler:
    """Gerenciador de JWT com refresh tokens"""

    @staticmethod
    def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """
        Cria um access token JWT

        Args:
            data: Dados a incluir no token
            expires_delta: Tempo de expiração customizado

        Returns:
            Token JWT codificado
        """
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + JWT_EXPIRATION

        to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc), "type": "access"})

        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        logger.info(f"Access token criado para usuário: {data.get('sub')}")
        return encoded_jwt

    @staticmethod
    def create_refresh_token(data: Dict[str, Any]) -> str:
        """
        Cria um refresh token JWT

        Args:
            data: Dados a incluir no token

        Returns:
            Refresh token JWT codificado
        """
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + JWT_REFRESH_EXPIRATION
        to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc), "type": "refresh"})

        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        logger.info(f"Refresh token criado para usuário: {data.get('sub')}")
        return encoded_jwt

    @staticmethod
    def verify_token(token: str, token_type: str = "access") -> Optional[Dict[str, Any]]:
        """
        Verifica e decodifica um token JWT

        Args:
            token: Token JWT a verificar
            token_type: Tipo de token esperado ("access" ou "refresh")

        Returns:
            Dados do token se válido, None se inválido
        """
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

            # Validar tipo de token
            if payload.get("type") != token_type:
                logger.warning(f"Token com tipo incorreto: esperado {token_type}, got {payload.get('type')}")
                return None

            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token expirado")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Token inválido: {e}")
            return None

    @staticmethod
    def refresh_access_token(refresh_token: str) -> Optional[str]:
        """
        Gera um novo access token usando um refresh token

        Args:
            refresh_token: Refresh token válido

        Returns:
            Novo access token ou None se falhar
        """
        payload = JWTHandler.verify_token(refresh_token, token_type="refresh")
        if not payload:
            return None

        # Remover claims que não devem ser copiados
        payload.pop("exp", None)
        payload.pop("iat", None)
        payload.pop("type", None)

        new_access_token = JWTHandler.create_access_token(payload)
        logger.info(f"Access token renovado para usuário: {payload.get('sub')}")
        return new_access_token

class PasswordManager:
    """Gerenciador de senhas com hash seguro"""

    SALT = os.getenv("PASSWORD_SALT", "gboc_secure_salt_2025")

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Faz hash seguro de senha usando PBKDF2

        Args:
            password: Senha em texto plano

        Returns:
            Hash da senha
        """
        if len(password) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"Senha deve ter no mínimo {PASSWORD_MIN_LENGTH} caracteres")

        hash_obj = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            PasswordManager.SALT.encode("utf-8"),
            100000  # Iterações
        )
        return hash_obj.hex()

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """
        Verifica se a senha corresponde ao hash

        Args:
            password: Senha em texto plano
            password_hash: Hash da senha

        Returns:
            True se corresponder, False caso contrário
        """
        try:
            return PasswordManager.hash_password(password) == password_hash
        except Exception as e:
            logger.error(f"Erro ao verificar senha: {e}")
            return False

class TokenManager:
    """Gerenciador de tokens com blacklist e revogação"""

    # Tokens revogados (em memória - considere usar Redis em produção)
    _revoked_tokens: set = set()

    @staticmethod
    def revoke_token(token: str) -> None:
        """
        Revoga um token adicionando à blacklist

        Args:
            token: Token a revogar
        """
        TokenManager._revoked_tokens.add(token)
        logger.info("Token revogado")

    @staticmethod
    def is_token_revoked(token: str) -> bool:
        """
        Verifica se um token foi revogado

        Args:
            token: Token a verificar

        Returns:
            True se revogado, False caso contrário
        """
        return token in TokenManager._revoked_tokens

    @staticmethod
    def clear_expired_tokens() -> None:
        """Limpa tokens expirados da blacklist"""
        # Em um sistema de produção, isso seria feito periodicamente via job
        logger.debug("Limpando tokens expirados")

class LoginAttemptTracker:
    """Rastreador de tentativas de login para prevenir força bruta"""

    # Formato: {username: {"attempts": int, "locked_until": datetime}}
    _login_attempts: Dict[str, Dict] = {}

    @staticmethod
    def record_failed_attempt(username: str) -> bool:
        """
        Registra uma tentativa de login falhada

        Args:
            username: Nome de usuário

        Returns:
            True se a conta está bloqueada, False caso contrário
        """
        if username not in LoginAttemptTracker._login_attempts:
            LoginAttemptTracker._login_attempts[username] = {
                "attempts": 0,
                "locked_until": None
            }

        attempt_data = LoginAttemptTracker._login_attempts[username]

        # Verificar se está bloqueado
        if attempt_data["locked_until"] and datetime.now(timezone.utc) < attempt_data["locked_until"]:
            return True

        # Incrementar tentativas
        attempt_data["attempts"] += 1
        logger.warning(f"Tentativa de login falhada para {username} ({attempt_data['attempts']}/{MAX_LOGIN_ATTEMPTS})")

        # Bloquear se necessário
        if attempt_data["attempts"] >= MAX_LOGIN_ATTEMPTS:
            attempt_data["locked_until"] = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            logger.warning(f"Conta {username} bloqueada por {LOCKOUT_DURATION_MINUTES} minutos")
            return True

        return False

    @staticmethod
    def reset_attempts(username: str) -> None:
        """
        Reseta as tentativas de login para um usuário

        Args:
            username: Nome de usuário
        """
        if username in LoginAttemptTracker._login_attempts:
            LoginAttemptTracker._login_attempts[username]["attempts"] = 0
            LoginAttemptTracker._login_attempts[username]["locked_until"] = None
            logger.info(f"Tentativas de login resetadas para {username}")

    @staticmethod
    def is_locked(username: str) -> bool:
        """
        Verifica se uma conta está bloqueada

        Args:
            username: Nome de usuário

        Returns:
            True se bloqueada, False caso contrário
        """
        if username not in LoginAttemptTracker._login_attempts:
            return False

        attempt_data = LoginAttemptTracker._login_attempts[username]

        if attempt_data["locked_until"] and datetime.now(timezone.utc) < attempt_data["locked_until"]:
            return True

        return False
