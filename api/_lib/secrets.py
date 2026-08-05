"""Reads the node-executor secrets bundle from env vars. Every API route that calls engine.run_execution/resume_execution builds this the same way."""
import os


def get_node_secrets() -> dict:
    return {
        "FAL_KEY": os.environ.get("FAL_KEY", ""),
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", ""),
    }
