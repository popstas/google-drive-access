from time import time
from typing import Any, Dict, List, Set, Tuple

import requests
from loguru import logger

from .model import PlanfixConfig


class PlanfixClient:
    def __init__(self, config: PlanfixConfig):
        self._config = config
        self._manager_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}

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
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            raise ValueError("Unexpected response structure for child tasks")
        logger.info("Received {} child tasks", len(tasks))
        return tasks

    def get_manager(self, assignee_id: str) -> Dict[str, Any]:
        # Check cache
        if assignee_id in self._manager_cache:
            cached_manager, cached_time = self._manager_cache[assignee_id]
            if time() - cached_time < 86400:  # 24 hours
                logger.debug(
                    "Using cached manager for assignee_id={}", assignee_id
                )
                return cached_manager
            else:
                logger.debug(
                    "Cache expired for assignee_id={}, fetching fresh data",
                    assignee_id,
                )
        
        payload = {"id": int(assignee_id)}
        logger.debug("Fetching manager for assignee_id={}", assignee_id)
        response = requests.post(
            self._config.get_manager.url,
            headers=self._headers(self._config.get_manager.token),
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        manager = response.json()
        logger.debug("Manager lookup result for {}: {}", assignee_id, manager)
        
        # Store in cache
        self._manager_cache[assignee_id] = (manager, time())
        
        return manager

    def get_client_task(self, client_id: int) -> Dict[str, Any]:
        payload = {"clientId": client_id}
        logger.debug("Fetching client task for client_id={}", client_id)
        response = requests.post(
            self._config.get_client_task.url,
            headers=self._headers(self._config.get_client_task.token),
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        client_task = response.json()
        logger.debug("Client task lookup result for {}: {}", client_id, client_task)
        return client_task

    def update_contact(self, contact_id: str, google_folder: str) -> Dict[str, Any]:
        try:
            contact_id_int = int(contact_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid contact ID: {contact_id} (must be a number)")
        payload = {"contactId": contact_id_int, "google_folder": google_folder}
        logger.debug(
            "Updating contact {} with google_folder={}", contact_id_int, google_folder
        )
        response = requests.post(
            self._config.update_contact.url,
            headers=self._headers(self._config.update_contact.token),
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        logger.debug("Update contact result for {}: {}", contact_id_int, result)
        return result

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
