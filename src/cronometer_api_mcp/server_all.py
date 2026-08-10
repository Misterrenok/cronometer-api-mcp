"""Full Cronometer MCP entrypoint: mobile REST tools plus confirmed web tools."""

from . import server_ext as extended
from . import control_tools as _control_tools  # noqa: F401
from . import entry_update_tools as _entry_update_tools  # noqa: F401
from . import hybrid_tools as _hybrid_tools  # noqa: F401
from . import export_tools as _export_tools  # noqa: F401

mcp = extended.mcp


def main() -> None:
    """Run the full Streamable HTTP Cronometer MCP server."""
    extended.main()


if __name__ == "__main__":
    main()
