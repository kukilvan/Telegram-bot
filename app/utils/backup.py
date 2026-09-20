import shutil
from datetime import datetime
from pathlib import Path

DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_FILE = DB_DIR / "bot.db"
BACKUP_DIR = DB_DIR / "backups"


def create_backup() -> Path | None:
    """Create a dated backup of the SQLite database. Returns backup path or None if DB doesn't exist."""
    if not DB_FILE.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"bot_db_{timestamp}.db"

    shutil.copy2(DB_FILE, backup_file)
    return backup_file
