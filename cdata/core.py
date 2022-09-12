import abc
import ctypes
import functools
import types
from dataclasses import asdict, fields, make_dataclass
from typing import (Any, Callable, ClassVar, Dict, Optional, Type, TypeVar,
                    Union)

CFieldName = str
CFieldType = Any
CFliedValue = Any
DataclassValue = Any
CtypesDecodeHook = Callable[[CFieldName, CFieldType, CFliedValue, DataclassValue], Optional[Any]]
CtypesEncodeHook = Callable[[CFieldName, CFieldType, CFliedValue, DataclassValue], Optional[Any]]
CtypesStructuredType = Union[Type[ctypes.Structure], Type[ctypes.Union]]
CtypesStructuredData = Union[ctypes.Structure, ctypes.Union]
StructureName = str

T = TypeVar("T", bound="CDataMixIn")

_STRUCTURE_DATACLASS_MAP: Dict[StructureName, Type] = {}
_CTYPE = "ctype"


def metadata(ctype: Union[Type[ctypes.Structure], Type[ctypes._SimpleCData], Type[ctypes.Array]]):
    return {_CTYPE: ctype}


@functools.cache
def _create_ctypes_class(datacls: Type, base: CtypesStructuredType, pack: int) -> CtypesStructuredType:
    """
    Dynamically create a class of ctypes.Structure/ctypes.Union corresponding to the given dataclass.
    """
    structure_name = f"_ctypes_generated_from_{datacls.__name__}"
    generated_ctypes_class = types.new_class(name=structure_name, bases=(base,))
    setattr(generated_ctypes_class, "_pack_", pack)
    setattr(generated_ctypes_class, "_fields_", [(f.name, f.metadata.get(_CTYPE)) for f in fields(datacls)])

    # Cache the dataclass info so that _create_dataclass can get the generated ctype class here
    _STRUCTURE_DATACLASS_MAP[structure_name] = datacls

    return generated_ctypes_class


@functools.cache
def _create_dataclass(structure: CtypesStructuredType) -> Type[T]:
    """
    Create a dataclass corresponding to the given ctypes.Structure/ctypes.Union.
    """
    # Get class info if there is an already defined dataclass for the coressponding structure
    already_defined = _STRUCTURE_DATACLASS_MAP.get(structure.__name__)
    if already_defined is not None:
        return already_defined

    generated_dataclass: Type[T] = make_dataclass(
        cls_name=f"_dataclass_generated_from_{structure.__name__}",
        fields=[(fname, ftype) for fname, ftype in getattr(structure, "_fields_", [])],
        bases=(CDataMixIn,),
    )

    setattr(generated_dataclass, "_cdata_pack_", structure._pack_)
    setattr(generated_dataclass, "_cdata_base_", structure)

    return generated_dataclass


def _ctypes2dataclass(
    datacls: Type[T], structure: CtypesStructuredData, padding: bool, hook: Optional[CtypesDecodeHook] = None
) -> T:
    """Create a dataclass instance initialized with the given ctypes.Structure/ctypes.Union"""
    d = {}
    for cname, ctype in getattr(structure, "_fields_", []):
        cvalue = getattr(structure, cname)
        dataclass_value = getattr(datacls, cname)

        if hook is not None and hook(cname, ctype, cvalue, dataclass_value) is not None:
            d[cname] = hook(cname, ctype, cvalue, dataclass_value)
            continue
        if (type(cvalue) not in [int, float, bool]) and not bool(cvalue):
            # Probably null pointer
            d[cname] = None
        elif hasattr(cvalue, "_length_") and hasattr(cvalue, "_type_"):
            # Probably an array
            if issubclass(cvalue._type_, ctypes.Structure) or issubclass(cvalue._type_, ctypes.Union):
                d[cname] = [_ctypes2dataclass(_create_dataclass(cvalue._type_), e, padding, hook) for e in cvalue]
            else:
                d[cname] = [e for e in cvalue]
        elif hasattr(cvalue, "_fields_"):
            # Probably another struct
            d[cname] = _ctypes2dataclass(dataclass_value.__class__, cvalue, padding, hook)
        # By default
        d[cname] = cvalue

    return datacls(**d)


