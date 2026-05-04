import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from loop import launch_instance, load_config, load_dotenv


def main() -> int:
    load_dotenv("config/.env.e2micro")
    launch_instance(load_config())
    return 0


if __name__ == "__main__":
    sys.exit(main())
