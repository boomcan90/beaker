from re import I
from typing import Final

from pyteal import *
from beaker import *


@Subroutine(TealType.bytes)
def make_tag_key(tag: abi.String):
    return Concat(Bytes("tag:"), tag.get())

class AppCallbackRegistryItem():
    pass
class Registry():

    def __init__(self):
        pass

    def __getitem__(self, idx: int):
        pass

class MySickApp(Application):

    # App state
    counter: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        descr="A counter for showing how to use application state",
    )

    # Account state
    nickname: Final[LocalStateValue] = LocalStateValue(
        TealType.bytes, default=Bytes("j. doe")
    )
    tags: Final[DynamicLocalStateValue] = DynamicLocalStateValue(
        TealType.uint64, max_keys=10, key_gen=make_tag_key
    )

    registry_fee: Final[Int] = Int(2)*Algo

    registry = Registry()

    # Overrides the default
    @bare_handler(no_op=CallConfig.CREATE)
    def create(self):
        """create application"""
        return self.initialize_app_state()

    @bare_handler(opt_in=CallConfig.CALL)
    def opt_in(self):
        """opt into application"""
        return self.initialize_account_state(Txn.sender())

    @handler
    def add(self, a: abi.Uint64, b: abi.Uint64, *, output: abi.Uint64):
        """add two uint64s, produce uint64"""
        return output.set(a.get() + b.get())

    @handler(authorize=Authorize.only(Global.creator_address()))
    def increment(self, *, output: abi.Uint64):
        """increment the counter"""
        return Seq(
            self.counter.set(self.counter + Int(1)),
            output.set(self.counter),
        )

    @handler(authorize=Authorize.only(Global.creator_address()))
    def decrement(self, *, output: abi.Uint64):
        """decrement the counter"""
        return Seq(
            self.counter.set(self.counter - Int(1)),
            output.set(self.counter),
        )

    @handler
    def add_tag(self, tag: abi.String):
        """add a tag to a user"""
        return self.tags(tag).set(Txn.sender(), Int(1))

    @handler
    def register_callback(self, fee: abi.PaymentTransaction, round: abi.Uint64, app: abi.Application, method: abi.String, *, output: abi.Uint64):
        return Seq(
            Assert(round>Global.round()+10),
            Assert(fee.get().amount()>self.registry_fee),
            output.set(self.registry.add(app, method, round))
        )

    @handler(authorize=Authorize.only(Global.creator_address))
    def trigger_callback(self, index: abi.Uint64, method: abi.String, *, output: abi.String):
        return Seq(
            (data := abi.String()).set(self.generate_data()),
            output.set(self.registry.trigger(index, Global.caller_app_id(), method, Global.round(), data))
        )

    @internal(TealType.bytes)
    def generate_data(self):
        return Bytes("Lmao.")

    #...

    oracle_id: Final[Int] = Int(256)
    oracle_method: Final[str] = register_callback.method_signature() 

    @handler
    def handle_callback(data: abi.String, *, output: abi.String):
        return output.set(Concat("lol.", data.get()))

    @internal(TealType.uint64)
    def register_with_oracle(self):
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.MethodCall(
                app_id=self.oracle_id,
                method_signature=self.oracle_method,
                args=[
                    self.handle_callback.method_signature()
                ]
            ),
            InnerTxnBuilder.Submit()
        )

if __name__ == "__main__":
    import json

    msa = MySickApp()
    print(msa.approval_program)
    print(msa.clear_program)
    print(json.dumps(msa.contract.dictify()))
