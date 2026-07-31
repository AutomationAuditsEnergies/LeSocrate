"""Primitives de concurrence standard partagées par le backend.

Les travaux longs et récupérables appartiennent à la file durable. Ces outils
ne servent qu'aux petits fan-outs bornés à l'intérieur d'une étape déjà prise
en charge, ou aux anciennes actions administratives asynchrones.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
import threading
from typing import Any, TypeVar


ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")


def start_background_thread(
    target: Callable[..., Any],
    *args: Any,
    name: str | None = None,
    **kwargs: Any,
) -> threading.Thread:
    """Démarre une tâche locale non durable sans dépendre du serveur HTTP."""
    thread = threading.Thread(
        target=target,
        args=args,
        kwargs=kwargs,
        name=name,
        daemon=True,
    )
    thread.start()
    return thread


def run_parallel_ordered(
    items: Iterable[ItemT],
    worker: Callable[[ItemT], ResultT],
    *,
    max_workers: int,
    thread_name_prefix: str = "socrate",
) -> list[ResultT]:
    """Exécute un fan-out borné et restitue les résultats dans l'ordre d'entrée.

    Toutes les tâches déjà soumises sont attendues avant de propager la première
    erreur, comme le faisaient les anciens pools coopératifs.
    """
    item_list = list(items)
    if not item_list:
        return []
    worker_count = max(1, min(int(max_workers or 1), len(item_list)))
    if worker_count == 1:
        return [worker(item) for item in item_list]

    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix=thread_name_prefix,
    ) as executor:
        futures = [executor.submit(worker, item) for item in item_list]
        results: list[ResultT | None] = [None] * len(futures)
        first_error: Exception | None = None
        for index, future in enumerate(futures):
            try:
                results[index] = future.result()
            except Exception as exc:  # attendre aussi les autres futures
                if first_error is None:
                    first_error = exc

    if first_error is not None:
        raise first_error
    return list(results)  # type: ignore[arg-type]
