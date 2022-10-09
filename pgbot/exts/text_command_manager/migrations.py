from . import DB_TABLE_PREFIX

MIGRATIONS = {
    "sqlite": {
        "0.1.0": f"CREATE TABLE '{DB_TABLE_PREFIX}guild_tcmd_states' (guild_id INTEGER PRIMARY KEY, data BLOB);"
    },
    "postgresql": {
        "0.1.0": f"CREATE TABLE '{DB_TABLE_PREFIX}guild_tcmd_states' (guild_id BIGINT PRIMARY KEY, data BYTEA);"
    },
}
