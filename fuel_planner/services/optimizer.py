"""Cheapest refuelling plan along a fixed route (the classic "gas station problem").

Stations are points at known mile markers with known prices; the tank holds
`range_miles` worth of fuel. The greedy below is optimal for this problem
(fuel cost is linear, capacity fixed):

  At each station, look ahead within one full tank:
    * if a cheaper station is reachable, buy only enough to get there;
    * else if the destination is reachable, buy only enough to finish;
    * else fill up here and continue to the cheapest reachable station.

Fuel is tracked in "miles of range"; gallons = miles / mpg.
"""
from dataclasses import dataclass, field

EPS = 1e-9


class InfeasibleRoute(ValueError):
    """A stretch of the route longer than one tank has no station."""

    def __init__(self, at_mile: float, gap_miles: float | None = None):
        self.at_mile = at_mile
        self.gap_miles = gap_miles
        super().__init__(
            f"No reachable fuel station after mile {at_mile:.0f}"
            + (f" (next gap is {gap_miles:.0f} mi)" if gap_miles else "")
        )


@dataclass
class Purchase:
    station: int  # index into the input arrays
    miles_of_fuel: float


@dataclass
class FuelPlan:
    purchases: list[Purchase] = field(default_factory=list)
    initial_fuel_miles: float = 0.0  # fuel in the tank at the origin
    initial_fuel_billed_station: int | None = None  # station whose price the initial fuel is valued at

    def cost(self, prices, mpg) -> float:
        total = sum(p.miles_of_fuel / mpg * prices[p.station] for p in self.purchases)
        if self.initial_fuel_billed_station is not None:
            total += self.initial_fuel_miles / mpg * prices[self.initial_fuel_billed_station]
        return total


def plan(positions, prices, total_miles, range_miles, start_tank="empty") -> FuelPlan:
    """Plan purchases. `positions` must be sorted ascending (mile markers along the route).

    start_tank:
      "full"  - leave with a full tank; that fuel is not charged.
      "empty" - leave with just enough fuel to reach the first station on the
                route; it is valued at that station's price so the reported
                cost covers every mile of the trip.
    """
    n = len(positions)
    if any(positions[i] > positions[i + 1] for i in range(n - 1)):
        raise ValueError("positions must be sorted")

    result = FuelPlan()
    if start_tank == "full":
        fuel = range_miles
    elif start_tank == "empty":
        if n == 0 or positions[0] >= total_miles:
            raise InfeasibleRoute(0.0)
        if positions[0] > range_miles + EPS:
            raise InfeasibleRoute(0.0, positions[0])
        fuel = positions[0]
        result.initial_fuel_miles = positions[0]
        result.initial_fuel_billed_station = 0
    else:
        raise ValueError("start_tank must be 'full' or 'empty'")

    cur, pos, price, can_buy = -1, 0.0, float("inf"), False  # at the origin, nothing to buy

    while True:
        limit = pos + (range_miles if can_buy else fuel)
        j = cur + 1
        reachable = []
        while j < n and positions[j] <= limit + EPS and positions[j] < total_miles:
            reachable.append(j)
            j += 1

        cheaper = next((k for k in reachable if prices[k] < price), None)
        if cheaper is not None:
            need = positions[cheaper] - pos
            if can_buy and fuel + EPS < need:
                result.purchases.append(Purchase(cur, need - fuel))
                fuel = need
        elif total_miles <= limit + EPS:
            need = total_miles - pos
            if can_buy and fuel + EPS < need:
                result.purchases.append(Purchase(cur, need - fuel))
            return result
        elif not reachable:
            nxt = (min(positions[j], total_miles) if j < n else total_miles) - pos
            raise InfeasibleRoute(pos, nxt)
        else:
            if can_buy and range_miles - fuel > EPS:
                result.purchases.append(Purchase(cur, range_miles - fuel))
                fuel = range_miles
            # cheapest reachable; ties -> the farthest one
            cheaper = min(reachable, key=lambda k: (prices[k], -positions[k]))

        fuel -= positions[cheaper] - pos
        cur, pos, price, can_buy = cheaper, positions[cheaper], prices[cheaper], True


