import typing
from typing import Any, Dict

from gt4py.gtscript import FORWARD, PARALLEL, computation, interval

import fv3core.utils.gt4py_utils as utils
from fv3core.utils.stencil import StencilFactory, computepath_method
from fv3core.utils.typing import FloatField, FloatFieldIJ, IntFieldIJ

# [DaCe] import
from dace import constant as dace_constant
from fv3gfs.util import Quantity


@typing.no_type_check
def fix_tracer(
    q: FloatField,
    dp: FloatField,
    dm: FloatField,
    dm_pos: FloatField,
    zfix: IntFieldIJ,
    sum0: FloatFieldIJ,
    sum1: FloatFieldIJ,
):
    # reset fields
    with computation(FORWARD), interval(...):
        zfix = 0
        sum0 = 0.0
        sum1 = 0.0
    with computation(PARALLEL), interval(...):
        lower_fix = 0.0
        upper_fix = 0.0
    # fix_top:
    with computation(PARALLEL):
        with interval(0, 1):
            if q < 0:
                q = 0
            dm = q * dp
        with interval(1, 2):
            if q[0, 0, -1] < 0.0:
                q = (
                    q + q[0, 0, -1] * dp[0, 0, -1] / dp
                )  # move enough mass up so that the top layer isn't negative
    # fix_interior:
    with computation(FORWARD), interval(1, -1):
        # if a higher layer borrowed from this one, account for that here
        if lower_fix[0, 0, -1] != 0.0:
            q = q - (lower_fix[0, 0, -1] / dp)
        if q < 0.0:
            zfix += 1
            if q[0, 0, -1] > 0.0:
                # Borrow from the layer above
                dq = (
                    q[0, 0, -1] * dp[0, 0, -1]
                    if q[0, 0, -1] * dp[0, 0, -1] < -(q * dp)
                    else -(q * dp)
                )
                q = q + dq / dp
                upper_fix = dq
            if (q < 0.0) and (q[0, 0, 1] > 0.0):
                # borrow from the layer below
                dq = (
                    q[0, 0, 1] * dp[0, 0, 1]
                    if q[0, 0, 1] * dp[0, 0, 1] < -(q * dp)
                    else -(q * dp)
                )
                q = q + dq / dp
                lower_fix = dq
    with computation(PARALLEL), interval(0, -1):
        if upper_fix[0, 0, 1] != 0.0:
            # If a lower layer borrowed from this one, account for that here
            q = q - upper_fix[0, 0, 1] / dp
        dm = q * dp
        dm_pos = dm if dm > 0.0 else 0.0
    # fix_bottom:
    with computation(FORWARD), interval(-1, None):
        # the 2nd-to-last layer borrowed from this one, account for that here
        if lower_fix[0, 0, -1] != 0.0:
            q = q - (lower_fix[0, 0, -1] / dp)
        qup = q[0, 0, -1] * dp[0, 0, -1]
        qly = -q * dp
        dup = qup if qup < qly else qly
        if (q < 0.0) and (q[0, 0, -1] > 0.0):
            zfix += 1
            q = q + (dup / dp)
            upper_fix = dup
        dm = q * dp
        dm_pos = dm if dm > 0.0 else 0.0
    with computation(PARALLEL), interval(-2, -1):
        # if the bottom layer borrowed from this one, adjust
        if upper_fix[0, 0, 1] != 0.0:
            q = q - (upper_fix[0, 0, 1] / dp)
            dm = q * dp
            dm_pos = dm if dm > 0.0 else 0.0  # now we gotta update these too
    with computation(FORWARD), interval(1, None):
        sum0 += dm
        sum1 += dm_pos
    # final_check
    with computation(PARALLEL), interval(1, None):
        fac = sum0 / sum1 if sum0 > 0.0 else 0.0
        if zfix > 0 and fac > 0.0:
            q = fac * dm / dp if fac * dm / dp > 0.0 else 0.0


class FillNegativeTracerValues:
    """
    Fix tracer values to prevent negative masses.

    Fortran name is `fillz`
    """

    # [DaCe] filter tracers in __init__ instead of runtime
    def __init__(
        self,
        stencil_factory: StencilFactory,
        im: int,
        jm: int,
        km: int,
        nq: int,
        tracers: Dict[str, Quantity],
    ):
        self._nq = nq
        self._fix_tracer_stencil = stencil_factory.from_origin_domain(
            fix_tracer,
            origin=stencil_factory.grid_indexing.origin_compute(),
            domain=(im, jm, km),
        )

        shape = stencil_factory.grid_indexing.domain_full(add=(1, 1, 1))
        shape_ij = shape[0:2]

        self._dm = utils.make_storage_from_shape(shape, origin=(0, 0, 0))
        self._dm_pos = utils.make_storage_from_shape(shape, origin=(0, 0, 0))
        # Setting initial value of upper_fix to zero is only needed for validation.
        # The values in the compute domain are set to zero in the stencil.
        self._zfix = utils.make_storage_from_shape(shape_ij, dtype=int, origin=(0, 0))
        self._sum0 = utils.make_storage_from_shape(shape_ij, origin=(0, 0))
        self._sum1 = utils.make_storage_from_shape(shape_ij, origin=(0, 0))

        # [DaCe] linearlize tracers dict into a list at __init__ time
        self._filtered_tracer_dict = {
            name: tracers[name] for name in utils.tracer_variables[0 : self._nq]
        }

    @computepath_method
    def __call__(
        self,
        dp2: FloatField,
        tracers: dace_constant,
    ):
        # [DaCe] runtime tracers is deactivate, was cached in __init__

        # [DaCe] return value is not used
        # [DaCe] dict.values/dict.items bug - using key indexing
        for tracer_name in self._filtered_tracer_dict.keys():
            self._fix_tracer_stencil(
                tracers[tracer_name],
                dp2,
                self._dm,
                self._dm_pos,
                self._zfix,
                self._sum0,
                self._sum1,
            )
        # [DaCe] unused return value was removed
