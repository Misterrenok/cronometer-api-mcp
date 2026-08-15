"""Full Cronometer MCP entrypoint: mobile REST tools plus confirmed web tools."""

from . import server_ext as extended
from . import biometric_control_tools as _biometric_control_tools  # noqa: F401
from . import control_tools as _control_tools  # noqa: F401
from . import entry_update_tools as _entry_update_tools  # noqa: F401
from . import hybrid_tools as _hybrid_tools  # noqa: F401
from . import mobile_write_fixes as _mobile_write_fixes  # noqa: F401
from . import gwt_macro_template_fix as _gwt_macro_template_fix  # noqa: F401
from . import repeat_control_tools as _repeat_control_tools  # noqa: F401
from . import repeat_v2_tools as _repeat_v2_tools  # noqa: F401
from . import repeat_v3_patch as _repeat_v3_patch  # noqa: F401
from . import repeat_v5_patch as _repeat_v5_patch  # noqa: F401
from . import repeat_v6_patch as _repeat_v6_patch  # noqa: F401
from . import repeat_v12_final as _repeat_v12_final  # noqa: F401
from . import repeat_live_probe as _repeat_live_probe  # noqa: F401
from . import export_tools as _export_tools  # noqa: F401

mcp = extended.mcp


def main() -> None:
    """Run the full Streamable HTTP Cronometer MCP server."""
    extended.main()


if __name__ == "__main__":
    main()
