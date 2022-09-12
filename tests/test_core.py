from ctypes import BigEndianStructure, c_char, c_uint32
from dataclasses import dataclass, field

import pytest
from cdata import CDataMixIn, metadata

# from typing import List


@dataclass
class Base(CDataMixIn):
    _cdata_base_ = BigEndianStructure
    _cdata_pack_ = 1


@dataclass
class Item(Base):
    number: int = field(metadata=metadata(c_uint32))
    string: str = field(metadata=metadata(c_char * 10))


@pytest.fixture
def item():
    return Item(1, "abcde")


"""
@dataclass
class MixInData(Base):
    number: int = field(ctypes.c_uint32)
    string: str = field(ctypes.c_char * 20)
    item: MixInItem = field(MixInItem.ctype())
    items: List[MixInItem] = field(MixInItem.ctype() * 5)
    int_array: List[int] = field(ctypes.c_uint16 * 6)
    byte_array: List[int] = field(ctypes.c_byte * 7)

@pytest.fixture
def item():
    return MixInData(
        1,
        "Data",
        MixInItem(0, "A"),
        [MixInItem(i, f"{i}") for i in range(5)],
        [i for i in range(6)],
        [i for i in range(7)],
    )
"""


def test_integer(item):
    c = item.to_ctype()
    assert c.number == 1


def test_str(item):
    c = item.to_ctype()
    assert c.string == "abcde"
