from typing import TypedDict
from typing_extensions import NotRequired


class GuildTextCommandState(TypedDict):

    tcmd_uuid: str
    "A UUID string representing the command's ID."
    parent_tcmd_uuid: str
    "A UUID string representing the parent command's ID."
    qualified_name: str
    "The qualified name of the text command."
    enabled: int
    "A 2 bit integer where ( 1 << 0 ) enables a command and ( 1 << 1 ) enables its "
    "subcommands. If set to 0b01, all subcommands of a command will be recursively "
    "disabled."
    channels: NotRequired[dict[int, bool]]
    """A dictionary of channel IDs to booleans that marks
    in which channels a text command should be enabled in, or explicitly disabled
    (if e.g. enabled by a parent command). If not missing, this will override or add "
    "to a parent's setting, depending on whether the "All Channels" sentinel "
    "(guild ID - 1)  is specified or not.
    command's settings
    """
    roles: NotRequired[dict[int, bool]]
    """A dictionary of role IDs to booleans that marks
    which roles enable the usage of a text command, or explicitly disables it
    (if e.g. enabled by a parent command). If not missing, this will override or add "
    "to a parent's setting, depending on whether the "@everyone" role (guild ID) "
    "is specified or not.
    """
