"""Module for the command line interface."""

from .login import cmd_login
from .root import cmd_root

cmd_root.add_command(cmd_login)

__all__ = ["cmd_root"]
