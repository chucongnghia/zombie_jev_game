"""Small cached visibility graph over wall corners (no grid or external pathfinder).

Persistent corner waypoints prevent stateless local steering oscillating on a
wall face. Straight-line pursuit remains the fast path for almost all frames.
"""
import heapq
import pygame
from game import config as C
from game.systems.collision import is_free


class ObstacleNavigator:
    def __init__(self):
        self.signature = None
        self.nodes: list[pygame.Vector2] = []
        self.edges: list[list[tuple[int, float]]] = []
        self.expanded = []
        self.routes: dict[object, tuple[pygame.Vector2, list[pygame.Vector2]]] = {}

    def visible(self, start, end) -> bool:
        return not any(wall.clipline(tuple(start), tuple(end)) for wall in self.expanded)

    def prepare(self, walls, radius):
        signature = (radius, tuple(tuple(wall) for wall in walls))
        if signature == self.signature:
            return
        self.signature = signature
        self.routes.clear()
        self.expanded = [wall.inflate(2 * (radius + 2), 2 * (radius + 2)) for wall in walls]
        self.nodes = []
        for wall in self.expanded:
            for x, y in [(wall.left - 2, wall.top - 2), (wall.right + 2, wall.top - 2),
                         (wall.left - 2, wall.bottom + 2), (wall.right + 2, wall.bottom + 2)]:
                pos = pygame.Vector2(x, y)
                if is_free(pos, radius + 2, walls):
                    self.nodes.append(pos)
        self.edges = [[] for _ in self.nodes]
        for i, a in enumerate(self.nodes):
            for j in range(i):
                b = self.nodes[j]
                if self.visible(a, b):
                    distance = a.distance_to(b)
                    self.edges[i].append((j, distance))
                    self.edges[j].append((i, distance))

    def plan(self, start, goal):
        nodes = self.nodes + [start, goal]
        start_id, goal_id = len(nodes) - 2, len(nodes) - 1
        edges = [list(edge) for edge in self.edges] + [[], []]
        for special in (start_id, goal_id):
            for i in range(len(self.nodes)):
                if self.visible(nodes[special], nodes[i]):
                    distance = nodes[special].distance_to(nodes[i])
                    edges[special].append((i, distance))
                    edges[i].append((special, distance))
        queue = [(0.0, start_id)]
        costs, parent = {start_id: 0.0}, {}
        while queue:
            cost, current = heapq.heappop(queue)
            if current == goal_id:
                route = []
                while current != start_id:
                    route.append(nodes[current].copy())
                    current = parent[current]
                return list(reversed(route))
            if cost > costs[current]:
                continue
            for neighbor, distance in edges[current]:
                candidate = cost + distance
                if candidate < costs.get(neighbor, float("inf")):
                    costs[neighbor], parent[neighbor] = candidate, current
                    heapq.heappush(queue, (candidate, neighbor))
        return []

    def direction(self, key, start, goal, walls, radius):
        self.prepare(walls, radius)
        if self.visible(start, goal):
            self.routes.pop(key, None)
            return goal - start
        previous = self.routes.get(key)
        if previous is None or previous[0].distance_to(goal) > 50:
            route = self.plan(start, goal)
            self.routes[key] = (goal.copy(), route)
        else:
            route = previous[1]
        while route and start.distance_to(route[0]) < 5:
            route.pop(0)
        # Do not discard a corner early: doing so cuts across an inflated wall.
        return route[0] - start if route else goal - start
