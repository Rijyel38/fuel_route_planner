from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RouteRequestSerializer
from .services.planner import PlanningError, plan_trip, to_geojson


def _plan_from(params):
    """Validate input and plan; returns (plan, query_dict) or raises PlanningError."""
    ser = RouteRequestSerializer(data=params)
    if not ser.is_valid():
        raise PlanningError(ser.errors)
    data = ser.validated_data
    plan = plan_trip(data["start"], data["finish"], data.get("max_detour_miles"), data["start_tank"],
                     data.get("stop_penalty_usd"))
    query = {k: v for k, v in data.items() if v is not None}
    return plan, query


class RoutePlanView(APIView):
    """Plan the cheapest fuel stops between two US locations.

    GET  /api/route/?start=New York, NY&finish=Los Angeles, CA
    POST /api/route/  {"start": "...", "finish": "...", "max_detour_miles": 10, "stop_penalty_usd": 10, "start_tank": "empty"}
    """

    def get(self, request):
        return self._handle(request, request.query_params)

    def post(self, request):
        return self._handle(request, request.data)

    def _handle(self, request, params):
        try:
            plan, query = _plan_from(params)
        except PlanningError as exc:
            detail = exc.args[0]
            return Response({"error": detail}, status=exc.status)
        qs = urlencode(query)
        plan["map"] = {
            "html_url": request.build_absolute_uri(f"{reverse('route-map')}?{qs}"),
            "geojson_url": request.build_absolute_uri(f"{reverse('route-geojson')}?{qs}"),
        }
        return Response(plan)


class RouteGeoJSONView(APIView):
    """The same plan as a GeoJSON FeatureCollection (route line + stop points)."""

    def get(self, request):
        try:
            plan, _ = _plan_from(request.query_params)
        except PlanningError as exc:
            return Response({"error": exc.args[0]}, status=exc.status)
        return Response(to_geojson(plan))


def route_map(request):
    """Interactive Leaflet map of the plan. With no query it shows an input form."""
    ctx = {"start": request.GET.get("start", ""), "finish": request.GET.get("finish", "")}
    if ctx["start"] and ctx["finish"]:
        try:
            plan, _ = _plan_from(request.GET)
            ctx["plan"] = plan
            ctx["geojson"] = to_geojson(plan)
        except PlanningError as exc:
            ctx["error"] = exc.args[0]
    return render(request, "fuel_planner/map.html", ctx, status=400 if "error" in ctx else 200)
