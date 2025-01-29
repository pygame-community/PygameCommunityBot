"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import re
import time


DB_PREFIX = f"{'hfs_pre'}__"
DB_SCHEMA_VERSION_NUMBER = 1

CAUTION_WHILE_MESSAGING_COOLDOWN: int = 900
THREAD_TITLE_TOO_SHORT_SLOWMODE_DELAY: int = 300
THREAD_DELETION_MESSAGE_THRESHOLD: int = 15
THREAD_TITLE_MINIMUM_LENGTH: int = 16
FORUM_THREAD_TAG_LIMIT = 5

HELPFULIE_ROLE_ID = 778205389942030377

HELP_FORUM_CHANNEL_IDS = {
    "newbies": 1022292223708110929,  # newbies-help-🔰
    "regulars": 1019741232810954842,  # regulars-pygame-help
    "python": 1022244052088934461,  # python-help
}

INVALID_HELP_THREAD_TYPES = {
    "thread_title_too_short",
    "member_asking_for_help",
    # "member_exclaiming_about_not_working_code",
    "member_asking_for_code",
    "member_asking_about_problem_with_code",
    "wrong_thread_help_topic_pygame",
}

INVALID_HELP_THREAD_SCANNING_ENABLED = {
    "thread_title_too_short": True,
    "member_asking_for_help": True,
    # "member_exclaiming_about_not_working_code": True,
    "member_asking_for_code": True,
    "member_asking_about_problem_with_code": True,
    "wrong_thread_help_topic_pygame": True,
}
INVALID_HELP_THREAD_REGEX_PATTERNS = {
    "thread_title_too_short": {
        "mode": "all",
        "fields": {
            "title": re.compile(
                r"^(.){1," f"{THREAD_TITLE_MINIMUM_LENGTH-1}" r"}$", flags=re.IGNORECASE
            ),
            "content": re.compile(r".*", flags=re.IGNORECASE),
        },
    },
    "member_asking_for_help": {
        "mode": "all",
        "fields": {
            "title": re.compile(
                r"[\s]*(^help\s*|help\?*?$|(can|does|is\s+)?(pl(ease|s)|(some|any)(one|body)|you|(need|want)|(can|(want|available|around|willing|ready)(\s*to)))\s*help)(?!(s|ed|er|ing))(\s*me(\s*please)?|pl(ease|s)|with)?\s*",
            ),
            "content": re.compile(r".*", flags=re.IGNORECASE),
        },
    },
    # "member_exclaiming_about_not_working_code": {
    #     "mode": "all",
    #     "fields": {
    #         "title": re.compile(
    #             r"[\s]*(why\s+)?((is|does|(sh|w)ould)(\s+not|n't)?)?\s*(my|the|this|it)?(?<=s|t|e|y|d)\s*(it|this|code|game|pygame(\s*(game|program|code|project|assignment)?))\s*(((is|does)(\s*not|n't)?|not)?\s*(work|runn?|start|break|load)(s|ed|ing)?)",
    #         ),
    #         "content": re.compile(r".*", flags=re.IGNORECASE),
    #     },
    # },
    "member_asking_for_code": {
        "mode": "all",
        "fields": {
            "title": re.compile(
                r"(?<!How\s)(?<!How\sdo\s)(?<!How\sdoes\s)(?<!I\s)((can('t|not)?|will)\s+)?(?<!How\scan\s)(please|pls|(some|any)(one|body)|(available|around|willing|ready|want)(\s*to))(\s*help(\s*me)?)?\s*(write|make|create|code|program|fix|correct|implement)(?!ing|ed)(\s*(a|my|the|this))?\s*(this|code|game|pygame(\s*(game|program|code)?))?\s*(for)?\s*(me(\s*please)?|please)?\s*",
                re.IGNORECASE,
            ),
            "content": re.compile(r".*", flags=re.IGNORECASE),
        },
    },
    "member_asking_about_problem_with_code": {
        "mode": "all",
        "fields": {
            "title": re.compile(
                r"[\s]*((why|what('s)?\s+)(is('nt)?|does(\s+not|'nt)|am\s*i\s*(doing|having))?\s*((wrong|the\s*(problem|issue))?\s*(with(in)?|in(side)?)\s*)?(my|the|this)?)\s*(this|code|game|pygame(\s*(game|program|code)?))\s*",
                re.IGNORECASE,
            ),
            "content": re.compile(r".*", flags=re.IGNORECASE),
        },
    },
    "wrong_thread_help_topic_pygame": {
        "mode": "any",
        "fields": {
            "title": re.compile(
                r"p[yi]g?(am?e|im|ae?y?me?)(\(?-?ce\)?)?|game|player|collision|tile(map)?|tilemap|sprite|render|surface|blit|rect|draw|render|display|screen|window|texture|event",
                re.IGNORECASE,
            ),
            "content": re.compile(
                r"p[yi]g?(am?e|im|ae?y?me?)(\(?-?ce\)?)?|game|player|collision|tile(map)?|tilemap|sprite|render|surface|blit|rect|draw|render|display|screen|window|texture|event",
                flags=re.IGNORECASE,
            ),
        },
    },
}
INVALID_HELP_THREAD_EMBEDS = {
    "thread_title_too_short": {
        "title": "Whoops, your post title must be at least "
        f"{THREAD_TITLE_MINIMUM_LENGTH} characters long (excluding numbers)",
        "description": "### Did you read our 👉 "
        "[Post & Question Guide](https://discord.com/channels/772505616680878080/1093999727667855380/1094000466712604681)? 👈\n\n"
        "Your post title must be at least "
        " "
        f"**{THREAD_TITLE_MINIMUM_LENGTH}** characters long, so I'm "
        "forced to put a slowmode delay of "
        f"{THREAD_TITLE_TOO_SHORT_SLOWMODE_DELAY//60} minute{'s'*(THREAD_TITLE_TOO_SHORT_SLOWMODE_DELAY > 60)} "
        " on your post (sorry) <:pg_sad:863165920038223912>.\n\n"
        "**Changing post titles:**\n"
        "> 1. Right-click post (desktop/web) or click & hold (mobile)\n"
        "> 2. Click **'Edit Post'** to see the post settings. Make your title changes there.\n"
        "> 3. Ensure your changes are saved.\n\n"
        "**Thank you for helping us maintain clean help forum channels "
        "<:pg_robot:837389387024957440>**\n\n"
        "This alert and the slowmode should disappear after you've made appropriate changes.",
        "color": 0x36393F,
    },
    "member_asking_for_help": {
        "title": "Please don't ask for help in your post title (no need to). "
        "We'd love to help you either way!",
        "description": "### Did you read our 👉 "
        "[Post & Question Guide](https://discord.com/channels/772505616680878080/1093999727667855380/1094000466712604681)? 👈\n\n"
        "We already know you need help. "
        "Please write a post title and text that describes your actual "
        "issue in more detail.\n"
        "Also send code snippets (no code screenshots), screenshots and "
        "other media, error messages, etc.\n\n"
        "**[Here's why!](https://www.dontasktoask.com)**\n\n"
        "**Changing post titles:**\n"
        "> 1. Right-click post (desktop/web) or click & hold (mobile)\n"
        "> 2. Click **'Edit Post'** to see the post settings, and make title changes.\n"
        "> 3. Ensure your changes are saved.\n\n"
        "This alert should disappear after you've made appropriate changes.",
        "color": 0x36393F,
    },
    "member_exclaiming_about_not_working_code": {
        "title": "Something doesn't work? Please tell us what.",
        "description": "### Did you read our 👉 "
        "[Post & Question Guide](https://discord.com/channels/772505616680878080/1093999727667855380/1094000466712604681)? 👈\n\n"
        "Edit your help post title and text "
        "to describe the problem that led to that diagnosis. What made your code "
        "stop working? What are you trying to do?\n"
        "Also send code snippets (no code screenshots), screenshots and "
        "other media, error messages, etc.\n\n"
        "**Changing post titles:**\n"
        "> 1. Right-click post (desktop/web) or click & hold (mobile)\n"
        "> 2. Click **'Edit Post'** to see the post settings, and make title changes.\n"
        "> 3. Ensure your changes are saved.\n\n"
        "This alert should disappear after you've made appropriate changes.",
        "color": 0x36393F,
    },
    "member_asking_for_code": {
        "title": "Please don't ask if anybody can write your code, game, project or "
        "assignment for you.",
        "description": "### Did you read our 👉 "
        "[Post & Question Guide](https://discord.com/channels/772505616680878080/1093999727667855380/1094000466712604681)? 👈\n\n"
        "All helpers here are volunteers, who show people how to "
        "improve or add things in their code by themselves. They don't do "
        "all the work for them. Show us what you are working on, what you've "
        "tried, as well as where you got stuck. "
        "Also send code snippets (no code screenshots), screenshots and "
        "other media, error messages, etc.\n\n"
        "**Changing post titles:**\n"
        "> 1. Right-click post (desktop/web) or click & hold (mobile)\n"
        "> 2. Click **'Edit Post'** to see the post settings, and make title changes.\n"
        "> 3. Ensure your changes are saved.\n\n"
        "This alert should disappear after you've made appropriate changes.",
        "color": 0x36393F,
    },
    "member_asking_about_problem_with_code": {
        "title": "There's a problem with your code, game, project or assignment? "
        "Please tell us what are you struggling with.",
        "description": "### Did you read our 👉 "
        "[Post & Question Guide](https://discord.com/channels/772505616680878080/1093999727667855380/1094000466712604681)? 👈\n\n"
        "Use your help post title and your starter message "
        "to describe how the problems with it came up. What made your code stop "
        "working? What are you trying to do? "
        "Remember to send along code snippets (no code screenshots), screenshots "
        "and other media, error messages, etc.\n\n"
        "**Changing post titles:**\n"
        "> 1. Right-click post (desktop/web) or click & hold (mobile)\n"
        "> 2. Click **'Edit Post'** to see the post settings, and make title changes.\n"
        "> 3. Ensure your changes are saved.\n\n"
        "This alert should disappear after you've made appropriate changes.",
        "color": 0x36393F,
    },
}
