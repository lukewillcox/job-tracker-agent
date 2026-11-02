"""Local Job Tracker CLI.

Runs entirely on the user's Mac: reads their Outlook (read-only), classifies via
the host's shared API (invite code in the Keychain), matches, and keeps an Excel
tracker. Reuses the domain/matcher/state-machine/Excel logic from the backend.
"""

__version__ = "0.1.0"
