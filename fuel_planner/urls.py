from django.urls import path

from . import views

urlpatterns = [
    path("route/", views.RoutePlanView.as_view(), name="route-plan"),
    path("route/geojson/", views.RouteGeoJSONView.as_view(), name="route-geojson"),
    path("route/map/", views.route_map, name="route-map"),
]
