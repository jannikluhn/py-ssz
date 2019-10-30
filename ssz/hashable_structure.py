import functools
import itertools
from typing import (
    Dict,
    Generator,
    Iterable,
    Iterator,
    List,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)

from eth_typing import Hash32
from eth_utils import to_dict, to_tuple
from eth_utils.toolz import groupby, partition, pipe
from pyrsistent import pvector
from pyrsistent._transformations import transform
from pyrsistent.typing import PVector

from ssz.abc import (
    HashableStructureAPI,
    HashableStructureEvolverAPI,
    ResizableHashableStructureAPI,
    ResizableHashableStructureEvolverAPI,
)
from ssz.constants import CHUNK_SIZE, ZERO_BYTES32
from ssz.hash_tree import HashTree
from ssz.sedes.base import BaseCompositeSedes

TStructure = TypeVar("TStructure", bound="BaseHashableStructure")
TResizableStructure = TypeVar(
    "TResizableStructure", bound="BaseResizableHashableStructure"
)
TElement = TypeVar("TElement")


def update_element_in_chunk(
    original_chunk: Hash32, index: int, element: bytes
) -> Hash32:
    """Replace part of a chunk with a given element.

    The chunk is interpreted as a concatenated sequence of equally sized elements. This function
    replaces the element given by its index in the chunk with the given data.

    If the length of the element is zero or not a divisor of the chunk size, a `ValueError` is
    raised. If the index is out of range, an `IndexError is raised.

    Example:
        >>> update_element_in_chunk(b"aabbcc", 1, b"xx")
        b'aaxxcc'
    """
    element_size = len(element)
    chunk_size = len(original_chunk)

    if element_size == 0:
        raise ValueError(f"Element size is zero")
    if chunk_size % element_size != 0:
        raise ValueError(f"Element size is not a divisor of chunk size: {element_size}")
    if not 0 <= index < chunk_size // element_size:
        raise IndexError(f"Index out of range for element size {element_size}: {index}")

    first_byte_index = index * element_size
    last_byte_index = first_byte_index + element_size

    prefix = original_chunk[:first_byte_index]
    suffix = original_chunk[last_byte_index:]
    return Hash32(prefix + element + suffix)


def update_elements_in_chunk(
    original_chunk: Hash32, updated_elements: Dict[int, bytes]
) -> Hash32:
    """Update multiple elements in a chunk.

    The set of updates is given by a dictionary mapping indices to elements. The items of the
    dictionary will be passed one by one to `update_element_in_chunk`.
    """
    return pipe(
        original_chunk,
        *(
            functools.partial(update_element_in_chunk, index=index, element=element)
            for index, element in updated_elements.items()
        ),
    )


def get_num_padding_elements(
    num_original_chunks: int, num_original_elements: int, element_size: int
) -> int:
    """Compute the number of elements that would still fit in the empty space of the last chunk."""
    total_size = num_original_chunks * CHUNK_SIZE
    used_size = num_original_elements * element_size
    padding_size = total_size - used_size
    num_elements_in_padding = padding_size // element_size
    return num_elements_in_padding


@to_dict
def get_updated_chunks(
    updated_elements: Dict[int, bytes],
    appended_elements: Sequence[bytes],
    original_chunks: Sequence[Hash32],
    num_original_elements: int,
    num_padding_elements: int,
) -> Generator[Tuple[int, Hash32], None, None]:
    """For an element changeset, compute the updates that have to be applied to the existing chunks.

    The changeset is given as a dictionary of element indices to updated elements and a sequence of
    appended elements. Note that appended elements that do not affect existing chunks are ignored.

    The pre-existing state is given by the sequence of original chunks and the number of elements
    represented by these chunks.

    The return value is a dictionary mapping chunk indices to chunks.
    """
    effective_appended_elements = appended_elements[:num_padding_elements]

    # get some element to infer the element size
    try:
        some_element = next(iter(updated_elements.values()))
    except StopIteration:
        try:
            some_element = effective_appended_elements[0]
        except IndexError:
            return  # changeset is empty, so no chunks are updated
    element_size = len(some_element)
    elements_per_chunk = CHUNK_SIZE // element_size

    padding_elements_with_indices = dict(
        enumerate(effective_appended_elements, start=num_original_elements)
    )
    effective_updated_elements = {**updated_elements, **padding_elements_with_indices}

    element_indices = effective_updated_elements.keys()
    element_indices_by_chunk = groupby(
        lambda element_index: element_index // elements_per_chunk, element_indices
    )

    for chunk_index, element_indices in element_indices_by_chunk.items():
        chunk_updates = {
            element_index
            % elements_per_chunk: effective_updated_elements[element_index]
            for element_index in element_indices
        }
        updated_chunk = update_elements_in_chunk(
            original_chunks[chunk_index], chunk_updates
        )
        yield chunk_index, updated_chunk


@to_tuple
def get_appended_chunks(
    appended_elements: Sequence[bytes], num_padding_elements: int
) -> Generator[Hash32, None, None]:
    """Get the sequence of appended chunks."""
    if len(appended_elements) <= num_padding_elements:
        return

    some_element = appended_elements[0]
    element_size = len(some_element)
    elements_per_chunk = CHUNK_SIZE // element_size

    chunk_partitioned_elements = partition(
        elements_per_chunk,
        appended_elements[num_padding_elements:],
        pad=b"\x00" * element_size,
    )
    for elements_in_chunk in chunk_partitioned_elements:
        yield Hash32(b"".join(elements_in_chunk))


