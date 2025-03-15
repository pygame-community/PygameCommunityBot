"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import asyncio
import random

import discord
from discord.ext import commands, tasks
import snakecore

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot
MessageableGuildChannel = discord.TextChannel | discord.VoiceChannel | discord.Thread

PGC_GUILD_ID = 772505616680878080

PRESENCE_MAP = {
    discord.ActivityType.watching: ["the pygame community", "over fellow pygamers"],
    discord.ActivityType.playing: ["Hiss at newcomers", "at Pygame Community Discord"],
    discord.ActivityType.listening: [
        *("'pg!help'" for i in range(4)),
        "bugs in my head",
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
        "Complete our",
        "Have a look at our",
        "To get started here, please complete the",
    ),
    "grab": (
        ", grab roles and channels at",
        ". Then get some roles and channels in",
        ", take some roles and channels from",
        ", then grab yourself some shiny channels and roles at",
        ". Get some fancy roles and channels from",
        ", customize your experience at ",
        ", then get yourself some cool roles and channels at",
        ", then adjust your experience via",
        ", then take some roles and channels at",
        ". Go get some cool roles and channels at",
        ". Make yourself comfortable with",
        ", then grab some shiny roles and channels at",
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


class PGCCog(BaseExtensionCog, name="pgc"):
    def __init__(
        self,
        bot: BotT,
        theme_color: int | discord.Color = 0,
        honeypot_channel_id: int | None = None,
    ) -> None:
        super().__init__(bot, theme_color)
        self.honeypot_channel_id = honeypot_channel_id
        self.honeypot_victims = set()

    @commands.Cog.listener()
    async def on_ready(self):
        if not (task_loop := self.toggle_presence).is_running():
            task_loop.start()

    async def cog_unload(self) -> None:
        if (task_loop := self.toggle_presence).is_running():
            task_loop.cancel()

    @tasks.loop(seconds=30, reconnect=True)
    async def toggle_presence(self):
        await self.bot.change_presence(
            activity=discord.Activity(
                type=(key := random.choice(PRESENCES)),
                name=random.choice(PRESENCE_MAP[key]),
            )
        )

    toggle_presence.add_exception_type(ConnectionResetError)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not (
            message.guild
            and message.guild.id == PGC_GUILD_ID
            and (
                message.type
                in (
                    discord.MessageType.premium_guild_subscription,
                    discord.MessageType.premium_guild_tier_1,
                    discord.MessageType.premium_guild_tier_2,
                    discord.MessageType.premium_guild_tier_3,
                )
            )
            and message.channel.permissions_for(
                message.guild.get_member(self.bot.user.id)  # type: ignore
                or await message.guild.fetch_member(self.bot.user.id)  # type: ignore
            ).send_messages
        ):
            return

        if message.channel.id == self.honeypot_channel_id:
            await message.guild.ban(
                message.author, reason="Fell into snake pit", delete_message_days=1
            )

            if message.author.id not in self.honeypot_victims:
                self.honeypot_victims.add(message.author.id)
                await message.guild.unban(message.author, reason="Second chance")
            else:
                self.honeypot_victims.remove(message.author.id)

        if message.type == discord.MessageType.premium_guild_tier_1:
            await message.channel.send(
                "LETS GO 🎉 ! Thanks for boosting us to **LEVEL 1** "
                f"{message.author.mention}!"
            )

        elif message.type == discord.MessageType.premium_guild_tier_2:
            await message.channel.send(
                "LETS GOO FURTHER 🎉🎉 !! Huge thanks for boosting us to **LEVEL 2** "
                f"{message.author.mention}!!"
            )

        elif message.type == discord.MessageType.premium_guild_tier_3:
            await message.channel.send(
                "LETS KEEP GOOOING UP 🎉🎉🎉 !!! A MASSIVE thanks for boosting us to "
                f"**LEVEL 3** {message.author.mention}!!!"
            )

        elif message.type == discord.MessageType.premium_guild_subscription:
            await message.channel.send(
                f"Wow! Thanks for giving us a boost {message.author.mention}! 🤩"
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

        for _ in range(1080):
            if not member.pending:
                break
            await asyncio.sleep(20)
            # wait for a maximum of six hours for members stuck on the membership/rules
            # screening prompt

        greet = random.choice(BOT_WELCOME_MSG["greet"])
        check = random.choice(BOT_WELCOME_MSG["check"])
        grab = random.choice(BOT_WELCOME_MSG["grab"])
        end = random.choice(BOT_WELCOME_MSG["end"])

        await member.guild.system_channel.send(
            f"{greet} {member.mention}! {check} "
            + f"<id:guide>{grab} "
            + f"<id:customize> & <id:browse>{end}"
        )


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT, honeypot_channel_id: int | None = None) -> None:
    await bot.add_cog(PGCCog(bot, honeypot_channel_id=honeypot_channel_id))
