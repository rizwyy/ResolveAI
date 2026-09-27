"""Lambda entrypoint: HTTP API goes through Mangum; SQS/scheduled events claim persisted turns."""
from mangum import Mangum
from .main import app
from .worker import run_once

http_handler = Mangum(app, lifespan="auto")

def handler(event, context):
    if isinstance(event, dict) and event.get("Records"):
        processed = run_once()
        return {"batchItemFailures": [], "processed": processed}
    return http_handler(event, context)
