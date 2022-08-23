"""This file should define the `discord.ext.commands.Bot` subclass to use for the project. 
"""

import asyncio
import logging

from discord.ext import commands
import snakecore  # TODO: Remove this if not using snakecore


_logger = logging.getLogger(__name__)

# TODO: Rename TemplateBot according to your bot application.
# TODO: Replace snakecore.commands.Bot with `commands.Bot` if snakecore should not be used.
class TemplateBot(snakecore.commands.Bot):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.bot_config: dict = {}
        self.launch_config: dict = {}

    async def setup_hook(self) -> None:
        setattr(self, "setup_hook_task", asyncio.create_task(self._setup_hook()))
        getattr(self, "setup_hook_task").add_done_callback(
            lambda fut: delattr(self, "setup_hook_task")
        )

    async def _setup_hook(self) -> None:
        """Helper method to circumvent potential deadlocks whilst awaiting
        ``wait_until_ready()``.
        """
        await self.wait_until_ready()
        for ext_dict in self.launch_config["extensions"]:
            try:
                await self.load_extension(
                    ext_dict["name"],
                    package=ext_dict.get("package"),
                    variables=ext_dict.get("variables"),
                    # TODO: Remove the line above if not using snakecore
                )
            except (TypeError, commands.ExtensionFailed) as exc:
                _logger.error(
                    f"Failed to load extension '{ext_dict.get('package', '')}{ext_dict['name']}' at launch",
                    exc_info=exc,
                )
            else:
                _logger.info(
                    f"Successfully loaded extension '{ext_dict.get('package', '')}{ext_dict['name']}' at launch"
                )
