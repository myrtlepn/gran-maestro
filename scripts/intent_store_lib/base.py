from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence


class IntentStoreError(Exception):
    """Raised when an intent store operation fails."""


class IntentStore(ABC):
    @abstractmethod
    def add(
        self,
        intent_id: str,
        *,
        feature: str,
        situation: str,
        motivation: str,
        goal: str,
        linked_req: Optional[str] = None,
        linked_plan: Optional[str] = None,
        related_intent: Optional[Sequence[str]] = None,
        tags: Optional[Sequence[str]] = None,
        files: Optional[Sequence[str]] = None,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update(
        self,
        intent_id: str,
        *,
        feature: Optional[str] = None,
        situation: Optional[str] = None,
        motivation: Optional[str] = None,
        goal: Optional[str] = None,
        linked_req: Optional[str] = None,
        linked_plan: Optional[str] = None,
        related_intent: Optional[Sequence[str]] = None,
        tags: Optional[Sequence[str]] = None,
        files: Optional[Sequence[str]] = None,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, intent_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get(self, intent_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def search(self, keyword: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def lookup(self, files: Sequence[str]) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def related(self, intent_id: str, depth: int = 1) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def rebuild(self) -> Dict[str, Any]:
        raise NotImplementedError

