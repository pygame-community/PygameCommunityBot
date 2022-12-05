"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from typing import Union
from . import DB_TABLE_PREFIX

# A list of dictionaries mapping database names/dialects to an SQL statement string or
# a tuple of them. Revision versions are the indices of the list.
# Make sure to prefix tables with DB_TABLE_PREFIX
# (to avoid database table name collisions and for easier database management)
REVISIONS: list[dict[str, str | tuple[str, ...]]] = [
    {"sqlite": (""), "postgresql": ("")},  # revision 0
    {"sqlite": (""), "postgresql": ("")},  # revision 1
    # other migration revisions and statements would be added here, label them as shown
    # above for readability
]

# An antithesis of REVISIONS, that undoes any changes done by a matching revision in
# REVISIONS. Data loss should be prevented, if possible.
ROLLBACKS: list[dict[str, str | tuple[str, ...]]] = [
    {"sqlite": (""), "postgresql": ("")},  # anti-revision 0
    {"sqlite": (""), "postgresql": ("")},  # anti-revision 1
    # other migration anti-revisions and statements would be added here, label them as shown
    # above for readability
]
