CREATE ROLE compiler_reader LOGIN PASSWORD 'compiler_reader_test';
GRANT CONNECT ON DATABASE compiler_test TO compiler_reader;
GRANT USAGE ON SCHEMA public TO compiler_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE compiler_test IN SCHEMA public GRANT SELECT ON TABLES TO compiler_reader;
