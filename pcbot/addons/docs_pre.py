"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.

This file defines some functions to access docs of any module/class/function
"""

import asyncio
import builtins
import cmath
import collections
import gc
import itertools
import json
import math
import os
import pickle
import random
import re
import socket
import sqlite3
import string
import sys
import threading
import time
import timeit
import types

import discord
from discord.ext import commands
import numpy
import pkg_resources
import pygame
import pygame._sdl2
import pygame.gfxdraw
import pygame_gui
import snakecore

doc_module_tuple = (
    asyncio,
    builtins,
    cmath,
    collections,
    discord,
    gc,
    itertools,
    json,
    math,
    numpy,
    os,
    pickle,
    pygame,
    pygame_gui,
    random,
    re,
    socket,
    sqlite3,
    string,
    sys,
    threading,
    time,
    timeit,
)
doc_module_dict = {}

for module_obj in doc_module_tuple:
    doc_module_dict[module_obj.__name__] = module_obj

for module in sys.modules:
    doc_module_dict[module] = sys.modules[module]


for module in pkg_resources.working_set:  # pylint: disable=not-an-iterable
    try:
        doc_module_dict[module] = __import__(module.project_name.replace("-", "_"))
    except BaseException:
        pass

import random
import discord
from discord.ext import commands
import snakecore

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot

DOC_EMBED_LIMIT = 3


class DocsPreCog(BaseExtensionCog, name="docs-pre"):
    async def put_main_doc(self, ctx: commands.Context[BotT], name: str):
        """
        Put main part of the doc into embed(s)
        """
        splits = name.split(".")

        try:
            is_builtin = bool(getattr(builtins, splits[0]))
        except AttributeError:
            is_builtin = False

        if splits[0] not in doc_module_dict and not is_builtin:
            await self.send_or_edit_response(
                ctx,
                embed=discord.Embed(
                    title="Unknown module!",
                    description="No such module was found.",
                    color=int(self.theme_color),
                ),
            )
            return None, None

        module_objs = dict(doc_module_dict)
        obj = None

        for part in splits:
            try:
                try:
                    obj = getattr(builtins, part)
                except AttributeError:
                    obj = module_objs[part]

                module_objs = {}
                for i in dir(obj):
                    if i != "__abstractmethods__":
                        module_objs[i] = getattr(obj, i)
            except KeyError:
                await self.send_or_edit_response(
                    ctx,
                    embed=discord.Embed(
                        title="Class/function/sub-module not found!",
                        description=f"There's no such thing here named `{name}`",
                    ),
                )
                return None, None

        if isinstance(obj, (int, float, str, dict, list, tuple, bool)):
            await self.send_or_edit_response(
                ctx,
                embed=discord.Embed(
                    title=f"Documentation for `{name}`",
                    description=f"{name} is a constant with a type of "
                    f"`{obj.__class__.__name__}` which does not have documentation.",
                ),
            )
            return None, None

        header = ""
        if splits[0] == "pygame":
            doclink = "https://pyga.me/docs"
            if len(splits) > 1:
                doclink += "/ref/" + splits[1].lower() + ".html"
                doclink += "#"
                doclink += "".join([s + "." for s in splits])[:-1]
            header = "Online documentation: " + doclink + "\n"

        docs = "" if obj.__doc__ is None else obj.__doc__

        embeds = []
        lastchar = 0
        count = 0
        while len(docs) >= lastchar:
            count += 1
            if count >= DOC_EMBED_LIMIT:
                text = docs[lastchar:]
            else:
                text = docs[lastchar : lastchar + 2040]

                # Try to split docs into paragraphs. If that does not work, split
                # based on sentences. If that too does not work, then just split
                # blindly
                ind = text.rfind("\n\n")
                if ind > 1500:
                    lastchar += ind
                    text = text[:lastchar]
                else:
                    ind = text.rfind("\n")
                    if ind > 1500:
                        lastchar += ind
                        text = text[:lastchar]
                    else:
                        lastchar += 2040

            if text:
                embeds.append(
                    discord.Embed(
                        title=f"Documentation for `{name}`",
                        description=header + snakecore.utils.code_block(text),
                        color=int(self.theme_color),
                    )
                )

            header = ""
            if count >= DOC_EMBED_LIMIT:
                break

        if not embeds:
            await self.send_or_edit_response(
                ctx,
                embed=discord.Embed(
                    title="Class/function/sub-module not found!",
                    description=f"There's no such thing here named `{name}`",
                ),
            )
            return None, None

        return module_objs, embeds

    async def put_doc(
        self,
        ctx: commands.Context[BotT],
        name: str,
        msg_invoker: discord.Member,
    ):
        """
        Helper function to get docs
        """
        module_objs, main_embeds = await self.put_main_doc(ctx, name)
        if module_objs is None or main_embeds is None:
            return

        allowed_obj_names = {
            "Modules": [],
            "Types": [],
            "Functions": [],
            "Methods": [],
        }

        formatted_obj_names = {
            "module": "Modules",
            "type": "Types",
            "function": "Functions",
            "method_descriptor": "Methods",
        }

        for oname, modmember in module_objs.items():
            if type(modmember).__name__ == "builtin_function_or_method":
                # Disambiguate into function or method
                obj_type_name = None
                if isinstance(modmember, types.BuiltinFunctionType):
                    obj_type_name = "Functions"
                elif isinstance(modmember, types.BuiltinMethodType):
                    obj_type_name = "Methods"
            else:
                obj_type_name = formatted_obj_names.get(type(modmember).__name__)

            if oname.startswith("__") or obj_type_name is None:
                continue

            allowed_obj_names[obj_type_name].append(oname)

        embeds = []

        for otype, olist in allowed_obj_names.items():
            if not olist:
                continue

            embeds.append(
                discord.Embed(
                    title=f"{otype} in `{name}`",
                    description=snakecore.utils.code_block("\n".join(olist)),
                    color=int(self.theme_color),
                )
            )

        main_embeds.extend(embeds)

        members = [msg_invoker]
        if (
            ctx.message.reference and ctx.message.reference.message_id
        ):  # allow reference author to also control EmbedPaginator
            try:
                reference_msg_author = (
                    ctx.message.reference.cached_message
                    or (
                        await ctx.channel.fetch_message(
                            ctx.message.reference.message_id
                        )
                    )
                ).author
            except discord.NotFound:
                pass
            else:
                if isinstance(reference_msg_author, discord.Member):
                    members.append(reference_msg_author)

        await self.send_paginated_response_embeds(ctx, *main_embeds, member=members)

    @commands.guild_only()
    @commands.command(
        extras=dict(invoke_on_message_edit=True, response_deletion_with_reaction=True)
    )
    async def doc(self, ctx: commands.Context[BotT], name: str):
        """Retrieve structural and docstring documentation of a speficied Python module, class, method or function by its qualified name.


        __**Parameters:**__

        **`<name>`**
        > The qualified name.
        """
        assert isinstance(ctx.author, discord.Member)
        await self.put_doc(ctx, name, ctx.author)


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT, color: int | discord.Color = 0):
    await bot.add_cog(DocsPreCog(bot, theme_color=color))
