from __future__ import annotations
from dataclasses import dataclass
from farewalk.models.road import CandidatePoint


@dataclass(frozen=True)
class ProjectedCandidate:
    x: float
    y: float
    candidate: CandidatePoint

    def __getitem__(self, axis: int) -> float:
        return self.x if axis == 0 else self.y

@dataclass
class KDNode:
    split_axis: int | None
    split_value: float | None
    bounds: tuple[float, float, float, float]
    left: KDNode | None
    right: KDNode | None
    points: list[ProjectedCandidate]
    is_leaf: bool


def build_kdtree(
    points: list[ProjectedCandidate],
    bounds: tuple[float, float, float, float],
    depth: int = 0,
    max_leaf_size: int = 6,
) -> KDNode:
    if len(points) <= max_leaf_size:
        return KDNode(
            split_axis=None,
            split_value=None,
            bounds=bounds,
            left=None,
            right=None,
            points=points,
            is_leaf=True,
        )

    axis = depth % 2
    sorted_points = sorted(points, key=lambda p: p[axis])
    mid = len(sorted_points) // 2
    split_value = sorted_points[mid][axis]

    left_points = sorted_points[:mid]
    right_points = sorted_points[mid:]

    x_min, y_min, x_max, y_max = bounds
    if axis == 0:
        left_bounds = (x_min, y_min, split_value, y_max)
        right_bounds = (split_value, y_min, x_max, y_max)
    else:
        left_bounds = (x_min, y_min, x_max, split_value)
        right_bounds = (x_min, split_value, x_max, y_max)

    return KDNode(
        split_axis=axis,
        split_value=split_value,
        bounds=bounds,
        left=build_kdtree(left_points, left_bounds, depth + 1, max_leaf_size),
        right=build_kdtree(right_points, right_bounds, depth + 1, max_leaf_size),
        points=[],
        is_leaf=False,
    )

# ── Querying ─────────────────────────────────────────────────────────
def get_leaf_zones(node: KDNode) -> list[KDNode]:
    if node.is_leaf:
        return [node]
    return get_leaf_zones(node.left) + get_leaf_zones(node.right)

def find_leaf(node: KDNode, x: float, y: float) -> KDNode:
    if node.is_leaf:
        return node
    value = x if node.split_axis == 0 else y
    if value <= node.split_value:
        return find_leaf(node.left, x, y)
    return find_leaf(node.right, x, y)

def _bounds_touch(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    """Check if two bounding boxes share a boundary (edge or corner).

    Two boxes are neighbors if they are not separated on either axis.
    "Not separated" means one's min is <= the other's max AND vice versa.
    """
    a_xmin, a_ymin, a_xmax, a_ymax = a
    b_xmin, b_ymin, b_xmax, b_ymax = b

    # Two boxes touch unless there's a gap between them on either axis.
    # A gap on x means one box is entirely left of the other (a_xmax < b_xmin).
    # No gap on both axes → they share a boundary (edge or corner).
    separated_x = a_xmax < b_xmin or b_xmax < a_xmin
    separated_y = a_ymax < b_ymin or b_ymax < a_ymin
    return not separated_x and not separated_y


def get_neighbors(root: KDNode, target_leaf: KDNode) -> list[KDNode]:
    """Find all leaf zones adjacent to target_leaf.

    Walks the full tree, collects every leaf whose bounds touch
    target_leaf's bounds (excluding target_leaf itself).
    """
    neighbors = []
    for leaf in get_leaf_zones(root):
        if leaf is target_leaf:
            continue
        if _bounds_touch(leaf.bounds, target_leaf.bounds):
            neighbors.append(leaf)
    return neighbors

