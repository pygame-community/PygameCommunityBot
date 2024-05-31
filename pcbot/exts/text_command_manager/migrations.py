"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from ...base import validate_revision_list as _
from ...types import Revision
from .constants import DB_PREFIX

MIGRATIONS: list[Revision] = _(
    [
        {  # revision 0
            "date": "2069-04-20T13:26:39",
            "description": "Initial migration",
            "migrate": {
                "sqlite": [
                    f"CREATE TABLE '{DB_PREFIX}bots' ("
                    "    uid VARCHAR(64) PRIMARY KEY REFERENCES bots(uid) ON DELETE CASCADE NOT NULL)",
                    ""
                    f"CREATE TABLE '{DB_PREFIX}guild_text_command_states' ("
                    f"    bot VARCHAR(64) REFERENCES '{DB_PREFIX}bots'(uid) ON DELETE CASCADE NOT NULL, "
                    "    guild_id INTEGER, "
                    "    text_command_uuid UUID NOT NULL, "
                    "    parent_text_command_uuid UUID NOT NULL, "
                    "    qualified_name VARCHAR(100) NOT NULL, "
                    "    enabled INTEGER NOT NULL, "
                    "    channels BLOB, "
                    "    roles BLOB, "
                    "    PRIMARY KEY (bot, guild_id, text_command_uuid))",
                ],
                "postgresql": [
                    f"CREATE TABLE '{DB_PREFIX}bots' ("
                    "    uid VARCHAR(64) PRIMARY KEY REFERENCES bots(uid) ON DELETE CASCADE NOT NULL)",
                    ""
                    f"CREATE TABLE '{DB_PREFIX}guild_text_command_states' ("
                    f"    bot VARCHAR(64) REFERENCES '{DB_PREFIX}bots'(uid) ON DELETE CASCADE NOT NULL, "
                    "    guild_id BIGINT NOT NULL, "
                    "    text_command_uuid UUID NOT NULL, "
                    "    parent_text_command_uuid UUID NOT NULL, "
                    "    qualified_name VARCHAR(100) NOT NULL, "
                    "    enabled SMALLINT NOT NULL, "
                    "    channels BYTEA, "
                    "    roles BYTEA, "
                    "    PRIMARY KEY (bot, guild_id, text_command_uuid))",
                ],
            },
            "rollback": {
                "sqlite": [f"DROP TABLE '{DB_PREFIX}guild_text_command_states'"],
                "postgresql": [f"DROP TABLE '{DB_PREFIX}guild_text_command_states'"],
            },
            "delete": {
                "sqlite": [f"DROP TABLE '{DB_PREFIX}guild_text_command_states'"],
                "postgresql": [f"DROP TABLE '{DB_PREFIX}guild_text_command_states'"],
            },
        },
    ]
)
