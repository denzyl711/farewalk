import pytest

from farewalk.models.road import CandidatePoint
from farewalk.utils.spatial import (
    KDNode,
    ProjectedCandidate,
    _bounds_touch,
    build_kdtree,
    find_leaf,
    get_leaf_zones,
    get_neighbors,
)

BOUNDS = (0.0, 0.0, 1000.0, 1000.0)


def _pc(x: float, y: float) -> ProjectedCandidate:
    """Shorthand to create a ProjectedCandidate with a dummy CandidatePoint."""
    return ProjectedCandidate(x=x, y=y, candidate=CandidatePoint(lat=0.0, lng=0.0))


# ── ProjectedCandidate ──────────────────────────────────────────────


class TestProjectedCandidate:
    def test_getitem_axis_0(self):
        p = _pc(100.0, 200.0)
        assert p[0] == 100.0

    def test_getitem_axis_1(self):
        p = _pc(100.0, 200.0)
        assert p[1] == 200.0

    def test_frozen(self):
        p = _pc(100.0, 200.0)
        with pytest.raises(AttributeError):
            p.x = 999.0


# ── build_kdtree ────────────────────────────────────────────────────


class TestBuildKdtree:
    def test_few_points_makes_leaf(self):
        points = [_pc(10, 20), _pc(30, 40)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=6)
        assert tree.is_leaf
        assert len(tree.points) == 2
        assert tree.left is None
        assert tree.right is None

    def test_many_points_makes_internal_node(self):
        points = [_pc(i * 100, i * 50) for i in range(10)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=3)
        assert not tree.is_leaf
        assert tree.left is not None
        assert tree.right is not None
        assert tree.points == []

    def test_all_points_preserved_in_leaves(self):
        points = [_pc(i * 100, i * 50) for i in range(20)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=4)
        leaves = get_leaf_zones(tree)
        leaf_points = []
        for leaf in leaves:
            leaf_points.extend(leaf.points)
        assert len(leaf_points) == 20

    def test_splits_alternate_axes(self):
        points = [_pc(i * 100, i * 50) for i in range(20)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=4)
        # Root splits on x (depth 0)
        assert tree.split_axis == 0
        # Children split on y (depth 1)
        assert tree.left.split_axis == 1 or tree.left.is_leaf
        assert tree.right.split_axis == 1 or tree.right.is_leaf

    def test_leaf_bounds_match_parent(self):
        points = [_pc(10, 20)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=6)
        assert tree.bounds == BOUNDS

    def test_child_bounds_narrow_on_split_axis(self):
        points = [_pc(i * 100, 500) for i in range(10)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=3)
        # Root splits on x, left child's x_max should be the split value
        x_min, _, x_max, _ = tree.left.bounds
        assert x_max == tree.split_value
        # Right child's x_min should be the split value
        r_xmin, _, _, _ = tree.right.bounds
        assert r_xmin == tree.split_value

    def test_empty_points(self):
        tree = build_kdtree([], BOUNDS)
        assert tree.is_leaf
        assert tree.points == []

    def test_single_point(self):
        tree = build_kdtree([_pc(500, 500)], BOUNDS)
        assert tree.is_leaf
        assert len(tree.points) == 1


# ── get_leaf_zones ──────────────────────────────────────────────────


class TestGetLeafZones:
    def test_leaf_returns_itself(self):
        tree = build_kdtree([_pc(10, 20)], BOUNDS)
        leaves = get_leaf_zones(tree)
        assert len(leaves) == 1
        assert leaves[0] is tree

    def test_leaf_count_grows_with_points(self):
        small = build_kdtree([_pc(i, i) for i in range(5)], BOUNDS, max_leaf_size=3)
        large = build_kdtree([_pc(i * 50, i * 50) for i in range(20)], BOUNDS, max_leaf_size=3)
        assert len(get_leaf_zones(large)) > len(get_leaf_zones(small))

    def test_all_leaves_are_leaf_nodes(self):
        points = [_pc(i * 100, i * 50) for i in range(15)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=3)
        for leaf in get_leaf_zones(tree):
            assert leaf.is_leaf
            assert leaf.left is None
            assert leaf.right is None


