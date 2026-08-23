"""Package drivers -- contrats et implementations RouterDriver.

Aucun import vendor a ce niveau (invariant C1) : `import drivers` doit
reussir sur toute instance meme sans `tplinkrouterc6u` installe. Les
implementations concretes (ex: `TplinkDriver`, Sprint 2) importent leur lib
vendor dans le corps de leurs methodes, jamais au niveau module.
"""

from ._base import (
    Hop,
    Readiness,
    RouterDriver,
    RouterHealth,
    RouterMetrics,
    RouterReadiness,
    RouterRole,
)

__all__ = [
    "Hop",
    "Readiness",
    "RouterDriver",
    "RouterHealth",
    "RouterMetrics",
    "RouterReadiness",
    "RouterRole",
]
