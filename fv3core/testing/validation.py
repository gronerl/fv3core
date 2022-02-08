import inspect
from typing import Callable, Mapping, Tuple

import numpy as np

import fv3core.stencils.divergence_damping
import fv3core.stencils.updatedzd
from fv3gfs.util.constants import X_DIM, X_INTERFACE_DIM, Y_DIM, Y_INTERFACE_DIM, Z_DIM
from fv3gfs.util.quantity import Quantity


def get_arg_spec(wrapped: Callable):
    if hasattr(wrapped.__call__, "lazy_method"):
        return wrapped.__call__.lazy_method.arg_spec
    return inspect.getfullargspec(wrapped)


def get_selective_class(
    cls: type,
    name_to_origin_domain_function: Mapping[
        str, Callable[..., Tuple[Tuple[int, ...], Tuple[int, ...]]]
    ],
):
    """
    Convert a model class into one that sets nans on non-validated outputs,
    and gives a helper function to retrieve the output subset we want to validate.

    Using this ensures that if these non-validated values are ever used, a test
    will fail because an output will have NaN.
    """

    class SelectivelyValidated:
        """
        Wrapper class that sets non-validated outputs to nan, and gives a helper
        function to retrieve the output subset to be validated.
        """

        def __init__(self, *args, **kwargs):

            self.wrapped = cls(*args, **kwargs)
            self._validation_slice = {}

            for arg_name, func in name_to_origin_domain_function.items():
                variable_origin, variable_domain = func(self.wrapped)
                self._validation_slice[arg_name] = tuple(
                    slice(start, start + n)
                    for start, n in zip(variable_origin, variable_domain)
                )
            arg_spec = get_arg_spec(self.wrapped)
            self._all_argument_names = tuple(arg_spec.args[1:])
            assert "self" not in self._all_argument_names

        def __call__(self, *args, **kwargs):
            kwargs.update(self._args_to_kwargs(args))
            self.wrapped(**kwargs)
            self._set_nans(kwargs)

        def _args_to_kwargs(self, args):
            return dict(zip(self._all_argument_names, args))

        @property
        def selective_names(self):
            return tuple(self._validation_slice.keys())

        def subset_output(self, varname: str, output: np.ndarray) -> np.ndarray:
            """
            Given an output array, return the slice of the array which we'd
            like to validate against reference data
            """
            if varname in self._validation_slice.keys():
                output = output[self._validation_slice[varname]]
            return output

        def _set_nans(self, kwargs):
            for name, validation_slice in self._validation_slice.items():
                if name in kwargs.keys():
                    array = kwargs[name]
                    validation_data = np.copy(array[validation_slice])
                    array[:] = np.nan
                    array[validation_slice] = validation_data

        def __getattr__(self, name):
            # if SelectivelyValidated doesn't have an attribute, this is called
            # which gets the attribute from the wrapped instance/class
            return getattr(self.wrapped, name)

    return SelectivelyValidated


def get_selective_tracer_advection(
    cls: type,
    origin_domain_func: Callable[..., Tuple[Tuple[int, ...], Tuple[int, ...]]],
):
    class SelectivelyValidatedTracerAdvection:
        """
        We have to treat tracers separately because they are a dictionary,
        not a storage.
        """

        def __init__(self, *args, **kwargs):
            self.wrapped = cls(*args, **kwargs)
            origin, domain = origin_domain_func(self.wrapped)
            self._validation_slice = tuple(
                slice(start, start + n) for start, n in zip(origin, domain)
            )
            arg_spec = get_arg_spec(self.wrapped)
            self._all_argument_names = tuple(arg_spec.args[1:])
            assert "self" not in self._all_argument_names

        def __call__(self, *args, **kwargs):
            if self._all_argument_names is not None:
                kwargs.update(self._args_to_kwargs(args))
            self.wrapped(**kwargs)
            self._set_nans(kwargs["tracers"])

        def _args_to_kwargs(self, args):
            return dict(zip(self._all_argument_names, args))

        def subset_output(self, varname: str, output: np.ndarray) -> np.ndarray:
            """
            Given an output array, return the slice of the array which we'd
            like to validate against reference data
            """
            if varname == "tracers":
                # tracers are still an array for this routine
                output = output[self._validation_slice]
            return output

        def _set_nans(self, tracers: Mapping[str, Quantity]):
            # tracers is a dict of Quantity for this routine
            for quantity in tracers.values():
                validation_data = np.copy(quantity.data[self._validation_slice])
                quantity.data[:] = np.nan
                quantity.data[self._validation_slice] = validation_data

    return SelectivelyValidatedTracerAdvection


def get_compute_domain_k_interfaces(
    instance,
) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
    try:
        origin = instance.grid_indexing.origin_compute()
        domain = instance.grid_indexing.domain_compute(add=(0, 0, 1))
    except AttributeError:
        origin = instance.grid.compute_origin()
        domain = instance.grid.domain_shape_compute(add=(0, 0, 1))
    return origin, domain


def get_domain_func(dims):
    def domain_func(instance):
        return instance.grid_indexing.get_origin_domain(dims)

    return domain_func


def enable_selective_validation():
    """
    Replaces certain function-classes with wrapped versions that set data we aren't
    validating to NaN, and have an attribute function `subset_output` that
    takes in a string variable name and an output array and returns the
    subset of that array which should be validated.

    This wrapping removes any attributes of the wrapped module.
    """
    # to enable selective validation for a new class, add a new monkeypatch
    # this should require only a new function for (origin, domain)
    # note we have not implemented disabling selective validation once enabled
    # [DaCe] the selective validation wrapper _set_nans() can't be parsed (bad annotation) on UpdateHeightOnDGrid
    #        We would either flag _set_nans() with @computepath_method OR do selective validation differently
    # fv3core.stencils.updatedzd.UpdateHeightOnDGrid = get_selective_class(
    # fv3core.stencils.updatedzd.UpdateHeightOnDGrid,
    # {
    # "height": get_compute_domain_k_interfaces,
    # "zh": get_compute_domain_k_interfaces,
    # },  # must include both function argument and savepoint names
    # )
    # make absolutely sure you don't write just the savepoint name, this would
    # selecively validate without making sure it's safe to do so

    # [DaCe] can't parse set_nans, see above
    # fv3core.stencils.tracer_2d_1l.TracerAdvection = get_selective_tracer_advection(
    #     fv3core.stencils.tracer_2d_1l.TracerAdvection,
    #     get_compute_domain_k_interfaces,
    # )

    fv3core.stencils.divergence_damping.DivergenceDamping = get_selective_class(
        fv3core.stencils.divergence_damping.DivergenceDamping,
        {
            "v_contra_dxc": get_domain_func([X_INTERFACE_DIM, Y_INTERFACE_DIM, Z_DIM]),
            "vort": get_domain_func([X_INTERFACE_DIM, Y_INTERFACE_DIM, Z_DIM]),
        },  # must include both function argument and savepoint names
    )
    cell_center_func = get_domain_func([X_DIM, Y_DIM, Z_DIM])
    fv3core.stencils.fv_dynamics.DynamicalCore = get_selective_class(
        fv3core.stencils.fv_dynamics.DynamicalCore,
        {
            "qsnow": cell_center_func,
            "va": cell_center_func,
            "qcld": cell_center_func,
            "qice": cell_center_func,
            "v": get_domain_func([X_INTERFACE_DIM, Y_DIM, Z_DIM]),
            "qliquid": cell_center_func,
            "ua": cell_center_func,
            "q_con": cell_center_func,
            "u": get_domain_func([X_DIM, Y_INTERFACE_DIM, Z_DIM]),
        },
    )
