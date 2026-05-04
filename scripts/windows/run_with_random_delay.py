import random
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    project_dir = Path(__file__).resolve().parents[2]
    loop_script = project_dir / "loop.py"
    delay_seconds = random.randint(0, 10 * 60)
    print(f"Waiting {delay_seconds} seconds before launch attempt.")
    time.sleep(delay_seconds)
    return subprocess.call([sys.executable, str(loop_script)], cwd=str(project_dir))


if __name__ == "__main__":
    sys.exit(main())
