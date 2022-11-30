"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from .constants import DB_TABLE_PREFIX

MIGRATIONS = {
    "sqlite": {
        "0.1.0": (
            f"CREATE TABLE '{DB_TABLE_PREFIX}bad_help_thread_data' ("
            "    thread_id BIGINT PRIMARY KEY, "
            "    last_cautioned_ts REAL NOT NULL, "
            "    caution_message_ids BLOB NOT NULL);\n\n",
            f"CREATE TABLE '{DB_TABLE_PREFIX}inactive_help_thread_data' ("
            "    thread_id BIGINT PRIMARY KEY, "
            "    last_active_ts REAL NOT NULL, "
            "    alert_message_id BIGINT);\n\n",
        )
    },
    "postgresql": {
        "0.1.0": (
            f"CREATE TABLE '{DB_TABLE_PREFIX}bad_help_thread_data' ("
            "    thread_id BIGINT PRIMARY KEY, "
            "    last_cautioned_ts DOUBLE PRECISION NOT NULL, "
            "    caution_message_ids BYTEA NOT NULL);\n\n",
            f"CREATE TABLE '{DB_TABLE_PREFIX}inactive_help_thread_data' ("
            "    thread_id BIGINT PRIMARY KEY, "
            "    last_active_ts DOUBLE PRECISION NOT NULL, "
            "    alert_message_id BIGINT);\n\n",
        )
    },
}
