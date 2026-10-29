CREATE USER 'compiler_reader'@'%' IDENTIFIED BY 'compiler_reader_test';
GRANT SELECT ON compiler_test.* TO 'compiler_reader'@'%';
