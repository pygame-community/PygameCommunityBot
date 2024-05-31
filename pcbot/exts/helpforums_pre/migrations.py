"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from ...base import Revision, validate_revision_list as _
from .constants import DB_PREFIX

MIGRATIONS: list[Revision] = _(
    [
        {  # revision 0
            "date": "2069-04-20T13:26:39",
            "description": "Initial migration",
            "migrate": {
                "sqlite": [
                    f"CREATE TABLE '{DB_PREFIX}bad_help_thread_data' ("
                    "    thread_id BIGINT PRIMARY KEY, "
                    "    last_cautioned_ts REAL NOT NULL, "
                    "    caution_message_ids BLOB NOT NULL);\n\n",
                    f"CREATE TABLE '{DB_PREFIX}inactive_help_thread_data' ("
                    "    thread_id BIGINT PRIMARY KEY, "
                    "    last_active_ts REAL NOT NULL, "
                    "    alert_message_id BIGINT);\n\n",
                ],
                "postgresql": [
                    f"CREATE TABLE '{DB_PREFIX}bad_help_thread_data' ("
                    "    thread_id BIGINT PRIMARY KEY, "
                    "    last_cautioned_ts DOUBLE PRECISION NOT NULL, "
                    "    caution_message_ids BYTEA NOT NULL);\n\n",
                    f"CREATE TABLE '{DB_PREFIX}inactive_help_thread_data' ("
                    "    thread_id BIGINT PRIMARY KEY, "
                    "    last_active_ts DOUBLE PRECISION NOT NULL, "
                    "    alert_message_id BIGINT);\n\n",
                ],
            },
            "rollback": {
                "sqlite": [f"DROP TABLE '{DB_PREFIX}bad_help_thread_data';"],
                "postgresql": [f"DROP TABLE '{DB_PREFIX}inactive_help_thread_data';"],
            },
            "delete": {
                "sqlite": [f"DROP TABLE '{DB_PREFIX}bad_help_thread_data';"],
                "postgresql": [f"DROP TABLE '{DB_PREFIX}inactive_help_thread_data';"],
            },
        },
    ]
)
