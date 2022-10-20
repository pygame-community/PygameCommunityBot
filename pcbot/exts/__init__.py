"""This file allows the `/exts` directory to behave like a package module of bot extensions.
By defining `setup()` and `teardown()` functions that take in a `discord.ext.commands.Bot`
instance as an argument, the entire directory can be loaded as one large collection
of extensions.
"""
