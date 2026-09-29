import random
import unittest

from fuel_planner.services.optimizer import InfeasibleRoute, plan, plan_practical

MPG = 10


def cost(p, prices):
    return p.cost(prices, MPG)


class GreedyTests(unittest.TestCase):
    def test_buys_just_enough_to_reach_cheaper_station(self):
        positions, prices = [0, 100, 300], [3.0, 2.0, 4.0]
        p = plan(positions, prices, 600, 500)
        self.assertEqual([(x.station, round(x.miles_of_fuel)) for x in p.purchases], [(0, 100), (1, 500)])
        self.assertAlmostEqual(cost(p, prices), 130.0)

    def test_fills_up_when_nothing_cheaper_ahead(self):
        positions, prices = [0, 400, 800], [2.0, 3.0, 3.0]
        p = plan(positions, prices, 1000, 500)
        self.assertEqual([(x.station, round(x.miles_of_fuel)) for x in p.purchases], [(0, 500), (1, 400), (2, 100)])
        self.assertAlmostEqual(cost(p, prices), 250.0)

    def test_full_tank_short_trip_needs_no_purchase(self):
        p = plan([100], [3.0], 400, 500, start_tank="full")
        self.assertEqual(p.purchases, [])
        self.assertEqual(cost(p, [3.0]), 0)

    def test_empty_start_values_fuel_to_first_station(self):
        prices = [3.0]
        p = plan([50], prices, 300, 500)
        self.assertEqual(p.initial_fuel_miles, 50)
        self.assertEqual(round(p.purchases[0].miles_of_fuel), 250)
        # Every mile of the 300-mile trip is paid for.
        self.assertAlmostEqual(cost(p, prices), 300 / MPG * 3.0)

    def test_gap_longer_than_range_is_infeasible(self):
        with self.assertRaises(InfeasibleRoute):
            plan([0, 600], [3.0, 3.0], 1000, 500)

    def test_no_station_at_all_is_infeasible_from_empty(self):
        with self.assertRaises(InfeasibleRoute):
            plan([], [], 100, 500)


def brute_force(positions, prices, total, rng, start_fuel, step):
    """Exact DP over integer fuel levels (in units of `step` miles)."""
    INF = float("inf")
    cap = rng // step
    pts = positions + [total]
    best = {start_fuel // step: 0.0}
    prev = 0
    for i, pos in enumerate(pts):
        dist = (pos - prev) // step
        arrive = {f - dist: c for f, c in best.items() if f >= dist}
        if i == len(positions):
            return min(arrive.values(), default=INF)
        best = {}
        for f, c in arrive.items():
            for buy in range(cap - f + 1):
                nf, nc = f + buy, c + buy * step / MPG * prices[i]
                if nc < best.get(nf, INF):
                    best[nf] = nc
        prev = pos


class GreedyMatchesBruteForce(unittest.TestCase):
    def test_random_instances(self):
        rnd = random.Random(42)
        step, rng = 10, 100
        for _ in range(300):
            n = rnd.randint(1, 8)
            positions = sorted(rnd.sample(range(0, 300, step), n))
            positions[0] = 0
            prices = [round(rnd.uniform(2.5, 4.5), 2) for _ in positions]
            total = positions[-1] + rnd.randrange(step, rng + step, step)
            try:
                p = plan(positions, prices, total, rng, start_tank="empty")
            except InfeasibleRoute:
                self.assertEqual(brute_force(positions, prices, total, rng, 0, step), float("inf"))
                continue
            self.assertAlmostEqual(cost(p, prices), brute_force(positions, prices, total, rng, 0, step), places=6)


class PracticalPlanTests(unittest.TestCase):
    def random_instance(self, rnd):
        positions = sorted(rnd.uniform(0, 1500) for _ in range(40))
        positions[0] = 0.0
        prices = [round(rnd.uniform(2.8, 4.2), 3) for _ in positions]
        return positions, prices, positions[-1] + rnd.uniform(10, 300)

    def test_zero_penalty_matches_optimal_cost(self):
        rnd = random.Random(7)
        for _ in range(50):
            positions, prices, total = self.random_instance(rnd)
            try:
                exact = plan(positions, prices, total, 500)
            except InfeasibleRoute:
                continue
            practical = plan_practical(positions, prices, total, 500, MPG)
            # 1-mile grid + one cell of slack: within a fraction of a percent.
            self.assertLessEqual(cost(practical, prices), cost(exact, prices) * 1.005)

    def test_penalty_reduces_stops_and_respects_range(self):
        rnd = random.Random(11)
        for _ in range(50):
            positions, prices, total = self.random_instance(rnd)
            try:
                exact = plan(positions, prices, total, 500)
            except InfeasibleRoute:
                continue
            practical = plan_practical(positions, prices, total, 500, MPG, stop_penalty=25)
            self.assertLessEqual(len(practical.purchases), len(exact.purchases))
            stops = [positions[p.station] for p in practical.purchases]
            legs = [b - a for a, b in zip([0.0] + stops, stops + [total])]
            self.assertTrue(all(leg <= 500 + 1e-6 for leg in legs))
            bought = sum(p.miles_of_fuel for p in practical.purchases) + practical.initial_fuel_miles
            self.assertAlmostEqual(bought, total, places=6)  # starts empty, ends empty

    def test_detour_cost_avoids_far_station(self):
        # Same price, but station 1 is 9 miles off-route: prefer the on-route one.
        positions, prices = [0, 300, 310], [3.0, 3.0, 3.0]
        p = plan_practical(positions, prices, 700, 500, MPG, stop_penalty=0, detour_miles=[0, 9, 0])
        self.assertNotIn(1, [x.station for x in p.purchases])
