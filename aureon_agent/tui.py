import os
import contextlib
from typing import List, Optional, Any
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
import questionary

from aureon_agent import __version__

console = Console()

def print_banner():
    banner = Text("🦾 Aureon Agent Setup", justify="center", style="bold cyan")
    banner.append(f"\nVersion {__version__}", style="dim")
    banner.append("\nWelcome to aureon-agent setup", style="italic")
    console.print(Panel(banner, border_style="cyan"))

def print_section(title: str, body: str = ""):
    console.print(f"\n[bold cyan]▶ {title}[/bold cyan]")
    if body:
        console.print(f"[dim]{body}[/dim]")

def confirm(prompt: str, default: bool = False) -> bool:
    return questionary.confirm(prompt, default=default).ask()

def select(prompt: str, choices: List[str], default: Optional[str] = None) -> str:
    return questionary.select(prompt, choices=choices, default=default).ask()

def checkbox(prompt: str, choices: List[str], default: Optional[List[str]] = None) -> List[str]:
    # Need to extract values properly from questionary choices if they are objects
    if default is None:
        default = []
    # Currently questionary checkbox sets checked=True for the initial values
    # But questionary 2+ doesn't have a direct default param for checkbox like select
    # We create Choice objects if needed or just pass strings.
    # To pre-select, we can map choices to Choice objects.
    q_choices = []
    for c in choices:
        q_choices.append(questionary.Choice(c, checked=(c in default)))
    return questionary.checkbox(prompt, choices=q_choices).ask()

def text(prompt: str, default: str = "", validate: Any = None, password: bool = False) -> str:
    if password:
        return questionary.password(prompt, validate=validate).ask()
    return questionary.text(prompt, default=default, validate=validate).ask()

def password(prompt: str, validate: Any = None) -> str:
    return text(prompt, validate=validate, password=True)

def path(prompt: str, default: str = "", must_exist: bool = False) -> str:
    return questionary.path(prompt, default=default, only_directories=False).ask()

def print_status(message: str, status: str = "success"):
    if status == "success":
        console.print(f"[bold green]✅ {message}[/bold green]")
    elif status == "error":
        console.print(f"[bold red]❌ {message}[/bold red]")
    elif status == "warn":
        console.print(f"[bold yellow]⚠️ {message}[/bold yellow]")
    else:
        console.print(message)

def print_table(headers: List[str], rows: List[List[str]], title: Optional[str] = None):
    table = Table(title=title)
    for h in headers:
        table.add_column(h)
    for row in rows:
        table.add_row(*row)
    console.print(table)

@contextlib.contextmanager
def spinner(message: str):
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description=message, total=None)
        yield

@contextlib.contextmanager
def progress(message: str):
    # Synonym for spinner in this case, representing indeterminate progress
    with spinner(message):
        yield
