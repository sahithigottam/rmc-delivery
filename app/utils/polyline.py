"""Distance from a GPS fix to an encoded Google route."""
import math


def distance_to_route_metres(lat: float, lng: float, encoded: str) -> float:
    points = []
    index = latitude = longitude = 0
    while index < len(encoded):
        delta = []
        for _ in range(2):
            result = shift = 0
            while True:
                if index >= len(encoded) or shift > 30:
                    raise ValueError("Invalid encoded route polyline")
                value = ord(encoded[index]) - 63
                index += 1
                if not 0 <= value <= 63:
                    raise ValueError("Invalid encoded route polyline")
                result |= (value & 31) << shift
                shift += 5
                if value < 32:
                    break
            delta.append(~(result >> 1) if result & 1 else result >> 1)
        latitude += delta[0]
        longitude += delta[1]
        point = (latitude / 100000, longitude / 100000)
        if not -90 <= point[0] <= 90 or not -180 <= point[1] <= 180:
            raise ValueError("Invalid route coordinates")
        points.append(point)
    if len(points) < 2:
        raise ValueError("Route polyline requires at least two points")

    radius = 6371000
    scale = math.cos(math.radians(lat))

    def project(point):
        longitude_delta = (point[1] - lng + 180) % 360 - 180
        return (radius * math.radians(longitude_delta) * scale,
                radius * math.radians(point[0] - lat))

    best = math.inf
    for start, end in zip(points, points[1:]):
        ax, ay = project(start)
        bx, by = project(end)
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        fraction = max(0, min(1, -(ax * dx + ay * dy) / length_squared)) if length_squared else 0
        best = min(best, math.hypot(ax + fraction * dx, ay + fraction * dy))
    return best
