"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from . import DB_TABLE_PREFIX

MIGRATIONS = {
    "sqlite": {
        # Map extension version strings to and SQL statement strings or tuples of SQL
        # statement strings here. Make sure to prefix tables with DB_TABLE_PREFIX
        # (to avoid database table name collisions)
    },
    "postgresql": {
        # Map extension version strings to and SQL statement strings or tuples of SQL
        # statement strings here. Make sure to prefix tables with DB_TABLE_PREFIX
        # (to avoid database table name collisions)
    },
}
