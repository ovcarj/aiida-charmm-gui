"""Entry point for the `charmm-gui` command"""

import click
from aiida.cmdline.groups import VerdiCommandGroup
from aiida.cmdline.params import options, types


@click.group(name="charmm-gui", cls=VerdiCommandGroup, context_settings={"help_option_names": ["-h", "--help"]})
@options.PROFILE(type=types.ProfileParamType(load_profile=True))
def cmd_root(profile):
    """CLI of the `charmm-gui` AiiDA plugin."""
