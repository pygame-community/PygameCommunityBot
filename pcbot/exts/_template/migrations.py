"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from . import DB_TABLE_PREFIX

MIGRATIONS = {
    "sqlite": {
        # map version strings to sql command strings. Make sure to prefix tables with
        # DB_TABLE_PREFIX (to avoid database table name collisions)
    },
    "postgresql": {
        # map version strings to sql command strings. Make sure to prefix tables with
        # DB_TABLE_PREFIX (to avoid database table name collisions)
    },
}
