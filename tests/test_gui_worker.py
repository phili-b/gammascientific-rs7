import os
import threading
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from rs7.gui.worker import Worker


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(app, condition, timeout=3.0):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def test_jobs_run_in_order_off_the_gui_thread(app):
    w = Worker()
    gui = threading.get_ident()
    results = []
    for i in range(3):
        w.submit(lambda i=i: (i, threading.get_ident()), lambda res: results.append((res, threading.get_ident())))
    pump_until(app, lambda: len(results) == 3)
    assert [r[0][0] for r in results] == [0, 1, 2]
    assert all(r[0][1] != gui and r[1] == gui for r in results)
    assert w.busy == 0
    w.stop()


def test_errors_are_reported_and_the_worker_keeps_going(app):
    w = Worker()
    errors, results = [], []
    w.submit(lambda: 1 / 0, None, errors.append)
    w.submit(lambda: "ok", results.append)
    pump_until(app, lambda: results)
    assert isinstance(errors[0], ZeroDivisionError)
    assert results == ["ok"]
    w.stop()


def test_gui_thread_is_not_blocked_by_a_slow_job(app):
    w = Worker()
    done = []
    w.submit(lambda: time.sleep(0.5), done.append)
    t = time.time()
    app.processEvents()
    assert time.time() - t < 0.1
    assert w.busy == 1
    pump_until(app, lambda: done)
    assert w.busy == 0
    w.stop()
