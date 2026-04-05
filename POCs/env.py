"""
Central environment loader for all POCs.

Reads the .env file from the project root once, making all variables
available via the standard ``os.getenv()`` calls that individual POC
modules already use.

Usage — add this single line near the top of any POC entry-point
(demo.py, agent.py, bot_server.py, etc.):

    import POCs.env  # noqa: F401  — loads .env on import
"""

from pathlib import Path

from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# override=False keeps any values already set in the real environment
load_dotenv(_ENV_FILE, override=False)
