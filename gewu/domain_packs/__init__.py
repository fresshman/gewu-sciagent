"""领域包索引。新增领域只需在此挂接对应包。"""
from .coal_libs import register_coal_tools

__all__ = ["register_coal_tools"]
