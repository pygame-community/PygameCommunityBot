from typing import TypedDict
from typing_extensions import NotRequired


class GuildTextCommandState(TypedDict):
    uuid: str  # a UUID string of the command's ID
    parent_uuid: str  # a UUID string of the parent command's ID
    enabled: int  # a 2 bit integer where 0b01 enables a command and 0b10 enables its subcommands
    channels: NotRequired[
        dict[int, bool]
    ]  # a dictionary of channel IDs to booleans that marks
    # in which channels a text command should be enabled in, or explicitly disabled
    # (if e.g. enabled by a parent command). If not missing, this will add to or override a parent
    # command's settings.
    roles: NotRequired[
        dict[int, bool]
    ]  # a dictionary of role IDs to booleans that marks
    # which roles enable the usage of a text command, or explicitly disables it
    # (if e.g. enabled by a parent command). If not missing, this will add to or override a parent
    # command's settings.


class GuildTextCommandData(TypedDict):
    states: dict[str, GuildTextCommandState]
