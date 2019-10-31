from typing import Iterable, TypeVar

from eth_typing import Hash32

from ssz.hashable_structure import BaseResizableHashableStructure
from ssz.sedes import List
from ssz.utils import mix_in_length

TElement = TypeVar("TElement")


class HashableList(BaseResizableHashableStructure[TElement]):
    @classmethod
    def from_iterable(
        cls, iterable: Iterable[TElement], sedes: List[TElement, TElement]
    ):
        return super().from_iterable_and_sedes(
            iterable, sedes, max_length=sedes.max_length
        )

    @property
    def root(self) -> Hash32:
        return mix_in_length(self.raw_root, len(self))