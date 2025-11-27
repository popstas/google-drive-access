from typing import Any, Dict, List, Set

import requests
from loguru import logger

from .model import PlanfixConfig


class PlanfixClient:
    def __init__(self, config: PlanfixConfig):
        self._config = config

    @staticmethod
    def _headers(token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def get_child_tasks(self, task_id: int) -> List[Dict[str, Any]]:
        payload = {"parentTaskId": task_id, "recursive": True}
        logger.debug("Fetching child tasks for task_id={}", task_id)
        response = requests.post(
            self._config.get_child_tasks.url,
            headers=self._headers(self._config.get_child_tasks.token),
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            raise ValueError("Unexpected response structure for child tasks")
        logger.info("Received {} child tasks", len(tasks))
        return tasks

    def get_manager(self, assignee_id: str) -> Dict[str, Any]:
        payload = {"id": int(assignee_id)}
        logger.debug("Fetching manager for assignee_id={}", assignee_id)
        response = requests.post(
            self._config.get_manager.url,
            headers=self._headers(self._config.get_manager.token),
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        manager = response.json()
        logger.debug("Manager lookup result for {}: {}", assignee_id, manager)
        return manager

    def get_client_task(self, client_id: int) -> Dict[str, Any]:
        payload = {"clientId": client_id}
        logger.debug("Fetching client task for client_id={}", client_id)
        response = requests.post(
            self._config.get_client_task.url,
            headers=self._headers(self._config.get_client_task.token),
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        client_task = response.json()
        logger.debug("Client task lookup result for {}: {}", client_id, client_task)
        return client_task

    @staticmethod
    def collect_assignee_ids(
        tasks: List[Dict[str, Any]], initial_assignee_ids: List[str]
    ) -> Set[str]:
        assignee_ids: Set[str] = set()
        for task in tasks:
            users = task.get("assignees", {}).get("users", [])
            for user in users:
                user_id = user.get("id", "")
                if user_id.startswith("user:"):
                    assignee_ids.add(user_id.split(":", 1)[1])
        for initial_assignee_id in initial_assignee_ids:
            assignee_ids.add(str(initial_assignee_id))
        return assignee_ids
