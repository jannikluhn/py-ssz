from typing import (
    Generator,
    Sequence,
    Tuple,
    TypeVar,
)

from eth_utils import (
    to_tuple,
)

from ssz.exceptions import (
    DeserializationError,
    SerializationError,
)
from ssz.sedes.base import (
    BaseSedes,
    CompositeSedes,
)

TSerializableElement = TypeVar("TSerializable")
TDeserializedElement = TypeVar("TDeserialized")


class Tuple(CompositeSedes[Sequence[TSerializableElement], Tuple[TDeserializedElement, ...]]):

    def __init__(self,
                 number_of_elements: int,
                 element_sedes: BaseSedes[TSerializableElement, TDeserializedElement]) -> None:

        self.number_of_elements = number_of_elements
        self.element_sedes = element_sedes

    #
    # Serialization
    #
    def serialize_content(self, value: Sequence[TSerializableElement]) -> bytes:
        if isinstance(value, (bytes, bytearray, str)):
            raise SerializationError("Can not serialize strings as tuples")

        if len(value) != self.number_of_elements:
            raise SerializationError(
                f"Cannot serialize {len(value)} elements as {self.number_of_elements}-tuple"
            )

        return b"".join(
            self.element_sedes.serialize(element) for element in value
        )

    #
    # Deserialization
    #
    @to_tuple
    def deserialize_content(self, content: bytes) -> Generator[TDeserializedElement, None, None]:
        element_start_index = 0
        for element_index in range(self.number_of_elements):
            element, next_element_start_index = self.element_sedes.deserialize_segment(
                content,
                element_start_index,
            )

            if next_element_start_index <= element_start_index:
                raise Exception("Invariant: must always make progress")
            element_start_index = next_element_start_index

            yield element

        if element_start_index > len(content):
            raise Exception("Invariant: must not consume more data than available")
        if element_start_index < len(content):
            raise DeserializationError(
                f"Serialized tuple ends with {len(content) - element_start_index} extra bytes"
            )

    def intermediate_tree_hash(self, value: Sequence[TSerializableElement]) -> bytes:
        pass  # TODO

    #
    # Size
    #
    @property
    def is_variable_length(self):
        return self.number_of_elements > 0 and self.element_sedes.is_variable_length

    def get_fixed_length(self):
        if self.is_variable_length:
            raise ValueError("Tuple does not have a fixed length")

        return self.element_sedes.get_fixed_length()