from abc import ABC, abstractmethod
from typing import List, Optional

from .models import AnyBottle


class IBottleRepository(ABC):

    @abstractmethod
    async def save(self, bottle: AnyBottle): pass

    @abstractmethod
    async def get(self, bottle_id: str) -> Optional[AnyBottle]: pass

    @abstractmethod
    async def get_all(self) -> List[AnyBottle]: pass


class IBottleExternalAdapter(ABC):

    @abstractmethod
    async def send_notification(self, target_user_id: str, message: str): pass

    @abstractmethod
    async def broadcast_event(self, message: str): pass
