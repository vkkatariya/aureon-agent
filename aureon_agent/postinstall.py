import os
import sys
import subprocess
import shutil

from aureon_agent.tui import print_banner, print_status, print_section

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def check_python():
    if sys.version_info < (3, 12):
        print_status("Python 3.12+ is required. Found: " + sys.version.split()[0], "error")
        print("Please install Python 3.12 via apt or uv.")
        sys.exit(1)
    print_status(f"Python 3.12+ found: {sys.version.split()[0]}")

def check_pip():
    if not shutil.which("pip"):
        print_status("pip is not available", "error")
        sys.exit(1)
    print_status("pip is available")

def check_ollama():
    if not shutil.which("ollama"):
        print_status("ollama is not in PATH", "warn")
        print("To install: curl -fsSL https://ollama.com/install.sh | sh")
    else:
        print_status("ollama is available")

def check_path():
    local_bin = os.path.expanduser("~/.local/bin")
    if local_bin not in os.environ.get("PATH", ""):
        print_status(f"{local_bin} not in PATH", "warn")
        print(f"Consider adding 'export PATH=\"{local_bin}:$PATH\"' to your ~/.bashrc")

def setup_venv():
    venv_path = os.path.join(BASE_DIR, ".venv")
    if not os.path.exists(venv_path):
        print_status("Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", ".venv"], cwd=BASE_DIR, check=True)
    else:
        print_status("Virtual environment exists")
        
    pip_path = os.path.join(venv_path, "bin", "pip")
    reqs_path = os.path.join(BASE_DIR, "requirements.txt")
    
    print_status("Installing requirements...")
    subprocess.run([pip_path, "install", "-r", reqs_path], cwd=BASE_DIR, check=True)

def main():
    print_banner()
    print_section("Pre-flight Checks")
    
    check_python()
    check_pip()
    check_ollama()
    check_path()
    
    print_section("Environment Setup")
    setup_venv()
    
    print_section("Done")
    print_status("Dependencies installed successfully.")
    print("Run `aureon-agent setup` to configure the agent.")

if __name__ == "__main__":
    main()
