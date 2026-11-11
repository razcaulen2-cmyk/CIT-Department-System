from datetime import datetime
from pathlib import Path
import os
import subprocess
import sys


project_root = Path(__file__).resolve().parent
python_path = project_root / "venv" / "Scripts" / "python.exe"
app_path = project_root / "app.py"
log_directory = Path(os.environ["LOCALAPPDATA"]) / "Department Fines Tracker"
log_path = log_directory / "autostart.log"


def main() -> int:
    if not python_path.is_file():
        raise FileNotFoundError(f"Python was not found at {python_path}")
    if not app_path.is_file():
        raise FileNotFoundError(f"app.py was not found at {app_path}")

    log_directory.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Starting Department Fines Tracker.\n")
        log.flush()
        try:
            options = {}
            if os.name == "nt":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                [str(python_path), str(app_path)],
                cwd=project_root,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                **options,
            )
        except OSError as error:
            log.write(f"Failed to launch the app: {error}\n")
            return 1
        log.write(
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
            f"App exited with status {result.returncode}.\n"
        )
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())
