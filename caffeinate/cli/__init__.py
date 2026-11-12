"""명령줄 인터페이스 (python -m caffeinate.cli)"""
from .app import build_parser, main

__all__ = ["build_parser", "main"]
