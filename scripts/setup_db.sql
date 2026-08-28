-- AvoLex — créer la base (PostgreSQL 16)
-- Exemple Windows (mot de passe postgres = 123456) :
--   $env:PGPASSWORD='123456'
--   & "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h 127.0.0.1 -f scripts\setup_db.sql

SELECT 'CREATE DATABASE "AvoLexMJ_db" OWNER postgres'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'AvoLexMJ_db')\gexec

\c "AvoLexMJ_db"
GRANT ALL ON SCHEMA public TO postgres;
ALTER SCHEMA public OWNER TO postgres;
