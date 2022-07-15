from inspect import getattr_static, signature
from typing import Final, cast, Callable
from algosdk.abi import Method
from pyteal import (
    MAX_TEAL_VERSION,
    Expr,
    ABIReturnSubroutine,
    Approve,
    BareCallActions,
    Expr,
    Global,
    MethodConfig,
    OnCompleteAction,
    OptimizeOptions,
    Reject,
    Router,
    Bytes,
    Subroutine,
)

from .decorators import (
    Bare,
    HandlerConfig,
    MethodHints,
    get_handler_config,
)
from .application_schema import (
    AccountState,
    ApplicationState,
    DynamicLocalStateValue,
    LocalStateValue,
    GlobalStateValue,
    DynamicGlobalStateValue,
)
from .errors import BareOverwriteError


def get_method_spec(fn) -> Method:
    hc = get_handler_config(fn)
    if hc.method_spec is None:
        raise Exception("Expected argument to be an ABI method")
    return hc.method_spec


class Application:
    """Application should be subclassed to add functionality"""

    # Convenience constant fields
    address: Final[Expr] = Global.current_application_address()
    id: Final[Expr] = Global.current_application_id()

    def __init__(self, version: int = MAX_TEAL_VERSION):
        self.teal_version = version

        self.attrs = {
            m: (getattr(self, m), getattr_static(self, m))
            for m in list(set(dir(self.__class__)) - set(dir(super())))
            if not m.startswith("__")
        }

        self.hints: dict[str, MethodHints] = {}
        self.bare_handlers: dict[str, OnCompleteAction] = {}
        self.methods: dict[str, tuple[ABIReturnSubroutine, MethodConfig]] = {}

        acct_vals: dict[str, LocalStateValue | DynamicLocalStateValue] = {}
        app_vals: dict[str, GlobalStateValue | DynamicGlobalStateValue] = {}

        for name, (bound_attr, static_attr) in self.attrs.items():
            handler_config = get_handler_config(bound_attr)

            match (bound_attr, handler_config):
                # Local State
                case DynamicLocalStateValue(), _:
                    acct_vals[name] = bound_attr
                case LocalStateValue(), _:
                    if bound_attr.key is None:
                        bound_attr.key = Bytes(name)
                    acct_vals[name] = bound_attr

                # Global State
                case DynamicGlobalStateValue(), _:
                    app_vals[name] = bound_attr
                case GlobalStateValue(), _:
                    if bound_attr.key is None:
                        bound_attr.key = Bytes(name)
                    app_vals[name] = bound_attr

                # Bare Handlers
                case _, HandlerConfig(bare_method=BareCallActions()):
                    actions = {
                        oc: cast(OnCompleteAction, action)
                        for oc, action in handler_config.bare_method.__dict__.items()
                        if action is not None
                    }

                    for oc, action in actions.items():
                        if oc in self.bare_handlers:
                            raise BareOverwriteError(oc)

                        # Swap the implementation with the bound version
                        if handler_config.referenced_self:
                            action.action.subroutine.implementation = bound_attr

                        self.bare_handlers[oc] = action

                # ABI Methods
                case _, HandlerConfig(method_spec=Method()):
                    # Create the ABIReturnSubroutine from the static attr
                    # but override the implementation with the bound version
                    abi_meth = ABIReturnSubroutine(static_attr)
                    if handler_config.referenced_self:
                        abi_meth.subroutine.implementation = bound_attr
                    self.methods[name] = abi_meth
                    self.hints[name] = handler_config.hints()

                # Internal subroutines
                case _, HandlerConfig(subroutine=Subroutine()):
                    if handler_config.referenced_self:
                        setattr(self, name, handler_config.subroutine(bound_attr))
                    else:
                        setattr(
                            self.__class__,
                            name,
                            handler_config.subroutine(static_attr),
                        )

        self.acct_state = AccountState(acct_vals)
        self.app_state = ApplicationState(app_vals)

        # Create router with name of class and bare handlers
        self.router = Router(
            name=self.__class__.__name__,
            bare_calls=BareCallActions(**self.bare_handlers),
        )

        # Add method handlers
        for method in self.methods.values():
            self.router.add_method_handler(
                method_call=method, method_config=handler_config.method_config
            )

        (
            self.approval_program,
            self.clear_program,
            self.contract,
        ) = self.router.compile_program(
            version=self.teal_version,
            assemble_constants=True,
            optimize=OptimizeOptions(scratch_slots=True),
        )

    def initialize_app_state(self):
        return self.app_state.initialize()

    def initialize_account_state(self, addr):
        return self.acct_state.initialize(addr)

    @Bare.create
    def create(self):
        return Approve()

    @Bare.update
    def update(self):
        return Reject()

    @Bare.delete
    def delete(self):
        return Reject()

    @Bare.opt_in
    def opt_in(self):
        return Reject()

    @Bare.close_out
    def close_out(self):
        return Reject()

    @Bare.clear_state
    def clear_state(self):
        return Reject()