class BaseHashableStructure(HashableStructureAPI[TElement]):
    def __init__(
        self,
        elements: PVector[TElement],
        hash_tree: HashTree,
        sedes: BaseCompositeSedes,
    ) -> None:
        self._elements = elements
        self._hash_tree = hash_tree
        self._sedes = sedes

    @classmethod
    def from_iterable(cls, iterable: Iterable[TElement], sedes: BaseCompositeSedes):
        elements = pvector(iterable)
        serialized_elements = [
            sedes.serialize_element_for_tree(index, element)
            for index, element in enumerate(elements)
        ]
        appended_chunks = get_appended_chunks(serialized_elements, 0, 0)
        hash_tree = HashTree.compute(
            appended_chunks or [ZERO_BYTES32], sedes.chunk_count
        )
        return cls(elements, hash_tree, sedes)

    @property
    def elements(self) -> PVector[TElement]:
        return self._elements

    @property
    def hash_tree(self) -> HashTree:
        return self._hash_tree

    @property
    def chunks(self) -> PVector[Hash32]:
        return self.hash_tree.chunks

    @property
    def raw_root(self) -> Hash32:
        return self.hash_tree.root

    @property
    def sedes(self) -> BaseCompositeSedes:
        return self._sedes

    #
    # PVector interface
    #
    def __len__(self) -> int:
        return len(self.elements)

    def __getitem__(self, index: int) -> TElement:
        return self.elements[index]

    def __iter__(self) -> Iterator[TElement]:
        return iter(self.elements)

    def transform(self, *transformations):
        return transform(self, transformations)

    def mset(self: TStructure, *args: Union[int, TElement]) -> TStructure:
        if len(args) % 2 != 0:
            raise TypeError(
                f"mset must be called with an even number of arguments, got {len(args)}"
            )

        evolver = self.evolver()
        for index, value in partition(2, args):
            evolver[index] = value
        return evolver.persistent()

    def set(self: TStructure, index: int, value: TElement) -> TStructure:
        return self.mset(index, value)

    def evolver(
        self: TStructure
    ) -> "HashableStructureEvolverAPI[TStructure, TElement]":
        return HashableStructureEvolver(self)


class HashableStructureEvolver(HashableStructureEvolverAPI[TStructure, TElement]):
    def __init__(self, hashable_structure: TStructure) -> None:
        self._original_structure = hashable_structure
        self._updated_elements: Dict[int, TElement] = {}
        # `self._appended_elements` is only used in the subclass ResizableHashableStructureEvolver,
        # but the implementation of `persistent` already processes it so that it does not have to
        # be implemented twice.
        self._appended_elements: List[TElement] = []

    def __getitem__(self, index: int) -> TElement:
        if index in self._updated_elements:
            return self._updated_elements[index]
        else:
            return self._original_structure[index]

    def set(self, index: int, element: TElement) -> None:
        self[index] = element

    def __setitem__(self, index: int, element: TElement) -> None:
        if 0 <= index < len(self):
            self._updated_elements[index] = element
        else:
            raise IndexError("Index out of bounds: {index}")

    def __len__(self) -> int:
        return len(self._original_structure)

    def is_dirty(self) -> bool:
        return bool(self._updated_elements or self._appended_elements)

    def persistent(self) -> TStructure:
        if not self.is_dirty():
            return self._original_structure

        updated_elements = {
            index: self._original_structure.sedes.serialize_element_for_tree(
                index, element
            )
            for index, element in self._updated_elements.items()
        }
        appended_elements = [
            self._original_structure.sedes.serialize_element_for_tree(index, element)
            for index, element in enumerate(
                self._appended_elements, start=len(self._original_structure)
            )
        ]

        updated_chunks = get_updated_chunks(
            updated_elements,
            appended_elements,
            self._original_structure.hash_tree.chunks,
            len(self._original_structure),
        )
        appended_chunks = get_appended_chunks(
            appended_elements,
            len(self._original_structure.hash_tree.chunks),
            len(self._original_structure),
        )

        elements = self._original_structure.elements.mset(
            *itertools.chain.from_iterable(  # type: ignore
                self._updated_elements.items()
            )
        ).extend(self._appended_elements)
        hash_tree = self._original_structure.hash_tree.mset(
            *itertools.chain.from_iterable(  # type: ignore
                updated_chunks.items()
            )
        ).extend(appended_chunks)

        return self._original_structure.__class__(
            elements, hash_tree, self._original_structure.sedes
        )


class BaseResizableHashableStructure(
    BaseHashableStructure, ResizableHashableStructureAPI[TElement]
):
    def append(self: TResizableStructure, value: TElement) -> TResizableStructure:
        evolver = self.evolver()
        evolver.append(value)
        return evolver.persistent()

    def extend(
        self: TResizableStructure, values: Iterable[TElement]
    ) -> TResizableStructure:
        evolver = self.evolver()
        evolver.extend(values)
        return evolver.persistent()

    def __add__(
        self: TResizableStructure, values: Iterable[TElement]
    ) -> TResizableStructure:
        return self.extend(values)

    def __mul__(self: TResizableStructure, times: int) -> TResizableStructure:
        if times <= 0:
            raise ValueError("Multiplication factor must be positive: {times}")
        elif times == 1:
            return self
        else:
            return (self + self) * (times - 1)

    def evolver(
        self: TResizableStructure,
    ) -> "ResizableHashableStructureEvolverAPI[TResizableStructure, TElement]":
        return ResizableHashableStructureEvolver(self)


class ResizableHashableStructureEvolver(
    HashableStructureEvolver, ResizableHashableStructureEvolverAPI[TStructure, TElement]
):
    def append(self, element: TElement) -> None:
        self._appended_elements.append(element)

    def extend(self, elements: Iterable[TElement]) -> None:
        self._appended_elements.extend(elements)
