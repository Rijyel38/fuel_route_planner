import sys
import threading

from django.apps import AppConfig


class RoutingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fuel_planner"

    def ready(self):
        # Load the gazetteer and station index in the background when serving,
        # so even the first request only pays for the routing call.
        serving = any(cmd in sys.argv for cmd in ("runserver", "gunicorn", "uwsgi")) or "wsgi" in sys.argv[0]
        if serving:
            threading.Thread(target=_warm, daemon=True).start()


def _warm():
    from .services import gazetteer, stations

    gazetteer.warm()
    try:
        stations.get_index()
    except Exception:  # e.g. stations not loaded yet; the request will report it
        pass
