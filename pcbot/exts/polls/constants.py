import enum

DB_TABLE_PREFIX = f"{__package__}:"


class POLL_COLORS(enum.Enum):
    WAITING_FOR_START = 0x6434EB
    ONGOING = 0x6434EB
    ENDED = 0xD9840D


class POLL_STATE(enum.IntEnum):
    WAITING_FOR_START = enum.auto()
    """Poll has not started yet, and will do at `Poll.start_time`"""
    ONGOING = enum.auto()
    """Poll is ongoing and can be voted on"""
    CLOSED = enum.auto()
    """Poll was closed by user"""
    ENDED = enum.auto()
    """Poll has ended at `Poll.end_time`"""


del enum
