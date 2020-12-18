# -*- coding: utf-8 -*-
import copy
import itertools
import logging
import math
from collections import defaultdict
from fractions import Fraction
from math import cos, sin

import numpy as np
import spglib
from pymatgen.core.lattice import Lattice
from pymatgen.core.operations import SymmOp
from pymatgen.core.structure import Molecule, PeriodicSite, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from pymatgen.symmetry.structure import SymmetrizedStructure
from pymatgen.util.coord import find_in_coord_list, pbc_diff


class MySpacegroupAnalyzer(SpacegroupAnalyzer):
    def get_conventional_standard_structure(self, international_monoclinic=True):
        """
        Gives a structure with a conventional cell according to certain
        standards. The standards are defined in Setyawan, W., & Curtarolo,
        S. (2010). High-throughput electronic band structure calculations:
        Challenges and tools. Computational Materials Science,
        49(2), 299-312. doi:10.1016/j.commatsci.2010.05.010
        They basically enforce as much as possible
        norm(a1)<norm(a2)<norm(a3)
        Returns:
            The structure in a conventional standardized cell
        """
        tol = 1e-5
        struct = self.get_refined_structure()
        latt = struct.lattice
        latt_type = self.get_lattice_type()
        sorted_lengths = sorted(latt.abc)
        sorted_dic = sorted(
            [
                {"vec": latt.matrix[i], "length": latt.abc[i], "orig_index": i}
                for i in [0, 1, 2]
            ],
            key=lambda k: k["length"],
        )

        if latt_type in ("orthorhombic", "cubic"):
            # you want to keep the c axis where it is
            # to keep the C- settings
            transf = np.zeros(shape=(3, 3))
            if self.get_space_group_symbol().startswith("C"):
                transf[2] = [0, 0, 1]
                a, b = sorted(latt.abc[:2])
                sorted_dic = sorted(
                    [
                        {"vec": latt.matrix[i], "length": latt.abc[i], "orig_index": i}
                        for i in [0, 1]
                    ],
                    key=lambda k: k["length"],
                )
                for i in range(2):
                    transf[i][sorted_dic[i]["orig_index"]] = 1
                c = latt.abc[2]
            elif self.get_space_group_symbol().startswith(
                "A"
            ):  # change to C-centering to match Setyawan/Curtarolo convention
                transf[2] = [1, 0, 0]
                a, b = sorted(latt.abc[1:])
                sorted_dic = sorted(
                    [
                        {"vec": latt.matrix[i], "length": latt.abc[i], "orig_index": i}
                        for i in [1, 2]
                    ],
                    key=lambda k: k["length"],
                )
                for i in range(2):
                    transf[i][sorted_dic[i]["orig_index"]] = 1
                c = latt.abc[0]
            else:
                for i, d in enumerate(sorted_dic):
                    transf[i][d["orig_index"]] = 1
                a, b, c = sorted_lengths
            latt = Lattice.orthorhombic(a, b, c)

        elif latt_type == "tetragonal":
            # find the "a" vectors
            # it is basically the vector repeated two times
            transf = np.zeros(shape=(3, 3))
            a, b, c = sorted_lengths
            for i, d in enumerate(sorted_dic):
                transf[i][d["orig_index"]] = 1

            if abs(b - c) < tol < abs(a - c):
                a, c = c, a
                transf = np.dot([[0, 0, 1], [0, 1, 0], [1, 0, 0]], transf)
            latt = Lattice.tetragonal(a, c)
        elif latt_type in ("hexagonal", "rhombohedral"):
            # for the conventional cell representation,
            # we allways show the rhombohedral lattices as hexagonal

            # check first if we have the refined structure shows a rhombohedral
            # cell
            # if so, make a supercell
            a, b, c = latt.abc
            if np.all(np.abs([a - b, c - b, a - c]) < 0.001):
                struct.make_supercell(((1, -1, 0), (0, 1, -1), (1, 1, 1)))
                a, b, c = sorted(struct.lattice.abc)

            if abs(b - c) < 0.001:
                a, c = c, a
            new_matrix = [
                [a / 2, -a * math.sqrt(3) / 2, 0],
                [a / 2, a * math.sqrt(3) / 2, 0],
                [0, 0, c],
            ]
            latt = Lattice(new_matrix)
            transf = np.eye(3, 3)

        elif latt_type == "monoclinic":
            # You want to keep the c axis where it is to keep the C- settings

            if self.get_space_group_operations().int_symbol.startswith("C"):
                transf = np.zeros(shape=(3, 3))
                transf[2] = [0, 0, 1]
                sorted_dic = sorted(
                    [
                        {"vec": latt.matrix[i], "length": latt.abc[i], "orig_index": i}
                        for i in [0, 1]
                    ],
                    key=lambda k: k["length"],
                )
                a = sorted_dic[0]["length"]
                b = sorted_dic[1]["length"]
                c = latt.abc[2]
                new_matrix = None
                for t in itertools.permutations(list(range(2)), 2):
                    m = latt.matrix
                    latt2 = Lattice([m[t[0]], m[t[1]], m[2]])
                    lengths = latt2.lengths
                    angles = latt2.angles
                    if angles[0] > 90:
                        # if the angle is > 90 we invert a and b to get
                        # an angle < 90
                        a, b, c, alpha, beta, gamma = Lattice(
                            [-m[t[0]], -m[t[1]], m[2]]
                        ).parameters
                        transf = np.zeros(shape=(3, 3))
                        transf[0][t[0]] = -1
                        transf[1][t[1]] = -1
                        transf[2][2] = 1
                        alpha = math.pi * alpha / 180
                        new_matrix = [
                            [a, 0, 0],
                            [0, b, 0],
                            [0, c * cos(alpha), c * sin(alpha)],
                        ]
                        continue

                    if angles[0] < 90:
                        transf = np.zeros(shape=(3, 3))
                        transf[0][t[0]] = 1
                        transf[1][t[1]] = 1
                        transf[2][2] = 1
                        a, b, c = lengths
                        alpha = math.pi * angles[0] / 180
                        new_matrix = [
                            [a, 0, 0],
                            [0, b, 0],
                            [0, c * cos(alpha), c * sin(alpha)],
                        ]

                if new_matrix is None:
                    # this if is to treat the case
                    # where alpha==90 (but we still have a monoclinic sg
                    new_matrix = [[a, 0, 0], [0, b, 0], [0, 0, c]]
                    transf = np.zeros(shape=(3, 3))
                    transf[2] = [0, 0, 1]  # see issue #1929
                    for i, d in enumerate(sorted_dic):
                        transf[i][d["orig_index"]] = 1
            # if not C-setting
            else:
                # try all permutations of the axis
                # keep the ones with the non-90 angle=alpha
                # and b<c
                new_matrix = None
                for t in itertools.permutations(list(range(3)), 3):
                    m = latt.matrix
                    a, b, c, alpha, beta, gamma = Lattice(
                        [m[t[0]], m[t[1]], m[t[2]]]
                    ).parameters
                    if alpha > 90 and b < c:
                        a, b, c, alpha, beta, gamma = Lattice(
                            [-m[t[0]], -m[t[1]], m[t[2]]]
                        ).parameters
                        transf = np.zeros(shape=(3, 3))
                        transf[0][t[0]] = -1
                        transf[1][t[1]] = -1
                        transf[2][t[2]] = 1
                        alpha = math.pi * alpha / 180
                        new_matrix = [
                            [a, 0, 0],
                            [0, b, 0],
                            [0, c * cos(alpha), c * sin(alpha)],
                        ]
                        continue
                    if alpha < 90 and b < c:
                        transf = np.zeros(shape=(3, 3))
                        transf[0][t[0]] = 1
                        transf[1][t[1]] = 1
                        transf[2][t[2]] = 1
                        alpha = math.pi * alpha / 180
                        new_matrix = [
                            [a, 0, 0],
                            [0, b, 0],
                            [0, c * cos(alpha), c * sin(alpha)],
                        ]
                if new_matrix is None:
                    # this if is to treat the case
                    # where alpha==90 (but we still have a monoclinic sg
                    new_matrix = [
                        [sorted_lengths[0], 0, 0],
                        [0, sorted_lengths[1], 0],
                        [0, 0, sorted_lengths[2]],
                    ]
                    transf = np.zeros(shape=(3, 3))
                    for i, d in enumerate(sorted_dic):
                        transf[i][d["orig_index"]] = 1

            if international_monoclinic:
                # The above code makes alpha the non-right angle.
                # The following will convert to proper international convention
                # that beta is the non-right angle.
                op = [[0, 1, 0], [1, 0, 0], [0, 0, -1]]
                transf = np.dot(op, transf)
                new_matrix = np.dot(op, new_matrix)
                beta = Lattice(new_matrix).beta
                if beta < 90:
                    op = [[-1, 0, 0], [0, -1, 0], [0, 0, 1]]
                    transf = np.dot(op, transf)
                    new_matrix = np.dot(op, new_matrix)

            latt = Lattice(new_matrix)

        elif latt_type == "triclinic":
            # we use a LLL Minkowski-like reduction for the triclinic cells
            struct = struct.get_reduced_structure("LLL")

            a, b, c = latt.lengths
            alpha, beta, gamma = [math.pi * i / 180 for i in latt.angles]
            new_matrix = None
            test_matrix = [
                [a, 0, 0],
                [b * cos(gamma), b * sin(gamma), 0.0],
                [
                    c * cos(beta),
                    c * (cos(alpha) - cos(beta) * cos(gamma)) / sin(gamma),
                    c
                    * math.sqrt(
                        sin(gamma) ** 2
                        - cos(alpha) ** 2
                        - cos(beta) ** 2
                        + 2 * cos(alpha) * cos(beta) * cos(gamma)
                    )
                    / sin(gamma),
                ],
            ]

            def is_all_acute_or_obtuse(m):
                recp_angles = np.array(Lattice(m).reciprocal_lattice.angles)
                return np.all(recp_angles <= 90) or np.all(recp_angles > 90)

            if is_all_acute_or_obtuse(test_matrix):
                transf = np.eye(3)
                new_matrix = test_matrix

            test_matrix = [
                [-a, 0, 0],
                [b * cos(gamma), b * sin(gamma), 0.0],
                [
                    -c * cos(beta),
                    -c * (cos(alpha) - cos(beta) * cos(gamma)) / sin(gamma),
                    -c
                    * math.sqrt(
                        sin(gamma) ** 2
                        - cos(alpha) ** 2
                        - cos(beta) ** 2
                        + 2 * cos(alpha) * cos(beta) * cos(gamma)
                    )
                    / sin(gamma),
                ],
            ]

            if is_all_acute_or_obtuse(test_matrix):
                transf = [[-1, 0, 0], [0, 1, 0], [0, 0, -1]]
                new_matrix = test_matrix

            test_matrix = [
                [-a, 0, 0],
                [-b * cos(gamma), -b * sin(gamma), 0.0],
                [
                    c * cos(beta),
                    c * (cos(alpha) - cos(beta) * cos(gamma)) / sin(gamma),
                    c
                    * math.sqrt(
                        sin(gamma) ** 2
                        - cos(alpha) ** 2
                        - cos(beta) ** 2
                        + 2 * cos(alpha) * cos(beta) * cos(gamma)
                    )
                    / sin(gamma),
                ],
            ]

            if is_all_acute_or_obtuse(test_matrix):
                transf = [[-1, 0, 0], [0, -1, 0], [0, 0, 1]]
                new_matrix = test_matrix

            test_matrix = [
                [a, 0, 0],
                [-b * cos(gamma), -b * sin(gamma), 0.0],
                [
                    -c * cos(beta),
                    -c * (cos(alpha) - cos(beta) * cos(gamma)) / sin(gamma),
                    -c
                    * math.sqrt(
                        sin(gamma) ** 2
                        - cos(alpha) ** 2
                        - cos(beta) ** 2
                        + 2 * cos(alpha) * cos(beta) * cos(gamma)
                    )
                    / sin(gamma),
                ],
            ]
            if is_all_acute_or_obtuse(test_matrix):
                transf = [[1, 0, 0], [0, -1, 0], [0, 0, -1]]
                new_matrix = test_matrix

            latt = Lattice(new_matrix)

        new_coords = np.dot(transf, np.transpose(struct.frac_coords)).T
        new_struct = Structure(
            latt,
            struct.species_and_occu,
            new_coords,
            site_properties=struct.site_properties,
            to_unit_cell=True,
        )
        return new_struct