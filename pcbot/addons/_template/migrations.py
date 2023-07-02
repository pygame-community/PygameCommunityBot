"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from ...base import Revision, validate_revision_list as _

MIGRATIONS: list[Revision] = _(
    [
        {  # Revision: 0
            "date": "2069-04-20T13:26:39",
            "description": "Initial migration",
            # creates, updates or deletes database tables used by this bot extension
            "migrate": {
                "sqlite": [
                    # '{DB_PREFIX}bots' is a special table to be referenced by other
                    # tables used by this bot extension, in order to enable cascading
                    # per-bot data deletion. It is done by declaring a 'FOREIGN KEY'
                    # constraint with 'ON DELETE CASCADE' on those tables.
                    #
                    # The table in turn references the global 'bots' table in the same way,
                    # , thereby enabling cascading per-bot data deletion on a global level,
                    # across all bot extensions.
                    #
                    # f"CREATE TABLE '{DB_PREFIX}bots' ("
                    # "    uid VARCHAR(64) PRIMARY KEY REFERENCES bots(uid) ON DELETE CASCADE NOT NULL)"
                    ""
                ],
                "postgresql": [
                    # f"CREATE TABLE '{DB_PREFIX}bots' ("
                    # "    uid VARCHAR(64) PRIMARY KEY REFERENCES bots(uid) ON DELETE CASCADE NOT NULL)",
                    "",
                ],
            },
            # undoes the changes applied by "migrate" field
            "rollback": {"sqlite": [""], "postgresql": [""]},
            # Deletes all database tables used by this extension, based on the database
            # changes applied by this revision. This field only needs to be redefined
            # in subsequent revisions if they make structural changes that would
            # invalidate the SQL of this specific field.
            "delete": {"sqlite": [""], "postgresql": [""]},
        },
        # {   # Revision: 1
        #     "date": "2070-12-31T23:59:59",
        #     "description": "...",
        #     "migrate": {
        #         "sqlite": [
        #             "CREATE TABLE {DB_PREFIX}my_table (...)",
        #         ],
        #         "postgresql": [
        #             "CREATE TABLE {DB_PREFIX}my_table (...)\n",
        #         ],
        #     },
        #     "rollback": {
        #         "sqlite": [
        #             "DROP TABLE {DB_PREFIX}my_table (...)",
        #         ],
        #         "postgresql": [
        #             "DROP TABLE {DB_PREFIX}my_table (...)",
        #         ],
        #     },
        #     "delete": {  # redefined in this revision to incorporate new table(s) in deletion
        #         "sqlite": [
        #             "DROP TABLE {DB_PREFIX}my_table (...)",
        #             "...",  # additional deletions to make
        #         ],
        #         "postgresql": [
        #             "DROP TABLE {DB_PREFIX}my_table (...)",
        #             "..."
        #         ],
        #     },
        # },
        # ...,
        # other migration revisions would be added here, label them as shown
        # above ('# revision x') for readability and easier searching
    ]
)
"""A list of "Revision" dictionaries with "migration", "rollback" and "delete" lists
of SQL commands grouped by database name/dialect.
Revision versions are the indices of the list.
Database tables must always prefix tables with ``DB_PREFIX``
(to avoid database table name collisions and for easier database table deletion)
"""
