from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from dropwatch.common.types import Listing


class BaseFetcher(ABC):
    is_global: bool = False

    @abstractmethod
    async def fetch(self, task=None, profile=None) -> list[Listing]:
        raise NotImplementedError


class GlobalFetcher(BaseFetcher):
    is_global = True

    async def fetch(self, task=None, profile=None) -> list[Listing]:
        return await self.fetch_all()

    @abstractmethod
    async def fetch_all(self) -> list[Listing]:
        raise NotImplementedError
