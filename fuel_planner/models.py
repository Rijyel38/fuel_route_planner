from django.db import models


class FuelStation(models.Model):
    """A truck stop from the OPIS price file, geocoded to its city centroid.

    The source file lists several prices per station (different racks/products);
    `retail_price` is the cheapest of them, the others are summarised in
    `price_count` / `max_price` for transparency.
    """

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.PositiveIntegerField(null=True, blank=True)
    retail_price = models.DecimalField(max_digits=8, decimal_places=5)
    max_price = models.DecimalField(max_digits=8, decimal_places=5)
    price_count = models.PositiveSmallIntegerField(default=1)
    latitude = models.FloatField()
    longitude = models.FloatField()
    geocode_source = models.CharField(max_length=20)

    class Meta:
        ordering = ["opis_id"]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state}) ${self.retail_price}"
