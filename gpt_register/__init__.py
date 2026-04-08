def main(*args, **kwargs):
    from .cli import main as _main

    return _main(*args, **kwargs)


__all__ = ["main"]
