from typing import Dict, List, Tuple

import fv3core._config as spec
import fv3core.stencils.remapping_part1 as remap_part1
import fv3core.stencils.remapping_part2 as remap_part2
import fv3core.utils.gt4py_utils as utils
from fv3core.utils.typing import FloatField, FloatFieldIJ, FloatFieldK


def compute(
    tracers: Dict[str, "FloatField"],
    pt: FloatField,
    delp: FloatField,
    delz: FloatField,
    peln: FloatField,
    u: FloatField,
    v: FloatField,
    w: FloatField,
    ua: FloatField,
    va: FloatField,
    cappa: FloatField,
    q_con: FloatField,
    pkz: FloatField,
    pk: FloatField,
    pe: FloatField,
    hs: FloatFieldIJ,
    te0_2d: FloatFieldIJ,
    ps: FloatFieldIJ,
    wsd: FloatField,
    omga: FloatField,
    ak: FloatFieldK,
    bk: FloatFieldK,
    pfull: FloatFieldK,
    dp1: FloatField,
    ptop: float,
    akap: float,
    zvir: float,
    last_step: bool,
    consv_te: float,
    mdt: float,
    bdt: float,
    kord_tracer: List[int],
    do_adiabatic_init: bool,
    nq: int,
):
    compute_origin: Tuple[int, int, int] = spec.grid.compute_origin()

    gz: FloatField = utils.make_storage_from_shape(pt.shape, compute_origin)
    cvm: FloatField = utils.make_storage_from_shape(pt.shape, compute_origin)
    te_2d: FloatFieldIJ = utils.make_storage_from_shape(pt.shape[0:2], compute_origin)
    zsum1: FloatFieldIJ = utils.make_storage_from_shape(pt.shape[0:2], compute_origin)

    remap_part1.compute(
        tracers,
        pt,
        delp,
        delz,
        peln,
        u,
        v,
        w,
        ua,
        cappa,
        q_con,
        pkz,
        pk,
        pe,
        hs,
        dp1,
        ps,
        wsd,
        omga,
        ak,
        bk,
        gz,
        cvm,
        ptop,
        akap,
        zvir,
        nq,
    )
    remap_part2.compute(
        tracers["qvapor"],
        tracers["qliquid"],
        tracers["qice"],
        tracers["qrain"],
        tracers["qsnow"],
        tracers["qgraupel"],
        tracers["qcld"],
        pt,
        delp,
        delz,
        peln,
        u,
        v,
        w,
        ua,
        cappa,
        q_con,
        gz,
        pkz,
        pk,
        pe,
        hs,
        te_2d,
        te0_2d,
        dp1,
        cvm,
        zsum1,
        pfull,
        ptop,
        akap,
        zvir,
        last_step,
        bdt,
        mdt,
        consv_te,
        do_adiabatic_init,
    )
