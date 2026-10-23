"""Install or remove the platform's daily, inbox, and weekly jobs."""
from . import platform


def install() -> list[str]:
    return platform.schedule_install()


def remove() -> list[str]:
    return platform.schedule_remove()
