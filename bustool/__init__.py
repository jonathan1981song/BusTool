"""
bustool/__init__.py
-------------------
Marks the `bustool` directory as a Python package and exposes the public
surface of the library.

Importing `bustool` directly gives access to the main data class without
needing to know the internal module layout:

    from bustool import GTFSData
"""

from bustool.api import GTFSData

__all__ = ["GTFSData"]
