from . import DB_TABLE_PREFIX

MIGRATIONS = {
    "sqlite": {
        "0.1.0": (
            f"CREATE TABLE '{DB_TABLE_PREFIX}polls' ("
            "guild_id INTEGER NOT NULL, "
            "channel_id INTEGER NOT NULL, "
            "message_id INTEGER NOT NULL, "
            "start_time TEXT, "  # date in iso format
            "end_time TEXT, "  # date in iso format
            "owner_id INTEGER NOT NULL, "
            "allow_multiple_votes INTEGER NOT NULL, "
            "state INTEGER NOT NULL, "  # one of the POLL_STATE values
            "CONSTRAINT message_link PRIMARY KEY (guild_id, channel_id, message_id))"
        )
    },
    "postgresql": {
        "0.1.0": (
            f"CREATE TABLE '{DB_TABLE_PREFIX}:polls' ("
            "guild_id BIGINT NOT NULL, "
            "channel_id BIGINT NOT NULL, "
            "message_id BIGINT NOT NULL, "
            "start_time TEXT, "  # date in iso format
            "end_time TEXT, "  # date in iso format
            "owner_id BIGINT NOT NULL, "
            "allow_multiple_votes SMALLINT NOT NULL, "
            "state SMALLINT NOT NULL, "  # one of the POLL_STATE values
            "CONSTRAINT message_link PRIMARY KEY (guild_id, channel_id, message_id))"
        )
    },
}
