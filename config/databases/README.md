Database profile configs
========================

This directory contains per-database profile JSON files that can be loaded by the
scanner at runtime. Profiles keep database settings separate from the main
scanner config so each machine can select the appropriate database setup.

Profile format
--------------
Each profile is a JSON object. Only the `database` section is used by the
scanner; other fields are metadata for humans.

Example:
{
  "name": "mysql_local",
  "description": "Local MySQL sample",
  "labels": ["local", "mysql"],
  "database": {
    "connections": [
      {
        "name": "mysql_local_sample",
        "enabled": true,
        "type": "mysql",
        "url": "mysql://root:${DPDP_MYSQL_PASSWORD}@127.0.0.1:3306/dpdp_scanner_sample"
      }
    ]
  }
}

How to use
----------
CLI (profile name from this folder):
  ./dpdp-scan --enable-db --db mysql_local

CLI (explicit file path):
  ./dpdp-scan --enable-db --db config/databases/mysql_local.json

Config file:
  "sources": {
    "database": {
      "profile_dir": "../databases",
      "profiles": ["mysql_local"]
    }
  }

Notes
-----
- Store secrets in environment variables and reference them in URLs/auth blocks.
- Add new profiles for cloud databases (RDS, Snowflake, BigQuery, Athena, etc.)
  by following the same shape and updating `type` / `piicatcher` settings.
- Optional fields for multi-database scans:
  `include_databases`, `exclude_databases`, and `include_all_databases`.
  If no database is specified, the scanner will attempt to discover and scan
  all available databases for supported engines.
