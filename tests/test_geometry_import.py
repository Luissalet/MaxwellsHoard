"""Independent geometric counterexamples to three-section plate detection."""
import struct

import numpy as np
import pytest

from maxwell.geometry_import import profile_from_stl
from maxwell.model import ProblemError


def box(low, high):
    v = np.array([[x, y, z] for x in (low[0], high[0])
                  for y in (low[1], high[1]) for z in (low[2], high[2])], float)
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5),
             (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6),
             (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    return v[np.array(faces)]


def binary(tris):
    return bytes(80) + struct.pack('<I', len(tris)) + b''.join(
        bytes(12) + t.astype('<f4').tobytes() + bytes(2) for t in tris)


@pytest.mark.parametrize('axis', range(3))
def test_shallow_blind_pocket_between_old_sampling_planes_is_refused(axis):
    # Five boxes form an open tray, bottom 1 mm, sides to 10 mm.
    # Old sections z=2,5,8 mm all see identical walls and miss the floor.
    tray = np.concatenate([box((0, 0, 0), (60, 40, 1)),
                           box((0, 0, 1), (2, 40, 10)),
                           box((58, 0, 1), (60, 40, 10)),
                           box((2, 0, 1), (58, 2, 10)),
                           box((2, 38, 1), (58, 40, 10))])
    tray = np.roll(tray, axis, axis=2)
    with pytest.raises(ProblemError, match='constant-thickness'):
        profile_from_stl(binary(tray), resolution_mm=2, thin_axis='zxy'[axis])


def test_tapered_wall_cannot_be_accepted_by_coarse_sections():
    prism = box((0, 0, 0), (60, 40, 10))
    # Slope is smaller than a sampling cell but is real variable geometry.
    prism[:, :, 0] += prism[:, :, 2] * 0.01
    with pytest.raises(ProblemError, match='constant-thickness'):
        profile_from_stl(binary(prism), resolution_mm=10, thin_axis='z')


@pytest.mark.parametrize('axis', range(3))
def test_true_extruded_plate_is_kept_in_each_orientation(axis):
    plate = np.roll(box((0, 0, 0), (60, 40, 5)), axis, axis=2)
    result = profile_from_stl(binary(plate), resolution_mm=2, thin_axis='zxy'[axis])
    assert result['report']['volume_difference'] < 1e-12
    assert result['profile']['thickness'] == 0.005


@pytest.mark.parametrize('resolution', [0, -1, float('nan'), float('inf')])
def test_resolution_must_be_finite_positive(resolution):
    with pytest.raises(ProblemError):
        profile_from_stl(binary(box((0, 0, 0), (60, 40, 5))), resolution_mm=resolution)


def test_nonfinite_vertices_are_refused():
    tris = box((0, 0, 0), (60, 40, 5))
    tris[0, 0, 0] = float('nan')
    with pytest.raises(ProblemError, match='finite'):
        profile_from_stl(binary(tris))


def test_invalid_axis_is_a_domain_error():
    with pytest.raises(ProblemError):
        profile_from_stl(binary(box((0, 0, 0), (60, 40, 5))), thin_axis='q')