def _dataclass2ctypes(
    datacls_instance: T, padding: bool, hook: Optional[CtypesEncodeHook] = None
) -> CtypesStructuredData:
    """Create a ctypes.Structure/ctypes.Union instance from given dataclass instance."""
    structure = datacls_instance.__class__.ctype()()
    for cname, ctype in getattr(structure, "_fields_", []):
        cvalue = getattr(structure, cname)
        dataclass_value = getattr(datacls_instance, cname)

        if hook is not None and hook(cname, ctype, cvalue, dataclass_value) is not None:
            setattr(structure, cname, hook(cname, ctype, cvalue, dataclass_value))
            continue
        if hasattr(cvalue, "_length_") and hasattr(cvalue, "_type_"):
            if issubclass(cvalue._type_, ctypes.Structure) or issubclass(cvalue._type_, ctypes.Union):
                setattr(structure, cname, (ctype)(*[_dataclass2ctypes(e, padding, hook) for e in dataclass_value]))
            else:
                setattr(structure, cname, (ctype)(*[e for e in dataclass_value]))
        elif hasattr(cvalue, "_fields_"):
            # Probably another struct
            setattr(structure, cname, _dataclass2ctypes(dataclass_value, padding, hook))
        # By default
        setattr(structure, cname, dataclass_value)
    return structure


class CDataMixIn(abc.ABC):
    """
    MixIn for dataclass to be able to convert from/to ctypes Structure/Union.
    """

    _cdata_base_: ClassVar[CtypesStructuredType]
    _cdata_pack_: ClassVar[int]

    # _decode_padding: bool = True
    # _encode_padding: bool = True
    _decode_hook: Optional[CtypesDecodeHook] = None
    _encode_hook: Optional[CtypesEncodeHook] = None

    @classmethod
    def ctype(cls: Type[T]) -> CtypesStructuredType:
        """Return a ctypes.Strcuture/ctypes.Union class corresponding to own dataclass"""
        return _create_ctypes_class(cls, cls._cdata_base_, cls._cdata_pack_)

    @classmethod
    def from_buffer(
        cls: Type[T], buffer: bytearray, offset=0, padding=True, hook: Optional[CtypesDecodeHook] = None
    ) -> T:
        """Return a corresponding ctypes.Structure/ctypes.Union instance shared with given buffer."""
        structure = cls.ctype().from_buffer(buffer, offset)
        return cls.from_ctype(structure, padding, hook)

    @classmethod
    def from_buffer_copy(
        cls: Type[T], buffer: bytes, offset=0, padding=True, hook: Optional[CtypesDecodeHook] = None
    ) -> T:
        """Return a corresponding ctypes.Structure/ctypes.Union instance copied from given buffer."""
        structure = cls.ctype().from_buffer_copy(buffer, offset)
        return cls.from_ctype(structure, padding, hook)

    @classmethod
    def from_ctype(
        cls: Type[T],
        structure: CtypesStructuredData,
        padding=True,
        hook: Optional[CtypesDecodeHook] = None,
    ) -> T:
        """Return an instance initialized with the given ctypes.Structure/ctypes.Union object."""
        if hook is None:
            hook = cls._decode_hook
        return _ctypes2dataclass(cls, structure, padding, hook)

    def to_ctype(self: T, padding=True, hook: Optional[CtypesEncodeHook] = None) -> CtypesStructuredData:
        """Return a ctypes.Strcuture instance from self."""
        if hook is None:
            hook = self.__class__._decode_hook
        return _dataclass2ctypes(self, padding, hook)

    @classmethod
    def from_dict(cls: Type[T], src: Dict[str, Any]) -> T:
        """Return an instance initialized with the given dict."""
        return cls(**src)

    def to_dict(self: T) -> Dict[str, Any]:
        """Return a dict instance from self."""
        return asdict(self)


class NativeEndianStructureMixIn(CDataMixIn):
    _cdata_endian = ctypes.Structure
    _cdata_pack = 1


class LittleEndianStructureMixIn(CDataMixIn):
    _cdata_endian = ctypes.LittleEndianStructure
    _cdata_pack = 1


class BigEndianStructureMixIn(CDataMixIn):
    _cdata_endian = ctypes.BigEndianStructure
    _cdata_pack = 1


class UnionMixIn(CDataMixIn):
    _cdata_endian = ctypes.Union
    _cdata_pack = 1
