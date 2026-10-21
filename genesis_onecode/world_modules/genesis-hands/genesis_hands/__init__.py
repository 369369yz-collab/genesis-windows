"""genesis_hands: the HANDS module of the GENESIS Windows assistant.

Execute plans on the Windows desktop (pywinauto) or in a browser (Playwright),
always behind the three-tier permission gate and with high-risk steps routed
through Windows Sandbox when available.

Exports: execute, check_permission.
"""

from genesis_hands.hands import execute
from genesis_hands.permission_gate import check as check_permission

__version__ = "1.0.0"
__all__ = ["execute", "check_permission"]
