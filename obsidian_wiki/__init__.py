"""obsidian-wiki: a markdown vault your agents can use as memory.

Three faces onto the same vault:

* the agent skills under ``.skills/`` (the original product, bundled as data)
* the ``obsidian-wiki`` CLI — see ``cli.py``
* :class:`~obsidian_wiki.client.Memory`, for using a vault from Python::

      from obsidian_wiki import Memory

      memory = Memory("~/brain", user_id="alice")
      memory.remember("stack", "Python, FastAPI", confidence=0.9)
      memory.add("Postgres was chosen over MySQL for partial indexes.")
      memory.search("database choice")
      memory.recap()
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("obsidian-wiki")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+dev"

def __getattr__(name: str):
    # Imported lazily so `obsidian_wiki.__version__` stays cheap and the CLI
    # does not pay for the client on every invocation.
    if name in ("Memory", "MemoryError_", "resolve_vault"):
        from obsidian_wiki import client

        return getattr(client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["__version__", "Memory", "MemoryError_", "resolve_vault"]
