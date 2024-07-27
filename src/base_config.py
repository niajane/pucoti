from pathlib import Path
from pprint import pprint
from typing import Annotated, Any, Self, TypeAliasType, get_origin
from dataclasses import dataclass, fields, MISSING
from textwrap import dedent, indent

import yaml
import typer
import inspect

from src import constants


AnnotatedType = type(Annotated[int, "dummy"])


@dataclass(frozen=True)
class Config:
    """The base class for configuration defined by dataclasses by the developer
    and modified using yaml by the user.


    This is not a battleproof implementation.
    In particular, it has no support for arbitrary dicts as values (only dataclasses aka. Config),
    limited support for lists and no support for custom types.
    Errors by users will likely raise understandable exceptions, but errors from devs will
    likely not, as the code with type hints is too messy and britle.
    """

    def load(self, conf: str | dict | Path) -> Self:
        if isinstance(conf, Path):
            data = yaml.safe_load(conf.read_text())
        elif isinstance(conf, str):
            data = yaml.safe_load(conf)
        else:
            data = conf

        # This is a bit messy, and I garantee that this function will not work for
        # evert `config_cls` thrown at it. It will work for most that use only
        # simple type hints. It will not work for unions nor dicts.
        # When it doesn't work because of unsupported config_cls, it will not
        # throw meaningful error messages, but if its `conf` input is invalid,
        # it does its best to throw a meaningful ValueError.

        def path_to_str(path, name: None | str = None):
            if name:
                path = path + (name,)
            return ".".join(path)

        to_update = {}

        def gather_updates(path: tuple, data, expected_type, is_inside_list=False):
            print(path, expected_type)
            # If Annotated, strip the annotation
            if isinstance(expected_type, AnnotatedType):
                expected_type = expected_type.__origin__
            if isinstance(expected_type, TypeAliasType):
                expected_type = expected_type.__value__

            if Config.is_config(expected_type):
                fields_by_name = {field.name: field for field in fields(expected_type)}
                converted_data = {}
                for name, value in data.items():
                    if name not in fields_by_name:
                        valid_fields = ", ".join(fields_by_name)
                        raise ValueError(
                            f"Unknown field {path_to_str(path, name)}. Valid fields are {valid_fields}"
                        )
                    converted_data[name] = gather_updates(
                        path + (name,),
                        value,
                        fields_by_name[name].type,
                        is_inside_list=is_inside_list,
                    )

                return expected_type(**converted_data)

            elif get_origin(expected_type) in (list, tuple):
                if not isinstance(data, (list, tuple)):
                    raise ValueError(f"Expected a list at {path_to_str(path)}, got {data}")
                elif get_origin(expected_type) is tuple:
                    collection_type = tuple
                    sub_types = expected_type.__args__
                    if len(sub_types) != len(data):
                        raise ValueError(
                            f"Expected a tuple of size {len(sub_types)} at {path_to_str(path)}, got {len(data)}"
                        )
                else:
                    collection_type = list
                    sub_types = [expected_type.__args__[0]] * len(data)
                # There is no merging of lists/tuples, we overwrite the full list.
                converted_data = collection_type(
                    gather_updates(path + (i,), d, sub_types[i], is_inside_list=True)
                    for i, d in enumerate(data)
                )
                print(converted_data, "list")
                if not is_inside_list:
                    to_update[path] = converted_data
                return converted_data

            elif expected_type in (str, int, float, Path, bool):
                converted_data = expected_type(data)
                if not is_inside_list:
                    to_update[path] = converted_data
                return converted_data

            else:
                raise ValueError(f"Unsupported type {expected_type} at {path_to_str(path)}")

        gather_updates((), data, type(self))

        # Make the flat dict into a recursive one
        def unflatten(d):
            out = {}
            for path, value in d.items():
                obj = out
                for part in path[:-1]:
                    obj = obj.setdefault(part, {})
                obj[path[-1]] = value
            return out

        pprint(to_update)
        to_update = unflatten(to_update)
        pprint(to_update)

        return self.merge(to_update)

    @staticmethod
    def is_config(type_hint):
        if isinstance(type_hint, AnnotatedType):
            type_hint = type_hint.__origin__
        return issubclass(type_hint, Config)

    @classmethod
    def gather_parameters(cls, prefix: str = "") -> dict[str, type]:
        """Recursively gathers all attributes of the config, except the ones in lists."""
        params = {}
        for fld in fields(cls):
            if cls.is_config(fld.type):
                params.update(fld.type.gather_parameters(prefix + fld.name + "."))
            elif get_origin(fld.type) in (list, dict):
                pass
            else:
                params[prefix + fld.name] = fld.type

        return params

    @classmethod
    def generate_default_config_yaml(cls) -> str:
        """Make the content of the yaml file with all parameters as default.

        It also shows the docsting for parameters as comments
        """

        out = []

        def add_comment(comment: str):
            out.append(indent(dedent(comment), "# "))

        if cls.__doc__:
            doc = cls.__doc__
            if not doc.startswith(cls.__name__ + "("):
                # Doc is automatically generated. We don't want to show that
                add_comment(cls.__doc__)
        for fld in fields(cls):
            try:
                doc = fld.type.__metadata__[0]
                add_comment(doc)
            except AttributeError:
                pass

            if cls.is_config(fld.type):
                # assert issubclass(fld.type, Config)
                out.append(f"{fld.name}:")
                out.append(indent(fld.type.generate_default_config_yaml(), "  "))
                continue

            if fld.default is not MISSING:
                default = fld.default
            elif fld.default_factory is not MISSING:
                default = fld.default_factory()
            else:
                raise ValueError(f"Field {fld.name} has no default value")

            out.append(to_nice_yaml(fld.name, default))

        return "\n".join(part.rstrip() for part in out)

    def merge(self, values: dict[str, dict | Any]):
        """Return a new config with the values provided replaced.

        Does not perform any validation of paths nor types. For this, use .load()
        """

        kwargs = {}
        for field in fields(self):
            if field.name not in values:
                continue

            if self.is_config(field.type):
                kwargs[field.name] = getattr(self, field.name).merge(values[field.name])
            else:
                kwargs[field.name] = values[field.name]

        return type(self)(**kwargs)

    def get(self, name: str):
        obj = self
        for part in name.split("."):
            obj = getattr(obj, part)
        return obj

    @classmethod
    def mk_typer_cli(cls, *arguments: str):
        """Return a function that with the signature that expects typer for @app.command().

        Any name passed in `argument` will be passed to typer as argument, the rest as options.
        Arguments of type list/tuple/dict are not supported and are silently skipped.

        Use as:

        @app.command()
        @Config.mk_typer_cli("arg1", "arg2"):
        def main(config: Config):
            ...
        """

        # Gather all parameters
        params = cls.gather_parameters()

        signature = {}
        for name, typ in params.items():
            if name in arguments:
                param_type = typer.Argument
            else:
                param_type = typer.Option

            if isinstance(typ, AnnotatedType):
                help = typ.__metadata__[0]
                typ = typ.__origin__
            else:
                help = None

            if "." in name:
                rich_panel = name.split(".", 1)[0].title()
            else:
                rich_panel = None

            signature[name] = Annotated[typ, param_type(help=help, rich_help_panel=rich_panel)]

        normalised_to_true_name = {}
        for name in signature:
            normalised = name.replace(".", "_")
            if normalised in normalised_to_true_name:
                raise ValueError(f"There are two config fields that normalise to {normalised}")
            normalised_to_true_name[normalised] = name

        defaults = cls()
        new_signature = inspect.Signature(
            [
                inspect.Parameter(
                    name=name.replace(".", "_"),
                    kind=inspect._ParameterKind.KEYWORD_ONLY,
                    default=defaults.get(name),
                    annotation=typ,
                )
                for name, typ in signature.items()
            ]
        )

        # Create the function
        def decorator(f):
            def decorated(**kwargs):
                config = cls().load(constants.CONFIG_FILE)

                params_overwritten_by_cli = {
                    normalised_to_true_name[name]: value for name, value in kwargs.items()
                }
                config.merge(params_overwritten_by_cli)
                return f(config)

            decorated.__signature__ = new_signature
            return decorated

        return decorator


def to_nice_yaml(name: str, obj):
    if isinstance(obj, Path):
        obj = str(obj)
    elif isinstance(obj, tuple):
        obj = list(obj)

    # default_flow_style=True makes it a one-liner, so that colors don't take to much space
    # but it outputs {name: value}, so we need to remove the first { and last }
    out = yaml.dump({name: obj}, allow_unicode=True, default_flow_style=True)
    return out[1:-2]
