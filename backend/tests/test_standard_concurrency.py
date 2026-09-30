import threading
import unittest

from utils.concurrency import run_parallel_ordered, start_background_thread


class StandardConcurrencyTest(unittest.TestCase):
    def test_parallel_results_keep_input_order(self):
        first_pair_started = threading.Barrier(2, timeout=1)

        def worker(value):
            if value < 2:
                first_pair_started.wait()
            return value * 10

        results = run_parallel_ordered(
            [0, 1, 2],
            worker,
            max_workers=2,
            thread_name_prefix="test-parallel",
        )

        self.assertEqual(results, [0, 10, 20])

    def test_background_thread_runs_without_server_runtime(self):
        completed = threading.Event()

        thread = start_background_thread(
            completed.set,
            name="test-background",
        )

        self.assertTrue(completed.wait(1))
        thread.join(1)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
