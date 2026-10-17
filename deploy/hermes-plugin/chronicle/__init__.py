"""Hermes Agent memory provider plugin for Chronicle.

Installed to $HERMES_HOME/plugins/chronicle/ by deploy/install.sh. The
implementation lives in the chronicle package, which must be installed into
the same Python environment that runs Hermes.
"""

from chronicle.integrations.hermes_provider import ChronicleMemoryProvider


def register(ctx) -> None:
    ctx.register_memory_provider(ChronicleMemoryProvider())
