"""
Importing this package registers every node executor into NODE_REGISTRY (see base.py).
Each entry below corresponds to a module that must define one or more functions
decorated with @register_node("type/name") from api._lib.nodes.base.

Modules not yet implemented are skipped silently so the app keeps running with a
partial node set during development.
"""

_MODULES = [
    "trigger_manual",
    "trigger_webhook",
    "trigger_schedule",
    "http_request",
    "supabase_query",
    "fal_generate_image",
    "fal_train_lora",
    "llm_prompt",
    "delay",
    "condition",
    "set_transform",
]

for _name in _MODULES:
    try:
        __import__(f"{__name__}.{_name}")
    except ImportError as exc:
        # Keep booting with a partial node set rather than taking down every
        # route that imports the engine — but say so loudly. Swallowing this
        # silently turns a typo in one executor into a baffling
        # "Unknown node type" at run time instead of a traceable import error.
        print(f"[flowforge] node module {_name!r} failed to import: {exc}")
