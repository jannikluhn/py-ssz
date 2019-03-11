from abc import (
    ABC,
    abstractmethod,
)
from typing import (
    Generic,
    Tuple,
    TypeVar,
)

from ssz.constants import (
    LENGTH_PREFIX_SIZE,
)
from ssz.exceptions import (
    DeserializationError,
)
from ssz.hash import (
    hash_eth2,
)
from ssz.utils import (
    get_length_prefix,
    validate_content_length,
)

TSerializable = TypeVar("TSerializable")
TDeserialized = TypeVar("TDeserialized")


class BaseSedes(ABC, Generic[TSerializable, TDeserialized]):

    @abstractmethod
    def serialize(self, value: TSerializable) -> bytes:
        pass

    @abstractmethod
    def deserialize_segment(self, data: bytes, start_index: int) -> Tuple[TDeserialized, int]:
        pass

    def deserialize(self, data: bytes) -> TDeserialized:
        value, end_index = self.deserialize_segment(data, 0)

        num_leftover_bytes = len(data) - end_index
        if num_leftover_bytes > 0:
            raise DeserializationError(
                f"The given string ends with {num_leftover_bytes} superfluous bytes",
                data,
            )
        elif num_leftover_bytes < 0:
            raise Exception(
                "Invariant: End index cannot exceed size of data"
            )

        return value

    @staticmethod
    def consume_bytes(data: bytes, start_index: int, num_bytes: int) -> Tuple[bytes, int]:
        if start_index < 0:
            raise ValueError("Start index must not be negative")
        elif num_bytes < 0:
            raise ValueError("Number of bytes to read must not be negative")
        elif start_index + num_bytes > len(data):
            raise DeserializationError(
                f"Tried to read {num_bytes} bytes starting at index {start_index} but the string "
                f"is only {len(data)} bytes long"
            )
        else:
            continuation_index = start_index + num_bytes
            return data[start_index:start_index + num_bytes], continuation_index

    @abstractmethod
    def intermediate_tree_hash(self, value: TSerializable) -> bytes:
        pass

    @property
    @abstractmethod
    def is_variable_length(self) -> bool:
        pass

    @abstractmethod
    def get_fixed_length(self) -> int:
        pass


class BasicSedes(BaseSedes[TSerializable, TDeserialized]):

    def __init__(self, length: int):
        if length <= 0:
            raise ValueError("Length must be greater than 0")

        self.length = length

    #
    # Size
    #
    is_variable_length = False

    def get_fixed_length(self):
        return self.length

    #
    # Serialization
    #
    def serialize(self, value: TSerializable) -> bytes:
        return self.serialize_content(value)

    @abstractmethod
    def serialize_content(self, value: TSerializable) -> bytes:
        pass

    #
    # Deserialization
    #
    def deserialize_segment(self, data: bytes, start_index: int) -> Tuple[TDeserialized, int]:
        content, continuation_index = self.consume_bytes(data, start_index, self.length)
        return self.deserialize_content(content), continuation_index

    @abstractmethod
    def deserialize_content(self, content: bytes) -> TDeserialized:
        pass

    #
    # Tree hashing
    #
    def intermediate_tree_hash(self, value: TSerializable) -> bytes:
        serialized = self.serialize(value)
        if self.length <= 32:
            return serialized
        else:
            return hash_eth2(serialized)


class CompositeSedes(BaseSedes[TSerializable, TDeserialized]):

    #
    # Serialization
    #
    def serialize(self, value: TSerializable) -> bytes:
        content = self.serialize_content(value)

        if not self.is_variable_length:
            return content
        else:
            validate_content_length(content)
            length_prefix = get_length_prefix(content)
            return length_prefix + content

    @abstractmethod
    def serialize_content(self, value: TSerializable) -> bytes:
        pass

    #
    # Deserialization
    #
    def deserialize_segment(self, data: bytes, start_index: int) -> Tuple[TDeserialized, int]:
        if not self.is_variable_length:
            content_size = self.get_fixed_length()
            content, continuation_index = self.consume_bytes(data, start_index, content_size)
            return self.deserialize_content(content), continuation_index
        else:
            prefix, content_start_index = self.consume_bytes(data, start_index, LENGTH_PREFIX_SIZE)
            length = int.from_bytes(prefix, "little")
            content, continuation_index = self.consume_bytes(data, content_start_index, length)
            return self.deserialize_content(content), continuation_index

    @abstractmethod
    def deserialize_content(self, content: bytes) -> TDeserialized:
        pass
