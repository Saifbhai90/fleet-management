# routes package — re-export everything from routes.py for backward compatibility
# This allows `from routes import X` to continue working across all modules.
import os, sys

# Ensure project root is in sys.path so routes.py can import app, models, etc.
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

# Import everything from routes.py (the shared helpers module inside this package)
from .routes import *  # noqa: F401,F403
