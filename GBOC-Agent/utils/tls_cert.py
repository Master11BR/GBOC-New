"""
Utilitário de TLS para GBOC — gera certificado autoassinado em disco se necessário.
Usa apenas a biblioteca `cryptography` que já está no requirements.txt.

Uso:
    from utils.tls_cert import ensure_tls_cert
    cert_path, key_path = ensure_tls_cert()   # gera em data/ se não existir
"""

from __future__ import annotations

import datetime
import ipaddress
import os
from pathlib import Path

# Diretório padrão: GBOC-Agent/data/
_DEFAULT_DIR = Path(__file__).parent.parent / "data"


def ensure_tls_cert(
    cert_file: str | None = None,
    key_file: str | None = None,
    *,
    cn: str = "GBOC-Agent",
    ip: str = "127.0.0.1",
    days: int = 3650,
) -> tuple[str, str]:
    """
    Garante que existe um par cert+chave PEM em disco.

    Lê GBOC_TLS_CERT / GBOC_TLS_KEY do ambiente para localização personalizada.
    Se os arquivos não existirem, gera um certificado autoassinado.

    Retorna (caminho_cert, caminho_chave) como strings absolutas.
    """
    cert_path = Path(
        cert_file
        or os.getenv("GBOC_TLS_CERT", str(_DEFAULT_DIR / "gboc_tls_cert.pem"))
    )
    key_path = Path(
        key_file
        or os.getenv("GBOC_TLS_KEY", str(_DEFAULT_DIR / "gboc_tls_key.pem"))
    )

    if cert_path.exists() and key_path.exists():
        return str(cert_path), str(key_path)

    _generate(cert_path, key_path, cn=cn, ip=ip, days=days)
    return str(cert_path), str(key_path)


def _generate(cert_path: Path, key_path: Path, *, cn: str, ip: str, days: int) -> None:
    """Gera chave RSA 2048 + certificado X.509 autoassinado e salva em disco."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as exc:
        raise RuntimeError(
            "Biblioteca 'cryptography' não encontrada. "
            "Execute: pip install cryptography"
        ) from exc

    cert_path.parent.mkdir(parents=True, exist_ok=True)

    # Gerar chave privada RSA 2048
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Atributos do subject / issuer
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "GBOC"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)

    # SANs: DNS localhost + IP fornecido
    san_list: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName(cn),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    if ip not in ("127.0.0.1", "localhost"):
        try:
            san_list.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            san_list.append(x509.DNSName(ip))

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .sign(private_key, hashes.SHA256())
    )

    # Salvar chave privada (sem senha — uso local)
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    # Salvar certificado
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print(f"[TLS] Certificado autoassinado gerado:")
    print(f"      cert → {cert_path}")
    print(f"      key  → {key_path}")
    print(f"      CN={cn}  válido por {days} dias")
    print(f"[TLS] Para confiar no cert no Windows (opcional):")
    print(f"      certutil -addstore Root \"{cert_path}\"")
