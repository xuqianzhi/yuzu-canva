"""Print the OpenAPI schema as JSON: python -m canvas_api.export_openapi"""

from __future__ import annotations

import json
import sys

from .app import create_app


def main() -> None:
    json.dump(create_app().openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
