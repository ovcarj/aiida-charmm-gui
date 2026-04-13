"""Login subcommand for the `aiida-charmm-gui` CLI."""

import click

from aiida_charmm_gui.client import CharmmGuiAuthError, CharmmGuiClient, CharmmGuiConfigError


@click.command("login")
@click.option("--username", "-u", default=None, help="CHARMM-GUI account email.")
@click.option("--password", "-p", default=None, hide_input=True, help="CHARMM-GUI account password.")
@click.option("--status", is_flag=True, default=False, help="Check whether a valid cached token exists.")
def cmd_login(username, password, status):
    """Authenticate with the CHARMM-GUI API and cache the token locally."""
    client = CharmmGuiClient(email=username, password=password)

    if status:
        cached = client.get_cached_token()
        if cached:
            click.echo(f"Token is valid (expires at {cached.expires_at}).")
        else:
            click.echo("No valid cached token found.", err=True)
            raise SystemExit(1)
        return

    try:
        token_info = client.login()
    except CharmmGuiConfigError as e:
        raise click.UsageError(str(e)) from e
    except CharmmGuiAuthError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"Login successful. Token cached (expires at {token_info.expires_at}).")
