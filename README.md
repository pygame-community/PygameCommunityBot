# Pygame Community Bot
The primary Discord bot powering the Pygame Community Discord server. 

## Setup
0. Install Python 3.10+.
1. Set up a virtual environment using your desired tool (e.g. `virtualenv`, `venv`, etc.).
2. Install requirements: `python -m pip install -U -r requirements.txt [-r requirements-dev.txt]`.
3. Create all necessary [configuration](#configuration) files.
4. Launch the application via the [CLI](#cli) using `python -m pcbot` with any needed extra CLI options.

## Configuration
A file called `config.py` should be used to provide information required for the bot to run. This file is meant to be stored locally on host machines without being 'added' to a Git repository. However, this suggestion may be ignored for workflows that don't permit it, and in such cases the files should be removed from the [`.gitignore`](./.gitignore) file. These files can either be stored in the top level directory or somewhere else if custom paths are passed to the CLI.

For easier overriding of configuration data or local development or testing, a `localconfig.py` file can be created to apply local overrides to the data in `config.py`.


### `config.py`
This file is meant to hold all essential configuration settings of the bot application, such as credentials and API endpoints. Creating this file is mandatory if `localconfig.py` doesn't exist, all data must be stored within a dictionary called `config`, meaning that it would be accessible as `config.config`. `"token"` within `"authentication"` is mandatory, but `"authentication"` can be expanded as needed to hold more related data. If using hosting solutions based on ephemeral file systems, credentials stored within the `"authentication"` dictionary like `"token"` can be turned into uppercase environment variables prefixed with `AUTH_` (e.g. `AUTH_TOKEN`) instead. As this file is a Python file, those credentials can be loaded into the `config` dictionary during startup via `os.environ`.

For the dictionaries within the `"extensions"` list, the `"name"` and `"package"` keys match the names of the `name` and `package` arguments in the [`discord.ext.commands.Bot.load_extension`](https://discordpy.readthedocs.io/en/latest/ext/commands/api.html#discord.ext.commands.Bot.load_extension) method and the values are meant to be forwarded to it, during startup. The `"config"` key (not to be confused with the `config` dictionary or `config.py`) inside an extension dictionary (only supported with `snakecore`) can be used as a way to provide keyword arguments to extensions while they load, if supported.

The resulting `config` dictionary will be passed to the bot constructor and will remain accessable in a read-only state as a `.config` attribute.

#### Example code for `config.py`
```py
config = {
    "authentication": {
        "token": "RVfpk43ojf...",
        # more custom stuff
    },
    "manager_role_ids": [111222333444555667, 888999000111222334], # bot managers (e.g. the Wizard role on the Discord server)
    "intents": 0b1100011111111011111101, # https://discord.com/developers/docs/topics/gateway#list-of-intents
    "extensions": [
        {
        "name": "pcbot.exts.bundled_extension",
        "config": {
            "a": 1,
            "b": 2
        }
    }],
}
```

### `localconfig.py`
This file is meant to override any data specified in the `config` dictionary inside `config.py`, in order to e.g. locally customize the launching/startup process of the bot application using custom/extra configuration settings. Creating this file is optional. All data must be stored within a dictionary called `config`, meaning that it would be accessible as `localconfig.config`.

To override variables as if they were omitted, define them with a value of `...` (`Ellipsis` object in Python).

#### Example code for `localconfig.py` 
```py
from typing import Any

from pcbot._types import Config # helper TypedDict for configuration data type checking, can be subclassed to define new variables, or omitted completely

OMIT: Any = Ellipsis # helper constant
config: Config = {
    "command_prefix": "!",  # can also be a list of prefixes
    "mention_as_command_prefix": True, # whether mentions may count as command prefixes
    "log_level": "INFO", # omission disables logging entirely
    "owner_ids" : [420420420420420420, 696969696969696969],
    "owner_role_ids": [123456789101213151, 987654321987654321], # used to implement role-based dynamic owners
    "manager_role_ids": OMIT, # will override and delete variable
    "extensions": [
        {
            "name": "pcbot.exts.bundled_extension2",
            "config": {
                "a": 1,
                "b": 2
            }
        },
        # comment out extensions to disable them or use the `--ignore-extension ext_name` option via the CLI.
        # {
        #     "name": ".exts.bundled_extension3",
        #     "package": "pcbot"
        # },
        {
            "name": "global_extension" # globally installed Python packages can be loaded as extensions
        }
    ],
    "databases": [
        {
            "name": "a_database",
            "url": "sqlite+aiosqlite:///path/to/a_database.db",
            "connect_args": {},  # arguments to pass to aiosqlite.connect() from sqlalchemy
        },
        # other secondary databases would go here
    ],
    "main_database_name": "a_database", # a way to select the main database by name
}
```

## CLI
The CLI is used to launch the bot application, whilst also allowing for selective overriding of the `config` dictionary specified inside `config.py` or `localconfig.py` using command line options. Subcommands like `extdata` allow for viewing the extensions which are currently occupying database storage, as well as deleting their data.

```
Usage: python -m pcbot [OPTIONS] COMMAND [ARGS]...

  Launch this Discord bot application.

Options:
  --config PATH                   A path to the 'config.py' file to use for
                                  configuration. credentials and launching.
                                  Failure will occur silently for an
                                  invalid/non-existing path.  [default:
                                  ./config.py]
  --localconfig PATH              A path to the optional 'localconfig.py' file
                                  to use for locally overriding 'config.py'.
                                  Failure will occur silently if this file
                                  could cannot be found/read successfully,
                                  except when 'config.py' is not provided, in
                                  which case an error will occur. HINT:
                                  Setting variables to '...' (Ellipsis) in
                                  'localconfig.py' will treat them as if they
                                  were omitted.  [default: ./localconfig.py]
  --intents TEXT                  The integer of bot intents as bitwise flags
                                  to be used by the bot instead of
                                  discord.py's defaults
                                  (0b1100010111111011111101). It can be
                                  specified as a base 2, 8, 10 or 16 integer
                                  literal. Note that the message content
                                  intent (1 << 15) flag is not set by default.
                                  See more at https://discord.com/developers/d
                                  ocs/topics/gateway#list-of-intents
  --command-prefix TEXT           The command prefix(es) to use. By default, !
                                  is used as a prefix.
  --mention-as-command-prefix     Enable the usage of bot mentions as a
                                  prefix.
  --ignore-ext, --ignore-extension TEXT
                                  The qualified name(s) of the extension(s) to
                                  ignore when loading extensions during
                                  startup.
  --ignore-all-extensions         Ignore all extensions at startup.
  --ignore-default-extensions     Ignore default extensions at startup.
  --ignore-extra-extensions       Ignore extra (non-default) extensions at
                                  startup.
  --log-level, --bot-log-level [NOTSET|DEBUG|INFO|WARNING|WARN|ERROR|FATAL|CRITICAL]
                                  The log level to use for the bot's default
                                  logging system.
  -quiet                          Supress informational (non-error) output.
  -h, --help                      Show this message and exit.

Commands:
  extdata  Show info about all/specific bot extensions with data stored.
```
