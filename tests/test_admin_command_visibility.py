import ast
import unittest
from pathlib import Path

import discord
from discord import app_commands

from cogs.admin_visibility import (
    ADMIN_COMMAND_PERMISSIONS,
    ADMIN_ONLY_COMMANDS,
    apply_admin_command_visibility,
)


ROOT = Path(__file__).resolve().parents[1]


def _is_app_command_decorator(decorator: ast.AST) -> bool:
    call = decorator if isinstance(decorator, ast.Call) else None
    if call is None:
        return False
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "command"
        and isinstance(func.value, ast.Name)
        and func.value.id == "app_commands"
    )


def _command_name(decorator: ast.Call) -> str | None:
    for keyword in decorator.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    return None


def _has_permission_decorator(decorators: list[ast.AST]) -> bool:
    for decorator in decorators:
        text = ast.unparse(decorator)
        if "checks.has_permissions" in text:
            return True
    return False


def _admin_commands_from_source() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "cogs").glob("*.py"):
        if path.name in {"admin_visibility.py", "help.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            command_name = None
            for decorator in node.decorator_list:
                if _is_app_command_decorator(decorator):
                    command_name = _command_name(decorator)
                    break
            if not command_name:
                continue
            body_source = "\n".join(
                ast.get_source_segment(source, item) or "" for item in node.body
            )
            is_admin_only = (
                _has_permission_decorator(node.decorator_list)
                or "_require_admin(" in body_source
                or "_is_admin(" in body_source
                or "_rules_admin(" in body_source
            )
            if is_admin_only:
                found.add(command_name)
    return found


class AdminCommandVisibilityTest(unittest.TestCase):
    def test_admin_command_sets_are_in_sync(self):
        self.assertEqual(ADMIN_ONLY_COMMANDS, set(ADMIN_COMMAND_PERMISSIONS))

    def test_every_admin_command_is_hidden_from_regular_members(self):
        self.assertEqual(_admin_commands_from_source(), ADMIN_ONLY_COMMANDS)

    def test_visibility_helper_sets_default_member_permissions(self):
        async def visible_callback(interaction):
            pass

        async def admin_callback(interaction):
            pass

        regular = app_commands.Command(name="rank", description="rank", callback=visible_callback)
        admin = app_commands.Command(name="warn", description="warn", callback=admin_callback)

        class _Tree:
            def get_commands(self):
                return [regular, admin]

        apply_admin_command_visibility(_Tree())
        self.assertIsNone(regular.default_permissions)
        self.assertEqual(admin.default_permissions, discord.Permissions(manage_messages=True))


if __name__ == "__main__":
    unittest.main()
