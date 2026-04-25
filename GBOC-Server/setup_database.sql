-- Script de Criação do Banco de Dados GBOC
-- Execute como superusuário do PostgreSQL (postgres)

-- Cria o usuário (idempotente)
DO $$
BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gboc_user') THEN
      CREATE ROLE gboc_user LOGIN PASSWORD 'Stoms2025+';
   END IF;
END $$;

-- Cria o banco se não existir (fora de transação implícita)
SELECT 'CREATE DATABASE gboc OWNER gboc_user'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gboc')\gexec

-- Conecta no banco gboc
\c gboc

-- Garantir owner e permissões no schema public
ALTER DATABASE gboc OWNER TO gboc_user;
GRANT ALL PRIVILEGES ON DATABASE gboc TO gboc_user;
ALTER SCHEMA public OWNER TO gboc_user;
GRANT USAGE, CREATE ON SCHEMA public TO gboc_user;

-- Concede privilégios em objetos existentes
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO gboc_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO gboc_user;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO gboc_user;

-- Ajusta permissões padrão para objetos futuros
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO gboc_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO gboc_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO gboc_user;

\echo '✓ Banco de dados GBOC pronto'
\echo '✓ Usuário gboc_user configurado com permissões no schema public'
