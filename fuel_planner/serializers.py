from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=200, help_text="'City, ST', 'lat,lon' or a US street address, e.g. 'Dallas, TX'."
    )
    finish = serializers.CharField(max_length=200, help_text="Same formats as `start`.")
    max_detour_miles = serializers.FloatField(
        required=False, min_value=0.5, max_value=50,
        help_text="How far from the route a station may be (default 10).",
    )
    stop_penalty_usd = serializers.FloatField(
        required=False, min_value=0, max_value=500,
        help_text="Fixed cost per stop used when choosing stops (default 10). 0 = cheapest fuel regardless of stop count.",
    )
    start_tank = serializers.ChoiceField(
        choices=["empty", "full"], default="empty",
        help_text="'empty' (default): cost covers the whole trip. 'full': leave with a free full tank.",
    )
