"""Páginas NiceGUI do portal."""

from .admin import register as register_admin
from .guidelines_admin import register as register_guidelines
from .login import register as register_login
from .shell import register as register_shell
from .system_create import register as register_system_create
from .system_detail import register as register_system_detail


def register_pages() -> None:
    register_login()
    register_shell()
    register_admin()
    register_guidelines()
    register_system_create()
    register_system_detail()
