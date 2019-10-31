from typing import Iterable, TypeVar

from eth_typing import Hash32
from pyrsistent import pvector

from ssz.hashable_structure import BaseHashableStructure
from ssz.sedes import Vector

TElement = TypeVar("TElement")


class HashableVector(BaseHashableStructure[TElement]):
    @classmethod
    def from_iterable(
        cls, iterable: Iterable[TElement], sedes: Vector[TElement, TElement]
    ):
        elements = pvector(iterable)
        if len(elements) != sedes.length:
            raise ValueError(
                "Vector has length {sedes.length}, but {len(elements)} elements are given"
            )
        return super().from_iterable_and_sedes(elements, sedes, max_length=None)

    @property
    def root(self) -> Hash32:
        return self.raw_root