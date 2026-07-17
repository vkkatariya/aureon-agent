import contextlib
from typing import List, Optional, Any
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
import questionary

from aureon_agent import __version__

console = Console()

# 5x7 pixel font (same as scripts/generate_banner.py)
_PIXEL_FONT = {
    "A": [" ### ", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"],
    "U": ["#   #", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    "R": ["#### ", "#   #", "#   #", "#### ", "# #  ", "#  # ", "#   #"],
    "E": ["#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"],
    "O": [" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    "N": ["#   #", "##  #", "# # #", "# # #", "#  ##", "#   #", "#   #"],
    "G": [" ### ", "#   #", "#    ", "# ###", "#   #", "#   #", " ### "],
    "T": ["#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "],
    "-": ["     ", "     ", "     ", " ### ", "     ", "     ", "     "],
    " ": ["     ", "     ", "     ", "     ", "     ", "     ", "     "],
}

# Warm orange gradient matching assets/banner.svg
# Top: #FFD24A (bright), Middle: #FF8A2B (main), Bottom: #E85D04 (deep)
_GRADIENT_COLORS = ["#FFD24A", "#FFB347", "#FF8A2B", "#FF8A2B", "#E85D04", "#E85D04", "#E85D04"]


def _render_pixel_text(text: str, char_gap: int = 2) -> list[str]:
    """Render text as 7 rows of unicode block chars (█ for filled, space for empty).
    Each char is 5 cols wide, chars separated by char_gap spaces.
    Returns 7 strings, each is one row of the pixel art.
    """
    rows = ["", "", "", "", "", "", ""]
    for i, ch in enumerate(text.upper()):
        glyph = _PIXEL_FONT.get(ch, _PIXEL_FONT[" "])
        for row_idx in range(7):
            row_str = glyph[row_idx]
            # Convert '#' to '█' and ' ' to ' '
            rendered = "".join("█" if c == "#" else " " for c in row_str)
            rows[row_idx] += rendered
            if i < len(text) - 1:
                rows[row_idx] += " " * char_gap
    return rows


def print_banner():
    """Print pixel-art AUREON-AGENT banner matching assets/banner.svg style.
    
    Renders the wordmark in warm orange gradient on dark background,
    with top + bottom accent bars (matching the SVG banner).
    """
    wordmark = "AUREON-AGENT"
    pixel_rows = _render_pixel_text(wordmark, char_gap=2)
    
    # Wordmark is 82 chars wide (12 chars × 5 cols + 11 gaps × 2). Add 6 padding.
    bar_width = 88
    
    # Build a Rich Text with gradient: each row gets its own color from the gradient
    banner = Text()
    
    # Top accent bar (orange line)
    banner.append("━" * bar_width + "\n", style="#E85D04")
    
    # Pixel art wordmark (7 rows, each row colored per gradient position)
    for row_idx, row in enumerate(pixel_rows):
        color = _GRADIENT_COLORS[row_idx]
        centered = row.center(bar_width)
        banner.append(centered + "\n", style=f"bold {color}")
    
    # Bottom accent bar
    banner.append("━" * bar_width + "\n", style="#E85D04")
    
    # Version + tagline
    tagline = f"v{__version__} · OLLAMA + TELEGRAM · DOCTRINE-AWARE"
    banner.append(tagline.center(bar_width) + "\n", style="dim white")
    banner.append("github.com/vkkatariya/aureon-agent".center(bar_width), style="dim #FF8A2B")
    
    console.print(banner)

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
