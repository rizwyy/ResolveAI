import json
from pathlib import Path
from .main import app

Path("../../packages/api-client/openapi.json").write_text(json.dumps(app.openapi(), indent=2) + "\n")
