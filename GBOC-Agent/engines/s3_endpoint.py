"""
Endpoint S3 próprio (S3 compatível: MinIO, SeaweedFS, Ceph...) para restic e Kopia.

Antes o restic usava sempre s3.amazonaws.com para o tipo "s3" (o endpoint informado no repositório era
ignorado) e o Kopia recebia o endpoint com "http://"/"https://", que ele não aceita. Sem endpoint o
comportamento continua o mesmo (Amazon S3).
"""
from typing import List, Optional


def restic_s3_repository(endpoint: Optional[str], path: str) -> str:
    """Valor de RESTIC_REPOSITORY. O restic aceita s3:http://host:porta/bucket para endpoint sem TLS."""
    ep = str(endpoint or '').strip().rstrip('/')
    path = str(path or '').strip().lstrip('/')
    return f"s3:{ep}/{path}" if ep else f"s3:s3.amazonaws.com/{path}"


def kopia_endpoint_args(endpoint: Optional[str]) -> List[str]:
    """--endpoint host[:porta] (sem esquema) e --disable-tls quando o endpoint é http://."""
    ep = str(endpoint or '').strip().rstrip('/')
    if not ep:
        return []
    low = ep.lower()
    if low.startswith('http://'):
        return ['--endpoint', ep[7:], '--disable-tls']
    if low.startswith('https://'):
        ep = ep[8:]
    return ['--endpoint', ep]
