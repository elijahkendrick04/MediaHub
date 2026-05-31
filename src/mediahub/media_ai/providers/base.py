"""Background remover interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BackgroundRemover(ABC):
    name: str = "base"

    @abstractmethod
    def remove(self, src_path: str, dst_path: str) -> str:
        """Remove background from src_path, write PNG with alpha to dst_path.

        Returns dst_path on success. Raises on hard failure.
        """
        ...

    def is_available(self) -> bool:
        return True
