from . import DB_TABLE_PREFIX

MIGRATIONS = {
    "sqlite": {
        "0.1.0": (
            f"CREATE TABLE '{DB_TABLE_PREFIX}guild_tcmd_states' ("
            "    guild_id INTEGER, "
            "    tcmd_uuid UUID, "
            "    parent_tcmd_uuid UUID NOT NULL, "
            "    qualified_name VARCHAR(100) NOT NULL, "
            "    enabled INTEGER NOT NULL, "
            "    channels BLOB, "
            "    roles BLOB, "
            "    PRIMARY KEY (guild_id, tcmd_uuid))"
        )
    },
    "postgresql": {
        "0.1.0": (
            f"CREATE TABLE '{DB_TABLE_PREFIX}guild_tcmd_states' ("
            "    guild_id BIGINT NOT NULL, "
            "    tcmd_uuid UUID NOT NULL, "
            "    parent_tcmd_uuid UUID NOT NULL, "
            "    qualified_name VARCHAR(100) NOT NULL, "
            "    enabled SMALLINT NOT NULL, "
            "    channels BYTEA, "
            "    roles BYTEA, "
            "    PRIMARY KEY (guild_id, tcmd_uuid))"
        )
    },
}
