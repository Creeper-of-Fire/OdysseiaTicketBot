from abc import ABC, abstractmethod
from typing import List, Optional

from .models import AnyWish


class IWishExternalAdapter(ABC):
    """
    外部交互适配器接口（Port）。
    未来的 Discord Bot 只需要实现这个接口即可与核心引擎对接。
    """

    @abstractmethod
    async def create_discussion_thread(self, wish: AnyWish) -> str:
        """创建讨论区，返回 thread_id"""
        pass

    @abstractmethod
    async def lock_discussion_thread(self, thread_id: str):
        """锁定/归档讨论区"""
        pass

    @abstractmethod
    async def unlock_discussion_thread(self, thread_id: str):
        """解锁讨论区"""
        pass

    @abstractmethod
    async def send_notification(self, target_user_id: str, message: str):
        """给指定用户发送通知 (如私信)"""
        pass

    @abstractmethod
    async def broadcast_event(self, message: str):
        """在主频道广播事件 (如：愿望已实现)"""
        pass


class IWishRepository(ABC):
    """
    数据持久化接口（Port）。
    引擎只管调用这些方法，不关心底层是 JSON 还是 MySQL。
    """

    @abstractmethod
    async def save(self, wish: AnyWish): pass

    @abstractmethod
    async def get(self, wish_id: str) -> Optional[AnyWish]: pass

    @abstractmethod
    async def get_all(self) -> List[AnyWish]: pass
