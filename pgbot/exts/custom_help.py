import asyncio
import re
import typing

import discord
from discord.ext import commands
import snakecore

from pgbot import constants, PygameBot, utils
from .base import BaseCommandCog

BotT = PygameBot

# regex for doc string
cmd_docstring_regex = re.compile(
    # If you add a new "section" to this regex dont forget the "|" at the end
    # Does not have to be in the same order in the docs as in here.
    r"(->type|"
    r"->signature|"
    r"->description|"
    r"->example command|"
    r"->extended description\n|"
    r"\Z)|(((?!->).|\n)*)"
)

BOT_HELP_DIALOG_FSTRING = """
Hey there, do you want to use {0} ?
My command prefixes are `{1}`.
If you want me to run your code, use Discord's code block syntax.
If you want to know about a specifc command run `help <command>`.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


def get_doc_from_func(func: typing.Callable):
    """
    Get the type, signature, description and other information from docstrings.

    Args:
        func (typing.Callable): The function to get formatted docs for

    Returns:
        Dict[str] or Dict[]: The type, signature and description of
        the string. An empty dict will be returned if the string begins
        with "->skip" or there was no information found
    """
    string = func.__doc__
    if not string:
        return {}

    string = string.strip()
    if string.startswith("->skip"):
        return {}

    finds = cmd_docstring_regex.findall(string.split("-----")[0])
    current_key = ""
    data = {}
    if finds:
        for find in finds:
            if find[0].startswith("->"):
                current_key = find[0][2:].strip()
                continue

            if not current_key:
                continue

            # remove useless whitespace
            value = re.sub("  +", "", find[1].strip())
            data[current_key] = value
            current_key = ""

    return data


async def create_help_command_embeds(
    ctx: commands.Context[BotT],
    qualified_name: typing.Optional[str] = None,
):
    doc_fields = {}
    embeds = []

    is_admin = await ctx.bot.is_owner(ctx.author)

    if not qualified_name:
        for cmd in sorted(ctx.bot.walk_commands(), key=lambda cmd: cmd.qualified_name):
            if cmd.hidden or not is_admin and cmd.extras.get("admin_only", False):
                continue

            data = get_doc_from_func(cmd.callback)
            if not data:
                continue

            if not doc_fields.get(data["type"]):
                doc_fields[data["type"]] = ["", "", True]

            doc_fields[data["type"]][0] += f"{data['signature'][2:]}\n"
            doc_fields[data["type"]][1] += (
                f"`{data['signature']}`\n" f"{data['description']}\n\n"
            )

        doc_fields_cpy = doc_fields.copy()

        for doc_field_name in doc_fields:
            doc_field_list = doc_fields[doc_field_name]
            doc_field_list[1] = f"```\n{doc_field_list[0]}\n```\n\n{doc_field_list[1]}"
            doc_field_list[0] = f"__**{doc_field_name}**__"

        doc_fields = doc_fields_cpy

        embeds.append(
            discord.Embed(
                title="Help",
                description=BOT_HELP_DIALOG_FSTRING.format(
                    ctx.bot.user.mention,
                    ", ".join(
                        (
                            p
                            for p in (await ctx.bot.get_prefix(ctx.message))
                            if not snakecore.utils.is_markdown_mention(p)
                        )
                    ),
                ),
                color=constants.DEFAULT_EMBED_COLOR,
            )
        )
        for doc_field in list(doc_fields.values()):
            body = f"{doc_field[0]}\n\n{doc_field[1]}"
            embeds.append(
                snakecore.utils.embeds.create_embed(
                    title="Help",
                    description=body,
                    color=constants.DEFAULT_EMBED_COLOR,
                )
            )

    else:
        cmd = ctx.bot.get_command(qualified_name)
        if (
            cmd is not None
            and not cmd.hidden
            and (is_admin or cmd.extras.get("admin_only", False))
        ):
            cmds = [cmd]
            if isinstance(cmd, commands.Group):
                cmds.extend(
                    sorted(
                        (subcmd for subcmd in cmd.walk_commands()),
                        key=lambda cmd: cmd.qualified_name,
                    )
                )

            for cmd in cmds:
                doc = get_doc_from_func(cmd.callback)
                if not doc:
                    # function found, but does not have help.
                    return embeds

                body = f"`{doc['signature']}`\n`Category: {doc['type']}`\n\n"

                desc = doc["description"]

                ext_desc = doc.get("extended description")
                if ext_desc:
                    desc = f"> *{desc}*\n\n{ext_desc}"

                desc_list = desc.split(sep="+===+")

                body += f"**Description:**\n{desc_list[0]}"

                embed_fields = []

                example_cmd = doc.get("example command")
                if example_cmd:
                    embed_fields.append(
                        dict(name="Example command(s):", value=example_cmd, inline=True)
                    )

                cmd_qualified_name = cmd.qualified_name

                if len(desc_list) == 1:
                    embeds.append(
                        snakecore.utils.embeds.create_embed(
                            title=f"Help for `{cmd_qualified_name}`",
                            description=body,
                            color=constants.DEFAULT_EMBED_COLOR,
                            fields=embed_fields,
                        )
                    )
                else:
                    embeds.append(
                        snakecore.utils.embeds.create_embed(
                            title=f"Help for `{cmd_qualified_name}`",
                            description=body,
                            color=constants.DEFAULT_EMBED_COLOR,
                        )
                    )
                    desc_list_len = len(desc_list)
                    for i in range(1, desc_list_len):
                        embeds.append(
                            snakecore.utils.embeds.create_embed(
                                title=f"Help for `{cmd_qualified_name}`",
                                description=desc_list[i],
                                color=constants.DEFAULT_EMBED_COLOR,
                                fields=embed_fields if i == desc_list_len - 1 else None,
                            )
                        )

    return embeds


class CustomHelp(BaseCommandCog):
    def __init__(self, bot: BotT) -> None:
        super().__init__(bot)

    @commands.guild_only()
    @commands.command(extras=dict(invoke_on_message_edit=True))
    async def help(
        self,
        ctx: commands.Context,
        *names: str,
    ):
        """
        ->type Get help
        ->signature pg!help [command]
        ->description Ask me for help
        ->example command pg!help help
        -----
        Implement pg!help, to display a help message
        """

        # needed for typecheckers to know that ctx.author is a member
        if isinstance(ctx.author, discord.User):
            return

        qualified_name = " ".join(names)
        embeds = await create_help_command_embeds(ctx, qualified_name=qualified_name)

        if not embeds:
            if not self.bot.get_command(qualified_name):
                raise commands.CommandInvokeError(
                    Exception(f"Command `{qualified_name}` was not found.")
                )
            else:
                raise commands.CommandInvokeError(
                    Exception(
                        f"Command `{qualified_name}` does not provide any documentation."
                    )
                )

        paginator = None
        if (
            response_message := self.recent_response_messages.get(ctx.message.id)
        ) is not None:
            try:
                if (
                    paginator_list := self.recent_embed_paginators.get(
                        response_message.id
                    )
                ) is not None:
                    paginator = paginator_list[0]
                    if paginator.is_running():
                        paginator_list[1].cancel()

                paginator = snakecore.utils.pagination.EmbedPaginator(
                    (response_message := await response_message.edit(content="\u200b", embed=None)),
                    *embeds,
                    callers=ctx.author,
                    inactivity_timeout=60,
                    theme_color=constants.DEFAULT_EMBED_COLOR,
                )
            except discord.NotFound:
                paginator = snakecore.utils.pagination.EmbedPaginator(
                    (response_message := await ctx.channel.send(content="\u200b")),
                    *embeds,
                    callers=ctx.author,
                    inactivity_timeout=60,
                    theme_color=constants.DEFAULT_EMBED_COLOR,
                )
        else:
            paginator = snakecore.utils.pagination.EmbedPaginator(
                (response_message := await ctx.channel.send(content="\u200b")),
                *embeds,
                callers=ctx.author,
                inactivity_timeout=60,
                theme_color=constants.DEFAULT_EMBED_COLOR,
            )

        paginator_list = [
            paginator,
            asyncio.create_task(paginator.mainloop(client=self.bot)),
        ]

        self.recent_response_messages[ctx.message.id] = response_message

        self.recent_embed_paginators[response_message.id] = paginator_list

        await paginator_list[1]


async def setup(bot: BotT):
    await bot.add_cog(CustomHelp(bot))