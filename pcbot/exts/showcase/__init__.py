from typing import Collection
import discord
import snakecore

from .utils import ShowcaseChannelConfig

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    showcase_channels_config: Collection[ShowcaseChannelConfig],
    theme_color: int | discord.Color = 0,
):
    # validate showcase channels config
    for i, showcase_channel_config in enumerate(showcase_channels_config):
        if "channel_id" not in showcase_channel_config:
            raise ValueError("Showcase channel config must have a 'channel_id' key")
        elif (
            "default_auto_archive_duration" in showcase_channel_config
            and not isinstance(
                showcase_channel_config["default_auto_archive_duration"], int
            )
        ):
            raise ValueError(
                "Showcase channel config 'default_auto_archive_duration' must be an integer"
            )
        elif (
            "default_thread_slowmode_delay" in showcase_channel_config
            and not isinstance(
                showcase_channel_config["default_thread_slowmode_delay"], int
            )
        ):
            raise ValueError(
                "Showcase channel config 'default_thread_slowmode_delay' must be an integer"
            )
        elif "showcase_message_rules" not in showcase_channel_config:
            raise ValueError(
                "Showcase channel config must have a 'showcase_message_rules' key"
            )

        from .utils import dispatch_rule_specifier_dict_validator, BadRuleSpecifier

        specifier_dict_validator = dispatch_rule_specifier_dict_validator(
            showcase_channel_config["showcase_message_rules"]
        )

        # validate 'showcase_message_rules' value
        try:
            specifier_dict_validator(
                showcase_channel_config["showcase_message_rules"]  # type: ignore
            )
        except BadRuleSpecifier as e:
            raise ValueError(
                f"Error while parsing config.{i}.showcase_message_rules field: {e}"
            ) from e

    from .cogs import Showcasing

    await bot.add_cog(Showcasing(bot, showcase_channels_config, theme_color))
