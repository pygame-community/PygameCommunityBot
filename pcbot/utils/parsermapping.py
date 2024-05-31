from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping

from . import raise_


class ParserMapping(
    dict[
        str,
        Callable[[str, Any, MutableMapping[str, Any]], Any]
        | "ParserMapping"
        | "ParserMappingValue",
    ]
):
    """A `dict` subclass that parses and/or validates mapping objects based on the
    structure and callback values of the input mapping given to it. The parsing and/or
    validating occurs in the order of definition of the key-value pairs of the input
    mapping. Input mapping fields can be marked as required using
    `ParserMappingValue(..., required=True)` as a value.

    `ParserMapping` instances can be arbitrarily nested inside input mappings of
    outer `ParserMapping` as values, to define more complex reqirements for the
    mappings to be validated and/or parsed.


    Examples
    --------

    ```py
    import re

    def raise_(exc):
        raise exc

    parser_mapping = ParserMapping(
        {
            "username": str,
            "password": lambda key, value, values_map: value # `values_map` is the value of the
            if isinstance(value, str) and len(value) > 8
            else raise_(
                ParsingError(
                    f"value for field '{key}' must be a string longer than 8 characters"
                )
            ),
            "email": ParserMappingValue(
                lambda key, value, values_map: value
                if isinstance(value, str) and re.match(r"^[\\w\\.]+@[\\w\\.]+$")
                else raise_(
                    ParsingError(
                        f"value for field '{key}' must be a string that is a valid email"
                    )
                ),
                required=True,
            ),
            ...: ...,
        },
    )

    parsed = parser_mapping.parse(
        {"username": "abc", "password": 123456789}
    )  # will raise an exception, as "email" is missing and "password" is of the wrong type.
    ```
    """

    __slots__ = (
        "_key",
        "_parent",
        "require_all",
        "reject_unknown",
    )

    def __init__(
        self,
        mapping: Mapping[
            str,
            Callable[[str, Any, MutableMapping[str, Any]], Any]
            | type
            | "ParserMapping"
            | "ParserMappingValue",
        ],
        require_all: bool = False,
        reject_unknown: bool = False,
    ):
        self._key: str | None = None
        self._parent: ParserMapping | None = None
        self.require_all = require_all
        self.reject_unknown = reject_unknown

        if not isinstance(mapping, Mapping):
            raise TypeError("argument 'mapping' must be a mapping object")

        temp_mapping = {}

        current_pmv = None

        _parser_lambda_map: dict[str, type] = {}
        # helper dictionary to hold classes passed as values to 'mapping', to avoid
        # local scope bugs with lambda functions defined in this method

        for k, v in tuple(mapping.items()):  # begin
            if isinstance(
                v, ParserMappingValue
            ):  # A ParserMappingValue was explicitly declared
                current_pmv = v
                v = v.value

            if isinstance(
                v, self.__class__
            ):  # build parent-child references with nested ParserMappings
                v._parent = self
                v._key = k
            elif isinstance(
                v, type
            ):  # convert class object to a validator using isinstance()
                cls = v

                callback = lambda key, value, mapping: (
                    value
                    if isinstance(value, _parser_lambda_map[key])  # type: ignore
                    else raise_(
                        ParsingError(
                            f"value "
                            + (
                                f"at fully qualified key '{qk}': "
                                if (qk := self._get_qualified_key())
                                else ": "
                            )
                            + f"must be an instance of '{v.__name__}' not '{type(value).__name__}'"
                        )
                    )
                )

                _parser_lambda_map[k] = v

                if current_pmv:
                    current_pmv.value = callback
                else:
                    temp_mapping[k] = v = callback

            elif not callable(v):
                raise ValueError(
                    f"value for mapping key '{k}' is not a class, callable, ParserMappingValue or a "
                    f"'{self.__class__.__name__}' object"
                )

            current_pmv = None

        self.update(mapping)
        self.update(temp_mapping)

    def _get_qualified_key(self, sep: str = ".") -> str:
        keys = []
        if self._key:
            keys.append(self._key)
        curr_parent = self._parent

        while curr_parent is not None:
            if curr_parent._key is not None:
                keys.append(
                    f"'{curr_parent._key}'"
                    if "." in curr_parent._key
                    else curr_parent._key
                )
            curr_parent = curr_parent._parent

        return sep.join(reversed(keys))

    def parse(
        self, input_mapping: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        if not isinstance(input_mapping, MutableMapping):
            raise ParsingError(
                f"value"
                + (
                    f"at fully qualified key '{qk}': "
                    if (qk := self._get_qualified_key())
                    else ": "
                )
                + "must be an instance of a mutable mapping "
                "type instantiable without arguments"
            )

        if self.require_all and len(input_mapping) < len(self):
            raise ParsingError(
                "Parsing failed"
                + (
                    f"at fully qualified key " + f"'{qk}': "
                    if (qk := self._get_qualified_key())
                    else ": "
                )
                + "All fields are required "
            )

        elif self.reject_unknown:
            for key in input_mapping:
                if key not in self:
                    raise ParsingError(
                        "Parsing failed"
                        + (
                            f"at fully qualified key " + f"'{qk}': "
                            if (qk := self._get_qualified_key())
                            else ": "
                        )
                        + f"Key '{key}' is unknown"
                    )

        try:
            output_mapping = input_mapping.__class__()
        except TypeError as t:
            raise ParsingError(
                f"value"
                + (
                    f"at fully qualified key '{qk}': "
                    if (qk := self._get_qualified_key())
                    else ": "
                )
                + "must be an instance of a mutable mapping "
                "type instantiable without arguments (e.g. dict)"
            ) from t

        for k, v_or_pmv in self.items():
            was_pmv = False
            if isinstance(v_or_pmv, ParserMappingValue):
                was_pmv = True
                v = v_or_pmv.value
            else:
                v = v_or_pmv

            if k in input_mapping:
                if isinstance(v, self.__class__):
                    output_mapping[k] = v.parse(input_mapping[k])
                else:
                    output_mapping[k] = v(k, input_mapping[k], output_mapping)  # type: ignore
            elif was_pmv and v_or_pmv.required or self.require_all:  # type: ignore
                raise ParsingError(
                    f"mapping "
                    + (
                        f"at fully qualified key '{qk}' "
                        if (qk := self._get_qualified_key())
                        else " "
                    )
                    + f"is missing required key '{k}' "
                )

        return output_mapping


class ParsingError(Exception):
    """A class for :class:`ParserMapping` related parsing errors."""

    pass


@dataclass
class ParserMappingValue:
    value: Callable[[str, Any, MutableMapping], Any] | ParserMapping | type
    required: bool = False


PMValue = ParserMappingValue
