"""Full Cronometer MCP entrypoint: mobile REST tools plus confirmed web writes."""

from . import server_ext as extended
from . import hybrid_tools as _hybrid_tools  # noqa: F401

mcp = extended.mcp


def main() -> None:
    """Run the full Streamable HTTP Cronometer MCP server."""
    extended.main()


if __name__ == "__main__":
    main()
