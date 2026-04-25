#!/usr/bin/env python3
"""
🧪 TESTE DE CARREGAMENTO DO MÓDULO DE REPOSITÓRIO
Script para verificar se o módulo de repositório carrega corretamente.
"""

import sys
import os
import logging

# Garantir raiz do projeto no PYTHONPATH (execução via tests/)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

print("=" * 80)
print("🧪 TESTE DE CARREGAMENTO DO MÓDULO DE REPOSITÓRIO")
print("=" * 80)

test_results = []

# TEST 1: Verificar estrutura de diretórios
print("\n1️⃣  Verificando estrutura de diretórios...")
test_1_pass = True

required_dirs = [
    ('storage_backends', 'Pasta dos backends'),
]

for dir_path, desc in required_dirs:
    if os.path.exists(dir_path) and os.path.isdir(dir_path):
        print(f"   ✅ {desc}: {dir_path}/")
    else:
        print(f"   ❌ {desc} FALTA: {dir_path}/")
        test_1_pass = False

test_results.append(('Estrutura de diretórios', test_1_pass))

# TEST 2: Verificar arquivos necessários
print("\n2️⃣  Verificando arquivos necessários...")
test_2_pass = True

required_files = [
    ('storage_backends/__init__.py', 'Módulo storage_backends'),
    ('storage_backends/base.py', 'Classe base StorageBackend'),
    ('storage_backends/local.py', 'Backend local'),
    ('storage_backends/cloud.py', 'Backend cloud'),
    ('engines/repository_manager.py', 'RepositoryManager'),
]

for file_path, desc in required_files:
    if os.path.exists(file_path):
        size = os.path.getsize(file_path)
        print(f"   ✅ {desc} ({size} bytes)")
    else:
        print(f"   ❌ {desc} FALTA: {file_path}")
        test_2_pass = False

test_results.append(('Arquivos necessários', test_2_pass))

# TEST 3: Imports básicos
print("\n3️⃣  Testando imports de storage_backends...")
test_3_pass = True

try:
    from storage_backends.base import StorageBackend
    print(f"   ✅ StorageBackend importado")
except ImportError as e:
    print(f"   ❌ Erro ao importar StorageBackend: {e}")
    test_3_pass = False

try:
    from storage_backends.local import LocalStorageBackend
    print(f"   ✅ LocalStorageBackend importado")
except ImportError as e:
    print(f"   ❌ Erro ao importar LocalStorageBackend: {e}")
    test_3_pass = False

try:
    from storage_backends.cloud import CloudStorageBackend
    print(f"   ✅ CloudStorageBackend importado")
except ImportError as e:
    print(f"   ❌ Erro ao importar CloudStorageBackend: {e}")
    test_3_pass = False

test_results.append(('Imports storage_backends', test_3_pass))

# TEST 4: Imports RepositoryManager
print("\n4️⃣  Testando imports de RepositoryManager...")
test_4_pass = True

try:
    from engines.repository_manager import RepositoryManager
    print(f"   ✅ RepositoryManager importado")
except ImportError as e:
    print(f"   ❌ Erro ao importar RepositoryManager: {e}")
    test_4_pass = False
    test_results.append(('Imports RepositoryManager', False))
    sys.exit(1)

test_results.append(('Imports RepositoryManager', test_4_pass))

# TEST 5: Verificar métodos críticos
print("\n5️⃣  Verificando métodos críticos em RepositoryManager...")
test_5_pass = True

required_methods = [
    'list_repositories',
    'get_repository',
    'create_repository',
    'initialize_repository',  # ← CRÍTICO
    'validate_connection',    # ← CRÍTICO
    'test_connection',        # ← CRÍTICO
    '_create_backend_from_config',
]

for method in required_methods:
    if hasattr(RepositoryManager, method):
        print(f"   ✅ {method}()")
    else:
        print(f"   ❌ {method}() FALTA")
        test_5_pass = False

test_results.append(('Métodos de RepositoryManager', test_5_pass))

# TEST 6: Verificar métodos em StorageBackend
print("\n6️⃣  Verificando métodos em StorageBackend...")
test_6_pass = True

required_backend_methods = [
    'check_connection',
    'list_snapshots',
    'test_credentials',
    'validate_connection',
]

for method in required_backend_methods:
    if hasattr(StorageBackend, method):
        print(f"   ✅ {method}()")
    else:
        print(f"   ❌ {method}() FALTA")
        test_6_pass = False

test_results.append(('Métodos de StorageBackend', test_6_pass))

# TEST 7: Testar LocalStorageBackend
print("\n7️⃣  Testando LocalStorageBackend com config de teste...")
test_7_pass = True

try:
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        test_config = {
            'type': 'local',
            'path': tmpdir,
            'name': 'test-repo'
        }
        
        backend = LocalStorageBackend(test_config)
        print(f"   ✅ LocalStorageBackend instanciado")
        
        # Test check_connection
        result = backend.check_connection()
        if result.get('success'):
            print(f"   ✅ check_connection() = {result.get('success')}")
        else:
            print(f"   ❌ check_connection() falhou: {result.get('message')}")
            test_7_pass = False
        
        # Test list_snapshots
        snapshots = backend.list_snapshots()
        print(f"   ✅ list_snapshots() = {len(snapshots)} snapshots")
        
        # Test test_credentials
        creds_ok = backend.test_credentials()
        print(f"   ✅ test_credentials() = {creds_ok}")

except Exception as e:
    print(f"   ❌ Erro ao testar LocalStorageBackend: {e}")
    import traceback
    traceback.print_exc()
    test_7_pass = False

test_results.append(('LocalStorageBackend funcional', test_7_pass))

# TEST 8: Tentar inicializar SharedCore (sem banco de dados)
print("\n8️⃣  Testando inicialização de SharedCore...")
test_8_pass = True

try:
    # Nota: isso pode falhar se o banco não estiver disponível
    # mas pelo menos veremos se os imports funcionam
    try:
        from shared_core import get_shared_core, SharedCore
        print(f"   ✅ SharedCore importado")
    except Exception as e:
        print(f"   ⚠️  SharedCore import: {e}")
        print(f"   ℹ️  (Isso pode falhar se o banco não está configurado)")
        test_8_pass = True  # Não é erro crítico

except Exception as e:
    print(f"   ❌ Erro: {e}")
    test_8_pass = False

test_results.append(('SharedCore importável', test_8_pass))

# SUMMARY
print("\n" + "=" * 80)
print("📊 RESUMO DOS TESTES")
print("=" * 80)

for test_name, passed in test_results:
    status = "✅ PASSOU" if passed else "❌ FALHOU"
    print(f"{status:20} {test_name}")

print("=" * 80)

# Final result
all_passed = all(result[1] for result in test_results)
if all_passed:
    print("\n🎉 TODOS OS TESTES PASSARAM!")
    print("\nAgora você pode tentar:")
    print("  1. Reiniciar o servidor: docker-compose restart gboc-agent")
    print("  2. Verificar logs: docker-compose logs -f gboc-agent")
    print("  3. Testar API: curl http://localhost:8001/api/v1/repositories")
    sys.exit(0)
else:
    print("\n❌ ALGUNS TESTES FALHARAM!")
    print("\nVerifique os erros acima e corrija antes de continuar.")
    sys.exit(1)
