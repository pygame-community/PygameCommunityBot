import asyncio
import random
from typing import Union

import discord
from discord.ext import commands, tasks
import snakecore
from snakecore.commands.decorators import flagconverter_kwargs
from snakecore.commands.converters import CodeBlock, String, Parens

from .base import BaseCommandCog

BotT = Union[snakecore.commands.Bot, snakecore.commands.AutoShardedBot]
MessageableGuildChannel = Union[
    discord.TextChannel, discord.VoiceChannel, discord.Thread
]

PGC_GUILD_ID = 772505616680878080
SERVER_GUIDE_CHANNEL_ID = 772528306615615500
ROLES_CHANNEL_ID = 772535163195228200

PRESENCE_MAP = {
    discord.ActivityType.watching: ["the pygame community", "over fellow pygamers"],
    discord.ActivityType.playing: ["Hiss at newcomers", "at Pygame Community Discord"],
    discord.ActivityType.listening: [
        "to 'help' (mention me as a prefix)",
        "to bugs in my head",
    ],
}

PRESENCES = tuple(PRESENCE_MAP.keys())

BOT_WELCOME_MSG = {
    "greet": (
        "Hi",
        "Hello",
        "Welcome to **Pygame Community**",
        "Greetings",
        "Howdy",
        "Hi there, ",
        "Hey there",
        "*Hiss* Who's that? It's",
        "*Hiss* Welcome",
        "Hello there,",
        "Ooooh! Hello",
        "Hi there,",
        "*Hiss* Do I see a new user? *hiss*\n" + "Welcome to our wonderful chatroom",
        "Ooooh! It's",
        "Oooh! Look who has joined us, it's",
    ),
    "check": (
        "Check out our",
        "Make sure to check out the",
        "Take a look at our",
        "See our",
        "Please see our",
        "Be sure to read our",
        "Be sure to check the",
        "Be sure to check out our",
        "Read our",
        "Have a look at our",
        "To get started here, please read the",
    ),
    "grab": (
        ", grab",
        ". Then get some",
        ", take",
        ", then grab yourself some shiny",
        ". Get some fancy",
        ", get some",
        ", then get yourself some cool",
        ", then get yourself some",
        ", take some",
        ", then take some",
        ", then take some",
        ". Go get some cool roles at",
        ". Then go take some fancy",
        ", then grab some shiny",
    ),
    "end": (
        " and have fun!",
        ", then have fun with pygame!",
        ", then have fun with pygame! *hiss*",
        " and have a nice time!",
        " and enjoy your stay!",
        " and have some fun! *hisss*",
        " and have fun here!",
        " and have fun with pygame!",
        " and have a wonderful time!",
        " and join us!",
        " and join the fun!",
        " and have fun with pygame! *hisss*",
        " and have fun here! *hisss*",
    ),
}


class PGCActivity(BaseCommandCog, name="pgc-activity"):
    def __init__(self, bot: BotT, theme_color: Union[int, discord.Color] = 0) -> None:
        super().__init__(bot, theme_color)

    @commands.Cog.listener()
    async def on_ready(self):
        if not (task_loop := self.toggle_presence).is_running():
            task_loop.start()

    @tasks.loop(seconds=30, reconnect=False)
    async def toggle_presence(self):
        key = random.choice(PRESENCES)
        await self.bot.change_presence(
            activity=discord.Activity(
                type=key,
                name=random.choice(PRESENCE_MAP[key]),
            )
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not (
            member.guild.id == PGC_GUILD_ID
            and member.guild.system_channel
            and member.guild.system_channel.permissions_for(
                member.guild.get_member(self.bot.user.id)  # type: ignore
                or await member.guild.fetch_member(self.bot.user.id)  # type: ignore
            ).send_messages
        ):
            return

        if member.pending:
            await asyncio.sleep(60)  # wait a minute

        greet = random.choice(BOT_WELCOME_MSG["greet"])
        check = random.choice(BOT_WELCOME_MSG["check"])
        grab = random.choice(BOT_WELCOME_MSG["grab"])
        end = random.choice(BOT_WELCOME_MSG["end"])
        await member.guild.system_channel.send(
            f"{greet} {member.mention}! {check} "
            + f"<#{SERVER_GUIDE_CHANNEL_ID}>{grab} "
            + f"<#{ROLES_CHANNEL_ID}>{end}"
        )


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT):
    await bot.add_cog(PGCActivity(bot))
