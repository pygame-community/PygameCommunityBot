"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.

This file contains helper functions used by the CLI.
"""

import importlib
import importlib.util
import re
from typing import Any, overload

import click

import sqlalchemy
from sqlalchemy.engine.result import Result
from sqlalchemy.ext.asyncio import AsyncConnection

from . import utils
from .base import ExtensionManager
from .bot import (
    PygameCommunityBot as Bot,
)
from .types import DatabaseDict
from .migrations import MIGRATIONS


async def migrate(
    db: DatabaseDict,
    specifier: str,
    config: dict[str, Any],
    quiet: bool = False,
    yes: bool = False,
):
    revision_number = await utils.get_pgcbots_db_schema_revision_number(db)

    final_steps = None

    if specifier == "+":  # migrate to highest revision
        final_steps = None

    elif specifier.isnumeric():  # migrate/rollback to exact revision
        final_steps = int(specifier) - revision_number

    elif (
        specifier.startswith(
            ("+", "-")
        )  # migrate/rollback relative to current revision
        and specifier[1:].isnumeric()
    ):
        final_steps = int(specifier)

    if final_steps is None or final_steps > 0:  # migration
        if not yes:
            confirm = click.confirm(
                click.style(
                    f"A bot database migration from a revision number {revision_number} "
                    f"to a projected revision number "
                    + str(
                        revision_number + final_steps
                        if final_steps
                        else len(MIGRATIONS) - 1
                    )
                    + " is about to be performed."
                    "\nDo you wish to proceed?",
                    bold=True,
                )
            )
            if not confirm:
                raise click.Abort()

        initial_migration_count = (
            migration_count
        ) = await utils.initialize_pgcbots_db_schema(db, config)
        if initial_migration_count and final_steps is not None:
            final_steps -= initial_migration_count

        if final_steps is None or final_steps >= 1:
            migration_count += await utils.migrate_pgcbots_db_schema(
                db,
                final_steps,
            )

        if migration_count:
            if not quiet:
                click.secho(
                    "Successfully performed bot database migration "
                    + (f"from revision number {revision_number}")
                    + f" to {revision_number+migration_count}.",
                    fg="green",
                )
        else:
            if not quiet:
                click.secho(
                    "No bot database migration was performed. The highest "
                    f"available revision (Nr. {revision_number}) has already been "
                    "reached and no new migrations are pending. Enable the logger for "
                    "more information.",
                    fg="yellow",
                )

    elif final_steps == 0:
        click.secho(
            f"No bot database migration/rollback was performed, "
            "as the targeted revision number already matches the "
            f"current revision number (Nr. {revision_number}).",
            fg="yellow",
        )

    else:  # rollback
        if not yes:
            confirm = click.confirm(
                click.style(
                    f"A bot database rollback from a revision number {revision_number} "
                    f"to a projected revision number "
                    + str(
                        revision_number + final_steps
                        if final_steps
                        else len(MIGRATIONS) - 1
                    )
                    + " is about to be performed."
                    "\nDo you wish to proceed?",
                    bold=True,
                )
            )
            if not confirm:
                raise click.Abort()

        if await utils.pgcbots_db_schema_is_defined(db):
            rollback_count = await utils.rollback_pgcbots_db_schema(
                db, abs(final_steps)
            )

            if rollback_count:
                if not quiet:
                    click.secho(
                        "Successfully performed "
                        + "bot database rollback "
                        + (f"from revision number {revision_number}")
                        + f" to {revision_number-rollback_count}.",
                        fg="green",
                    )
            else:
                if not quiet:
                    click.secho(
                        "No bot "
                        "database rollback was performed, "
                        "as rollbacks beyond the initial revision (Nr. 0) "
                        "aren't possible. "
                        "Enable the logger for more information.\n",
                        fg="yellow",
                    )
        elif not quiet:
            click.secho(
                "No bot "
                "database rollback was performed. "
                "Perform an initial migration to enable rollbacks.",
                fg="yellow",
            )


@overload
async def extract_bot_extension_info(
    db: DatabaseDict,
    extensions: tuple[str, ...],
    ignore_failures: bool = False,
    quiet: bool = False,
    return_text_output: bool = False,
) -> list[str]:
    ...


@overload
async def extract_bot_extension_info(
    db: DatabaseDict,
    extensions: tuple[str, ...],
    ignore_failures: bool = False,
    quiet: bool = False,
    return_text_output: bool = False,
    return_extension_info: bool = False,
) -> list[dict[str, Any]]:
    ...


@overload
async def extract_bot_extension_info(
    db: DatabaseDict,
    extensions: tuple[str, ...],
    ignore_failures: bool = False,
    quiet: bool = False,
) -> bool:
    ...


async def extract_bot_extension_info(
    db: DatabaseDict,
    extensions: tuple[str, ...],
    ignore_failures: bool = False,
    quiet: bool = False,
    return_text_output: bool = False,
    return_extension_info: bool = False,
) -> bool | list[str] | list[dict[str, Any]]:
    engine = db["engine"]
    extension_info_row_dicts: list[dict[str, str]] = []

    filtered_extension_names = []

    for ext_name in extensions:
        if not re.match(r"[\w.]+", ext_name):
            if not quiet:
                click.secho(f"Invalid bot extension name: '{ext_name}'", fg="red")

            if ignore_failures:
                continue

            raise click.Abort()

        filtered_extension_names.append(ext_name)

    row_dicts = []

    conn: AsyncConnection
    async with engine.connect() as conn:
        if filtered_extension_names:
            result: Result = await conn.execute(
                sqlalchemy.text(
                    "SELECT name, revision_number, "
                    "auto_migrate, db_prefix FROM bot_extensions "
                    "WHERE name IN ("
                    + ", ".join(repr(ext_name) for ext_name in filtered_extension_names)
                    + ")"
                )
            )

            rows = result.all()
            if not rows:
                if not quiet:
                    click.secho(
                        "No bot extension data could be found for any of the specified "
                        f" bot extensions.",
                        fg="red",
                    )
                raise click.Abort()

            row_dict_map = {row.name: row._asdict() for row in rows}

            for ext_name in filtered_extension_names:
                row_dict = row_dict_map.get(ext_name)

                if not row_dict:
                    if not quiet:
                        click.secho(
                            f"No bot extension data could be found for '{ext_name}'.",
                            fg="red",
                        )

                    if ignore_failures:
                        continue
                    else:
                        raise click.Abort()

                row_dicts.append(row_dict)

        else:
            result: Result = await conn.execute(
                sqlalchemy.text(
                    "SELECT name, revision_number, "
                    "auto_migrate, db_prefix FROM bot_extensions"
                ),
            )

            row_dicts = [row._asdict() for row in result.all()]

        for row_dict in row_dicts:
            # get a list of dicts with the name and type of all database objects for the
            # current bot extension
            db_object_row_dicts = [
                row2._asdict()
                | dict(
                    row_count=(
                        await conn.execute(
                            sqlalchemy.text(f"SELECT COUNT(*) FROM {row2.name}"),
                        )
                    ).scalar()
                    if not row2.name.startswith(
                        "sqlite" if engine.name == "sqlite" else "pg_"
                    )
                    else None
                )
                for row2 in (
                    (
                        await conn.execute(
                            sqlalchemy.text(
                                "SELECT name, type FROM sqlite_schema "
                                "WHERE tbl_name LIKE :prefix || '%' AND tbl_name NOT LIKE 'sqlite%'"
                                "ORDER BY type ASC, name ASC"
                                if engine.name == "sqlite"
                                else "SELECT table_name AS name, table_type AS type "
                                "FROM information_schema.tables "
                                "WHERE name LIKE :prefix || '%' "
                                "ORDER BY type ASC, name ASC"
                            ),
                            dict(prefix=row_dict["db_prefix"]),
                        )
                    ).all()
                    if engine.name == "sqlite"
                    else (
                        *(
                            await conn.execute(
                                sqlalchemy.text(
                                    "SELECT table_name AS name, table_type AS type "
                                    "FROM information_schema.tables "
                                    "WHERE name LIKE :prefix || '%' "
                                    "ORDER BY type ASC, name ASC"
                                ),
                                dict(prefix=row_dict["db_prefix"]),
                            )
                        ).all(),
                        *(
                            await conn.execute(
                                sqlalchemy.text(
                                    "SELECT indexname AS name, 'INDEX' AS type FROM pg_indexes "
                                    "WHERE tablename LIKE :prefix || '%' "
                                    "ORDER BY type ASC, name ASC"
                                ),
                                dict(prefix=row_dict["db_prefix"]),
                            )
                        ).all(),
                    )
                )
            ]

            row_dict["db_objects_print_str"] = ""
            for (
                row_dict2
            ) in (
                db_object_row_dicts
            ):  # generate textual list of database objects for an extension
                row_dict["db_objects_print_str"] += (
                    f"  + [{row_dict2['type'].upper()}] "  # type: ignore
                    + (
                        f"({row_dict2['row_count']} row(s))"
                        if row_dict2["row_count"] is not None
                        else "(N/A row(s))"
                    )
                    + f" {row_dict2['name']}\n"
                )

                row_dict2["queryable"] = row_dict2["row_count"] is not None

            row_dict["db_objects_print_str"].removesuffix("\n")
            row_dict["db_objects"] = db_object_row_dicts

            extension_info_row_dicts.append(row_dict)

    if not extension_info_row_dicts:
        click.secho(f"No bot extension data could be found.", fg="red")
        raise click.Abort()

    if not quiet:
        click.secho(
            f"\n{len(extension_info_row_dicts)} extension data entries found.\n",
            fg="yellow",
        )

    extension_info_texts = []

    for i in range((info_len := len(extension_info_row_dicts))):
        row_dict = extension_info_row_dicts[i]
        extension_info_text = (
            f"{click.style(row_dict['name'], bold=True, underline=True)}\n"
            f"- Revision Number:       {row_dict['revision_number']}\n"
            f"- Auto Migrate:          {bool(row_dict['auto_migrate'])}\n"
            f"- Database Prefix:       {row_dict.get('db_prefix')}\n"
            f"- Database Objects:\n{row_dict.get('db_objects_print_str')}"
        ) + ("\n" if i < info_len - 1 else "")

        if not (return_text_output or return_extension_info):
            click.echo(extension_info_text)

        extension_info_texts.append(extension_info_text)

    return (
        extension_info_texts
        if return_text_output
        else extension_info_row_dicts
        if return_extension_info
        else True
    )


async def delete_bot_extensions(
    db: DatabaseDict,
    extensions: tuple[str, ...] = (),
    bots: tuple[str, ...] = (),
    all_extensions: bool = False,
    ignore_failures: bool = False,
    quiet: bool = False,
    yes: bool = False,
) -> int:
    engine = db["engine"]
    extname_row_map: dict[str, dict[str, str]] = {}

    deletions = 0

    conn: AsyncConnection
    async with engine.connect() as conn:
        if all_extensions:
            result: Result = await conn.execute(
                sqlalchemy.text(
                    "SELECT name, revision_number, "
                    "auto_migrate, db_prefix FROM bot_extensions"
                ),
            )
            for row in result.all():
                row_dict = row._asdict()
                extname_row_map[row_dict["name"]] = row_dict

        elif extensions:
            for ext_name in set(extensions):
                result: Result = await conn.execute(
                    sqlalchemy.text(
                        "SELECT name, revision_number, "
                        "auto_migrate, db_prefix FROM bot_extensions "
                        "WHERE name == :name"
                    ),
                    dict(name=ext_name),
                )

                row = result.one_or_none()
                if not row:
                    if not quiet:
                        click.secho(
                            "No bot extension data could be found for an extension "
                            f"named '{ext_name}'",
                            fg="red",
                        )
                    if ignore_failures:
                        continue

                    return deletions

                row_dict = row._asdict()
                extname_row_map[ext_name] = row_dict

        else:
            if not quiet:
                click.secho(f"No bot extension data could be found.", fg="red")

            return deletions

    if not extname_row_map:
        if not quiet:
            click.secho(f"No bot extension data could be found.", fg="red")
        return deletions

    if not quiet:
        click.secho(
            f"\n{len(extname_row_map)} extension data entries found.\n", fg="yellow"
        )

    deletions = 0
    conn: AsyncConnection
    async with engine.begin() as conn:
        for row_dict in extname_row_map.values():
            if bots:
                db_prefix = row_dict["db_prefix"]
                for bot_uid in bots:
                    if (
                        await conn.execute(
                            sqlalchemy.text(
                                "SELECT EXISTS(SELECT 1 FROM sqlite_schema "
                                "WHERE type == 'table' "
                                f"AND name == '{db_prefix}bots')"
                                if engine.name == "sqlite"
                                else "SELECT EXISTS(SELECT 1 FROM "
                                "information_schema.tables "
                                f"WHERE table_name == '{db_prefix}bots')"
                            )
                        )
                    ).scalar():
                        if (
                            await conn.execute(
                                sqlalchemy.text(
                                    "SELECT EXISTS(SELECT 1 FROM "
                                    f"'{db_prefix}bots' WHERE uid == :uid)"
                                ),
                                dict(uid=bot_uid),
                            )
                        ).scalar():
                            if not yes:
                                confirm = click.confirm(
                                    click.style(
                                        "All extension-specific data "
                                        f"for bot with uid '{bot_uid}' in the data of "
                                        f"'{row_dict['name']}' is about to be deleted."
                                        "\nAre you sure you wish to proceed?",
                                        fg="yellow",
                                        bold=True,
                                    )
                                )
                                if not confirm:
                                    continue
                            result = await conn.execute(
                                sqlalchemy.text(
                                    f"DELETE FROM '{db_prefix}bots' WHERE uid == :uid"
                                ),
                                dict(uid=bot_uid),
                            )

                            if result.rowcount:
                                if not quiet:
                                    click.secho(
                                        "Successfully deleted all extension-specific data "
                                        f"for bot with uid '{bot_uid}' in the data of "
                                        f"'{row_dict['name']}'.",
                                        fg="green",
                                    )
                                deletions += 1

                            else:
                                if not quiet:
                                    click.secho(
                                        "No extension-specific data for bot with uid "
                                        f"'{bot_uid}' was found in the data of "
                                        f"'{row_dict['name']}'.",
                                        fg="yellow",
                                    )
                        else:
                            click.secho(
                                f"Bot extension '{row_dict['name']}' does not define "
                                f"extension-specific data for a bot with uid '{bot_uid}'.",
                                fg="yellow",
                            )
                    else:
                        click.secho(
                            f"Bot extension '{row_dict['name']}' does not define "
                            "extension-specific data for any bots.",
                            fg="yellow",
                        )

            else:
                extinfo_dict = (
                    await extract_bot_extension_info(
                        db, (row_dict["name"],), quiet=True, return_extension_info=True
                    )
                )[0]

                if not (quiet and yes):
                    click.echo(
                        "Preparing to delete extension data for extension:\n\n"
                        f"{click.style(row_dict['name'], bold=True, underline=True)}\n"
                        f"- Revision Number:       {extinfo_dict['revision_number']}\n"
                        f"- Auto Migrate:          {bool(extinfo_dict['auto_migrate'])}\n"
                        f"- Database Prefix:       {extinfo_dict.get('db_prefix')}\n"
                        f"- Database Objects:\n{extinfo_dict.get('db_objects_print_str')}\n"
                    )
                if not yes:
                    confirm = click.confirm(
                        click.style(
                            "This entry and all data associated with it will be deleted."
                            "\nAre you sure you wish to proceed?",
                            fg="yellow",
                            bold=True,
                        )
                    )
                    if not confirm:
                        continue

                if engine.name == "sqlite":
                    result: Result = await conn.execute(
                        sqlalchemy.text(
                            "SELECT name FROM sqlite_schema "
                            f"WHERE type == 'table' AND name LIKE :db_prefix || '%'"
                        ),
                        dict(db_prefix=row_dict["db_prefix"]),
                    )

                for db_object in extinfo_dict["db_objects"]:
                    # detect correct specifier for types across
                    # sqlite and postgresql
                    drop_specifier = (
                        "TABLE"
                        if any(
                            substr in db_object["type"]
                            for substr in ("TABLE", "TEMPORARY")
                        )
                        else db_object["type"].upper()
                    )

                    if db_object["queryable"]:
                        await conn.execute(
                            sqlalchemy.text(f"DELETE FROM '{db_object['name']}'")
                        )
                        await conn.execute(
                            sqlalchemy.text(
                                f"DROP {drop_specifier} '{db_object['name']}'"
                            )
                        )

                await conn.execute(
                    sqlalchemy.text(
                        "DELETE FROM bot_extensions as be WHERE be.name == :extension"
                    ),
                    dict(extension=row_dict["name"]),
                )

                if not quiet:
                    click.secho(
                        f"Successfully deleted all stored data of extension {row_dict['name']}",
                        fg="green",
                    )

                deletions += 1

    if not (deletions or quiet):
        click.secho(f"No bot extension data was deleted.", fg="yellow")

    return deletions


async def migrate_bot_extensions(
    bot: Bot,
    options: tuple[tuple[str, str], ...],
    ignore_failures: bool = False,
    quiet: bool = False,
    yes: bool = False,
) -> int:
    successes = 0

    for extension_name, specifier in options:
        try:
            extension_module = importlib.import_module(extension_name)
        except ModuleNotFoundError:
            if not quiet:
                click.secho(
                    "Could not migrate/rollback database objects of bot extension "
                    f"'{extension_name}': Module not found.",
                    fg="red",
                )
            if ignore_failures:
                continue
            return successes

        extension_manager: ExtensionManager | None = getattr(
            extension_module, "extension_manager", None
        )
        if not isinstance(extension_manager, ExtensionManager):
            if not quiet:
                click.secho(
                    "Could not migrate/rollback database objects of bot extension "
                    f"'{extension_name}': No extension manager object "
                    "found.",
                    fg="red",
                )

            if ignore_failures:
                continue
            return successes

        extension_data_existed = await bot.extension_data_exists(extension_name)

        if extension_data_existed:
            revision_number = (
                await bot.read_extension_data(extension_name, data=False)
            )["revision_number"]
        else:
            revision_number = -1

        final_steps = None

        if specifier == "+":  # migrate to highest revision
            final_steps = None

        elif specifier.isnumeric():  # migrate/rollback to exact revision
            final_steps = int(specifier) - revision_number

        elif (
            specifier.startswith(
                ("+", "-")
            )  # migrate/rollback relative to current revision
            and specifier[1:].isnumeric()
        ):
            final_steps = int(specifier)

        if final_steps is None or final_steps > 0:  # migration
            if not yes:
                confirm = click.confirm(
                    click.style(
                        "\nA bot extension database object migration for "
                        f"'{extension_name}' from a revision number {revision_number} "
                        f"to a projected revision number "
                        + str(
                            revision_number + final_steps
                            if final_steps
                            else len(extension_manager.migrations) - 1
                        )
                        + " is about to be performed."
                        "\nDo you wish to proceed?",
                        bold=True,
                    )
                )
                if not confirm:
                    continue

            initial_migration_count = migration_count = await extension_manager.prepare(
                bot, initial_migration_steps=1
            )
            if initial_migration_count and final_steps is not None:
                final_steps -= initial_migration_count

            if final_steps is None or final_steps >= 1:
                migration_count += await extension_manager.migrate(
                    bot,
                    final_steps,
                )

            if migration_count:
                if not quiet:
                    click.secho(
                        "Successfully performed bot extension database object "
                        f"migration for '{extension_name}' "
                        + (f"from revision number {revision_number}")
                        + f" to {revision_number+migration_count}.",
                        fg="green",
                    )
                successes += 1
            else:
                if not quiet:
                    click.secho(
                        "No bot extension database object migration was performed for "
                        f"'{extension_name}'. The highest available "
                        f"revision (Nr. {revision_number}) has already been reached "
                        "and no new migrations are pending. Enable the logger for "
                        "more information.",
                        fg="yellow",
                    )

        elif final_steps == 0:
            click.secho(
                f"No bot extension database object migration/rollback was performed "
                f"for '{extension_name}'. "
                "The targeted revision number already matches the "
                f"current revision number (Nr. {revision_number}).",
                fg="yellow",
            )

        else:  # rollback
            if not yes:
                confirm = click.confirm(
                    click.style(
                        "\nA bot extension database object rollback for "
                        f"'{extension_name}' from a revision "
                        f"number {revision_number} to a projected revision number "
                        + str(
                            revision_number + final_steps
                            if final_steps
                            else len(MIGRATIONS) - 1
                        )
                        + f" is about to be performed for '{extension_name}'."
                        "\nDo you wish to proceed?",
                        bold=True,
                    )
                )
                if not confirm:
                    continue

            if extension_data_existed:
                rollback_count = await extension_manager.rollback(bot, abs(final_steps))

                if rollback_count:
                    if not quiet:
                        click.secho(
                            "Successfully performed "
                            + "bot extension database object rollback "
                            f"for '{extension_name}', "
                            + (f"from revision number {revision_number}")
                            + f" to {revision_number-rollback_count}.",
                            fg="green",
                        )
                    successes += 1
                else:
                    if not quiet:
                        click.secho(
                            f"No bot "
                            "extension database object rollback was performed "
                            f"for '{extension_name}',"
                            "as rollbacks beyond the initial revision (Nr. 0) "
                            "aren't possible. "
                            "Enable the logger for more information.\n",
                            fg="yellow",
                        )

            elif not quiet:
                click.secho(
                    "No bot "
                    "extension database object rollback was performed "
                    f"for '{extension_name}'. "
                    "Perform an initial bot extension database object "
                    "migration to enable rollbacks.",
                    fg="yellow",
                )

    return successes
