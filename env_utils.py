import os

from dotenv import load_dotenv


# Several modules read configuration while they are imported. Load the local
# .env here so command-line entry points behave like the hosted bot as well.
load_dotenv()


def env_int(name: str, default: int, *, minimum: int | None = None,
            maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except (AttributeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def env_float(name: str, default: float, *, minimum: float | None = None,
              maximum: float | None = None) -> float:
    try:
        value = float(os.getenv(name, str(default)).strip())
    except (AttributeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value
