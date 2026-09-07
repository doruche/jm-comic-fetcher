from importlib import import_module


def check_worker_dependencies() -> None:
    """Let AstrBot's import-time recovery see dependencies used only by workers.

    Importing the worker validates its complete import graph without starting a
    client, making a request or launching a task.
    """
    import_module(f"{__package__}.worker")
