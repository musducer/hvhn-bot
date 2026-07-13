import discord
from discord import app_commands


# Commands listed here are synced to Discord with default member permissions,
# making them hidden from ordinary members in the native slash-command picker.
ADMIN_ONLY_COMMANDS = {
    "addbadword",
    "ai_feedback_duyet",
    "ai_feedback_stats",
    "ai_gioihan_dat",
    "ai_gioihan_reset",
    "ai_gioihan_xem",
    "ai_kienthuc_them",
    "announce",
    "answer",
    "ban",
    "clear",
    "giverole",
    "hvhn_capkhach",
    "hvhn_debug_retrieval",
    "hvhn_embed_backfill",
    "hvhn_giahan",
    "hvhn_giahankhach",
    "hvhn_huykhach",
    "hvhn_khach",
    "hvhn_khach_check",
    "hvhn_khach_ds",
    "hvhn_moikhach",
    "hvhn_retry_failed",
    "hvhn_status_full",
    "hvhn_tailieu_khach",
    "hvhn_tailieu_khach_link",
    "hvhn_themkhach",
    "hvhn_xoakhach",
    "hvhn_xoatailieu",
    "kick",
    "lock",
    "luat_dang",
    "luat_reset",
    "luat_sua",
    "luat_them",
    "luat_xem",
    "luat_xoa",
    "mute",
    "questions",
    "removebadword",
    "removerole",
    "setup",
    "slowmode",
    "unban",
    "unlock",
    "unmute",
    "warn",
}

ADMIN_COMMAND_PERMISSIONS = {
    "addbadword": discord.Permissions(manage_guild=True),
    "ai_feedback_duyet": discord.Permissions(manage_guild=True),
    "ai_feedback_stats": discord.Permissions(manage_guild=True),
    "ai_gioihan_dat": discord.Permissions(manage_guild=True),
    "ai_gioihan_reset": discord.Permissions(manage_guild=True),
    "ai_gioihan_xem": discord.Permissions(manage_guild=True),
    "ai_kienthuc_them": discord.Permissions(manage_guild=True),
    "announce": discord.Permissions(manage_messages=True),
    "answer": discord.Permissions(manage_messages=True),
    "ban": discord.Permissions(ban_members=True),
    "clear": discord.Permissions(manage_messages=True),
    "giverole": discord.Permissions(manage_roles=True),
    "hvhn_capkhach": discord.Permissions(manage_guild=True),
    "hvhn_debug_retrieval": discord.Permissions(manage_guild=True),
    "hvhn_embed_backfill": discord.Permissions(manage_guild=True),
    "hvhn_giahan": discord.Permissions(manage_guild=True),
    "hvhn_giahankhach": discord.Permissions(manage_guild=True),
    "hvhn_huykhach": discord.Permissions(manage_guild=True),
    "hvhn_khach": discord.Permissions(manage_guild=True),
    "hvhn_khach_check": discord.Permissions(manage_guild=True),
    "hvhn_khach_ds": discord.Permissions(manage_guild=True),
    "hvhn_moikhach": discord.Permissions(manage_guild=True),
    "hvhn_retry_failed": discord.Permissions(manage_guild=True),
    "hvhn_status_full": discord.Permissions(manage_guild=True),
    "hvhn_tailieu_khach": discord.Permissions(manage_guild=True),
    "hvhn_tailieu_khach_link": discord.Permissions(manage_guild=True),
    "hvhn_themkhach": discord.Permissions(manage_guild=True),
    "hvhn_xoakhach": discord.Permissions(manage_guild=True),
    "hvhn_xoatailieu": discord.Permissions(manage_guild=True),
    "kick": discord.Permissions(kick_members=True),
    "lock": discord.Permissions(manage_channels=True),
    "luat_dang": discord.Permissions(manage_guild=True),
    "luat_reset": discord.Permissions(manage_guild=True),
    "luat_sua": discord.Permissions(manage_guild=True),
    "luat_them": discord.Permissions(manage_guild=True),
    "luat_xem": discord.Permissions(manage_guild=True),
    "luat_xoa": discord.Permissions(manage_guild=True),
    "mute": discord.Permissions(moderate_members=True),
    "questions": discord.Permissions(manage_messages=True),
    "removebadword": discord.Permissions(manage_guild=True),
    "removerole": discord.Permissions(manage_roles=True),
    "setup": discord.Permissions(administrator=True),
    "slowmode": discord.Permissions(manage_channels=True),
    "unban": discord.Permissions(ban_members=True),
    "unlock": discord.Permissions(manage_channels=True),
    "unmute": discord.Permissions(moderate_members=True),
    "warn": discord.Permissions(manage_messages=True),
}


def iter_commands(commands):
    for command in commands:
        yield command
        if isinstance(command, app_commands.Group):
            yield from iter_commands(command.commands)


def apply_admin_command_visibility(tree: app_commands.CommandTree) -> None:
    for command in iter_commands(tree.get_commands()):
        if isinstance(command, app_commands.Command) and command.name in ADMIN_COMMAND_PERMISSIONS:
            command.default_permissions = ADMIN_COMMAND_PERMISSIONS[command.name]
