"""Enable `python -m meridian.notify "msg" -p P0`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
