import sys
import types
import unittest
from unittest.mock import patch

from services.pipeline_queue.contracts import WorkItem
from services.pipeline_queue.handlers import handle_auto_pilot_work_item


def _item():
    return WorkItem(
        id="11111111-1111-1111-1111-111111111111",
        pipeline_job_id=42,
        run_id="run-42",
        task_type="auto_pilot_tick",
        scope_key="pipeline",
        dedupe_key="run-42:auto:reac",
        payload={"expected_step": "reac"},
        status="running",
        priority=0,
        attempt_count=1,
        max_attempts=5,
        available_at=None,
        lease_owner="worker",
        lease_token="22222222-2222-2222-2222-222222222222",
        lease_version=3,
        lease_expires_at=None,
        last_error=None,
        result={},
        created_at=None,
        updated_at=None,
    )


class _Lease:
    def __init__(self):
        self.checkpoints = 0

    def checkpoint(self):
        self.checkpoints += 1


class PipelineQueueHandlerTest(unittest.TestCase):
    def _modules(self, *, execute_error=None, next_steps=("reac", None)):
        events = []
        updates = []
        steps = iter(next_steps)
        job = {
            "id": 42,
            "auto_pilot_enabled": True,
            "auto_pilot_model": "pro",
            "auto_pilot_tts_mode": "gtts",
            "auto_pilot_use_cc": False,
            "auto_pilot_generate_audio": False,
        }

        routes_module = types.SimpleNamespace()
        routes_module.get_job = lambda _job_id: dict(job)
        routes_module.update_job = lambda job_id, **kwargs: updates.append((job_id, kwargs))
        routes_module._determine_next_ap_step = lambda _job_id: next(steps)
        routes_module.executed_steps = []

        def execute(_job_id, _step, _job):
            routes_module.executed_steps.append(_step)
            if execute_error:
                raise execute_error

        routes_module._execute_ap_step = execute
        routes_package = types.ModuleType("routes")
        routes_package.formation_routes = routes_module

        observability = types.ModuleType("services.formation_observability_service")
        observability.log_pipeline_event = (
            lambda job_id, event_type, **kwargs: events.append((job_id, event_type, kwargs))
        )
        return routes_package, observability, events, updates

    def test_success_preserves_step_and_pipeline_completion_events(self):
        routes_package, observability, events, updates = self._modules()
        lease = _Lease()
        with patch.dict(
            sys.modules,
            {
                "routes": routes_package,
                "services.formation_observability_service": observability,
            },
        ):
            result = handle_auto_pilot_work_item(_item(), lease)

        self.assertEqual(result.result["status"], "done")
        self.assertEqual(lease.checkpoints, 2)
        self.assertEqual(
            [event_type for _job_id, event_type, _kwargs in events],
            ["step_started", "step_completed", "pipeline_completed"],
        )
        for _job_id, _event_type, kwargs in events:
            self.assertEqual(kwargs["data"]["work_item_id"], _item().id)
            self.assertEqual(kwargs["data"]["fence"], 3)
        self.assertTrue(any(update[1].get("auto_pilot_step") == "done" for update in updates))

    def test_failure_preserves_step_failed_event_and_reraises(self):
        routes_package, observability, events, _updates = self._modules(
            execute_error=RuntimeError("LLM timeout"),
            next_steps=("reac",),
        )
        with patch.dict(
            sys.modules,
            {
                "routes": routes_package,
                "services.formation_observability_service": observability,
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "LLM timeout"):
                handle_auto_pilot_work_item(_item(), _Lease())

        self.assertEqual(
            [event_type for _job_id, event_type, _kwargs in events],
            ["step_started", "step_failed"],
        )
        self.assertEqual(events[-1][2]["error"], "LLM timeout")

    def test_out_of_order_tick_skips_execution_and_chains_current_step(self):
        routes_package, observability, events, updates = self._modules(
            next_steps=("global",),
        )
        lease = _Lease()
        with patch.dict(
            sys.modules,
            {
                "routes": routes_package,
                "services.formation_observability_service": observability,
            },
        ):
            result = handle_auto_pilot_work_item(_item(), lease)

        self.assertEqual(routes_package.formation_routes.executed_steps, [])
        self.assertEqual(lease.checkpoints, 1)
        self.assertEqual(result.result["status"], "step_reconciled")
        self.assertEqual(result.result["skipped_step"], "reac")
        self.assertEqual(result.result["next_step"], "global")
        self.assertEqual(len(result.next_items), 1)
        next_item = result.next_items[0]
        self.assertEqual(next_item.payload["expected_step"], "global")
        self.assertEqual(next_item.scope_key, "pipeline")
        self.assertIn(_item().id, next_item.dedupe_key)
        self.assertEqual(
            [event_type for _job_id, event_type, _kwargs in events],
            ["step_reconciled"],
        )
        self.assertTrue(
            any(update[1].get("auto_pilot_step") == "global" for update in updates)
        )


if __name__ == "__main__":
    unittest.main()