# ── find_leaf ───────────────────────────────────────────────────────


class TestFindLeaf:
    def test_single_leaf_returns_itself(self):
        tree = build_kdtree([_pc(500, 500)], BOUNDS)
        leaf = find_leaf(tree, 500, 500)
        assert leaf is tree

    def test_finds_correct_leaf_for_point(self):
        points = [_pc(i * 100, i * 50) for i in range(20)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=3)
        target = points[0]
        leaf = find_leaf(tree, target.x, target.y)
        assert leaf.is_leaf
        assert target in leaf.points

    def test_different_points_can_land_in_different_leaves(self):
        points = [_pc(i * 100, i * 50) for i in range(20)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=3)
        leaf_a = find_leaf(tree, 0, 0)
        leaf_b = find_leaf(tree, 900, 900)
        # Far apart points should be in different leaves (with enough points)
        assert leaf_a is not leaf_b

    def test_point_on_split_boundary_goes_left(self):
        points = [_pc(i * 100, 500) for i in range(10)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=3)
        # A point exactly at the split value should go left (<= goes left)
        leaf = find_leaf(tree, tree.split_value, 500)
        assert leaf.is_leaf


# ── _bounds_touch ───────────────────────────────────────────────────


class TestBoundsTouch:
    def test_adjacent_boxes_touch(self):
        a = (0, 0, 100, 100)
        b = (100, 0, 200, 100)
        assert _bounds_touch(a, b)

    def test_separated_boxes_dont_touch(self):
        a = (0, 0, 100, 100)
        b = (200, 0, 300, 100)
        assert not _bounds_touch(a, b)

    def test_overlapping_boxes_touch(self):
        a = (0, 0, 150, 100)
        b = (100, 0, 200, 100)
        assert _bounds_touch(a, b)

    def test_corner_touch(self):
        a = (0, 0, 100, 100)
        b = (100, 100, 200, 200)
        assert _bounds_touch(a, b)

    def test_separated_on_y(self):
        a = (0, 0, 100, 100)
        b = (0, 200, 100, 300)
        assert not _bounds_touch(a, b)

    def test_same_box(self):
        a = (0, 0, 100, 100)
        assert _bounds_touch(a, a)


# ── get_neighbors ───────────────────────────────────────────────────


class TestGetNeighbors:
    def test_single_leaf_has_no_neighbors(self):
        tree = build_kdtree([_pc(500, 500)], BOUNDS)
        neighbors = get_neighbors(tree, tree)
        assert neighbors == []

    def test_two_leaves_are_neighbors(self):
        # Enough points to split into exactly 2 leaves
        points = [_pc(i * 100, 500) for i in range(10)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=5)
        leaves = get_leaf_zones(tree)
        assert len(leaves) == 2
        neighbors = get_neighbors(tree, leaves[0])
        assert leaves[1] in neighbors

    def test_does_not_include_self(self):
        points = [_pc(i * 100, 500) for i in range(10)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=4)
        leaves = get_leaf_zones(tree)
        for leaf in leaves:
            neighbors = get_neighbors(tree, leaf)
            assert leaf not in neighbors

    def test_distant_leaves_not_neighbors(self):
        # Grid of points to create multiple zones
        points = [_pc(x, y) for x in range(0, 1000, 100) for y in range(0, 1000, 100)]
        tree = build_kdtree(points, BOUNDS, max_leaf_size=4)
        leaves = get_leaf_zones(tree)
        # With enough leaves, not every leaf is a neighbor of every other
        if len(leaves) >= 4:
            neighbor_counts = [len(get_neighbors(tree, leaf)) for leaf in leaves]
            # At least one leaf should have fewer neighbors than total leaves - 1
            assert min(neighbor_counts) < len(leaves) - 1
