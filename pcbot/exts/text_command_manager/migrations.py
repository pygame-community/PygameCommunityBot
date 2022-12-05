"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from typing import Union
from . import DB_TABLE_PREFIX

REVISIONS: list[dict[str, str | tuple[str, ...]]] = [
    {  # revision 0
        "sqlite": (
            f"CREATE TABLE '{DB_TABLE_PREFIX}guild_tcmd_states' ("
            "    guild_id INTEGER, "
            "    tcmd_uuid UUID, "
            "    parent_tcmd_uuid UUID NOT NULL, "
            "    qualified_name VARCHAR(100) NOT NULL, "
            "    enabled INTEGER NOT NULL, "
            "    channels BLOB, "
            "    roles BLOB, "
            "    PRIMARY KEY (guild_id, tcmd_uuid))"
        ),
        "postgresql": (
            f"CREATE TABLE '{DB_TABLE_PREFIX}guild_tcmd_states' ("
            "    guild_id BIGINT NOT NULL, "
            "    tcmd_uuid UUID NOT NULL, "
            "    parent_tcmd_uuid UUID NOT NULL, "
            "    qualified_name VARCHAR(100) NOT NULL, "
            "    enabled SMALLINT NOT NULL, "
            "    channels BYTEA, "
            "    roles BYTEA, "
            "    PRIMARY KEY (guild_id, tcmd_uuid))"
        ),
    }
]

ROLLBACKS: list[dict[str, str | tuple[str, ...]]] = [
    {  # anti-revision 0
        "sqlite": (f"DROP TABLE '{DB_TABLE_PREFIX}guild_tcmd_states'"),
        "postgresql": (f"DROP TABLE '{DB_TABLE_PREFIX}guild_tcmd_states'"),
    }
]