def plan_practical(positions, prices, total_miles, range_miles, mpg, start_tank="empty",
                   stop_penalty=0.0, detour_miles=None, resolution_miles=1.0) -> FuelPlan:
    """Cheapest plan when every stop also has a fixed cost.

    Pure price-greedy happily makes a stop to save a cent on a gallon. Here each
    stop costs `stop_penalty` dollars (driver time) plus the fuel burned on the
    round-trip detour to the station, so the plan only stops when it pays off.

    Exact DP over (station, fuel level) on a `resolution_miles` grid. The buy
    step is O(F) per station via a prefix minimum:
        after[f'] = min(arrive[f'], penalty + c*f' + min_{f<=f'}(arrive[f] - c*f))
    The chosen stop set is then handed to `plan` (exact, continuous) to size
    each purchase precisely.
    """
    import numpy as np

    n = len(positions)
    if n == 0:
        return plan(positions, prices, total_miles, range_miles, start_tank)
    detour_miles = detour_miles if detour_miles is not None else [0.0] * n
    r = resolution_miles
    cap = int(range_miles // r) - 1  # one cell of slack absorbs grid rounding
    grid = np.rint(np.asarray(positions) / r).astype(int)
    dest = int(np.ceil(total_miles / r))
    per_cell = np.asarray(prices) * r / mpg  # $ per grid cell of fuel
    fixed = stop_penalty + 2 * np.asarray(detour_miles) / mpg * np.asarray(prices)

    inf = np.inf
    levels = np.arange(cap + 1)
    arrive = np.full(cap + 1, inf)
    if start_tank == "empty":
        arrive[0] = 0.0
    else:
        left = cap - grid[0]
        if left < 0:
            raise InfeasibleRoute(0.0, positions[0])
        arrive[left] = 0.0

    came_from = np.empty((n, cap + 1), dtype=np.int32)  # fuel level on arrival, per after-buy level
    for i in range(n):
        shifted = arrive - per_cell[i] * levels
        run_min = np.minimum.accumulate(shifted)
        run_arg = _running_argmin(shifted)
        bought = fixed[i] + per_cell[i] * levels + run_min
        use_buy = bought < arrive
        after = np.where(use_buy, bought, arrive)
        came_from[i] = np.where(use_buy, run_arg, levels)
        if i + 1 < n:
            d = grid[i + 1] - grid[i]
            arrive = np.full(cap + 1, inf)
            if d <= cap:
                arrive[: cap + 1 - d] = after[d:]
            if not np.isfinite(arrive).any():
                raise InfeasibleRoute(positions[i], positions[i + 1] - positions[i])

    need = dest - grid[-1]
    if need > cap or not np.isfinite(after[max(need, 0):]).any():
        raise InfeasibleRoute(positions[-1], total_miles - positions[-1])
    f = max(need, 0) + int(np.argmin(after[max(need, 0):]))

    stops = []
    for i in range(n - 1, -1, -1):
        arrived = int(came_from[i][f])
        if arrived != f:
            stops.append(i)
        if i:
            f = arrived + (grid[i] - grid[i - 1])
    stops.reverse()
    if start_tank == "empty" and (not stops or stops[0] != 0):
        stops.insert(0, 0)

    sub = plan([positions[i] for i in stops], [prices[i] for i in stops], total_miles, range_miles, start_tank)
    return FuelPlan(
        purchases=[Purchase(stops[p.station], p.miles_of_fuel) for p in sub.purchases],
        initial_fuel_miles=sub.initial_fuel_miles,
        initial_fuel_billed_station=None if sub.initial_fuel_billed_station is None else stops[0],
    )


def _running_argmin(a):
    """Index of the running minimum of `a` (first occurrence)."""
    import numpy as np

    idx = np.arange(len(a))
    is_new_min = np.concatenate(([True], a[1:] < np.minimum.accumulate(a)[:-1]))
    return np.maximum.accumulate(np.where(is_new_min, idx, 0))
