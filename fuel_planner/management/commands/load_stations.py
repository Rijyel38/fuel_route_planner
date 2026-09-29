import csv
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from fuel_planner.models import FuelStation


class Command(BaseCommand):
    help = "Load data/stations_geocoded.csv into the database (idempotent: replaces all rows)."

    @transaction.atomic
    def handle(self, *args, **opts):
        with open(settings.STATIONS_CSV, encoding="utf-8") as fh:
            objs = [
                FuelStation(
                    opis_id=int(r["opis_id"]), name=r["name"], address=r["address"], city=r["city"],
                    state=r["state"], rack_id=int(r["rack_id"]) if r["rack_id"] else None,
                    retail_price=Decimal(r["retail_price"]), max_price=Decimal(r["max_price"]),
                    price_count=int(r["price_count"]), latitude=float(r["latitude"]),
                    longitude=float(r["longitude"]), geocode_source=r["geocode_source"],
                )
                for r in csv.DictReader(fh)
            ]
        FuelStation.objects.all().delete()
        FuelStation.objects.bulk_create(objs, batch_size=1000)
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(objs)} fuel stations."))
