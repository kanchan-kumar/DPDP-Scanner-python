SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'dpdp_scanner_sample'
  AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS dpdp_scanner_sample;
