"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from .constants import DB_PREFIX
from ...base import Revision, validate_revision_list as _

MIGRATIONS: list[Revision] = _(
    [
        {  # Revision: 0
            "date": "2026-05-08T02:11:00",
            "description": "Initial migration",
            "migrate": {
                "sqlite": [
                    f"CREATE TABLE '{DB_PREFIX}bots' ("
                    "    uid VARCHAR(64) PRIMARY KEY REFERENCES bots(uid) ON DELETE CASCADE NOT NULL)",
                    f"CREATE TABLE '{DB_PREFIX}cache_entries' ("
                    f"   uid VARCHAR(64) NOT NULL REFERENCES '{DB_PREFIX}bots'(uid) ON DELETE CASCADE,"
                    "    thread_id INTEGER PRIMARY KEY,"
                    "    name VARCHAR(200) NOT NULL,"
                    "    content TEXT NOT NULL"
                    ")",
                    f"CREATE TABLE '{DB_PREFIX}cache_keys' ("
                    f"    uid VARCHAR(64) NOT NULL REFERENCES '{DB_PREFIX}bots'(uid) ON DELETE CASCADE,"
                    "    key VARCHAR(100) PRIMARY KEY,"
                    f"    thread_id INTEGER NOT NULL REFERENCES '{DB_PREFIX}cache_entries'(thread_id) ON DELETE CASCADE"
                    ")",
                ],
                "postgresql": [
                    f"CREATE TABLE '{DB_PREFIX}bots' ("
                    "    uid VARCHAR(64) PRIMARY KEY REFERENCES bots(uid) ON DELETE CASCADE NOT NULL)",
                    f"CREATE TABLE '{DB_PREFIX}cache_entries' ("
                    f"    uid VARCHAR(64) NOT NULL REFERENCES '{DB_PREFIX}bots'(uid) ON DELETE CASCADE,"
                    "    thread_id BIGINT PRIMARY KEY,"
                    "    name VARCHAR(200) NOT NULL,"
                    "    content TEXT NOT NULL"
                    ")",
                    f"CREATE TABLE '{DB_PREFIX}cache_keys' ("
                    f"    uid VARCHAR(64) NOT NULL REFERENCES '{DB_PREFIX}bots'(uid) ON DELETE CASCADE,"
                    "    key VARCHAR(100) PRIMARY KEY,"
                    f"    thread_id BIGINT NOT NULL REFERENCES '{DB_PREFIX}cache_entries'(thread_id) ON DELETE CASCADE"
                    ")",
                ],
            },
            "rollback": {
                "sqlite": [
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}cache_keys'",
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}cache_entries'",
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}bots'",
                ],
                "postgresql": [
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}cache_keys'",
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}cache_entries'",
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}bots'",
                ],
            },
            "delete": {
                "sqlite": [
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}cache_keys'",
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}cache_entries'",
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}bots'",
                ],
                "postgresql": [
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}cache_keys'",
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}cache_entries'",
                    f"DROP TABLE IF EXISTS '{DB_PREFIX}bots'",
                ],
            },
        },
    ]
)
