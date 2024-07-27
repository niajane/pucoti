from pathlib import Path
from typing import Annotated, Any, Self, TypeAliasType, get_origin
from dataclasses import dataclass, fields, is_dataclass, MISSING, asdict
from textwrap import dedent, indent

import yaml
import typer
import inspect


AnnotatedType = type(Annotated[int, "dummy"])


@dataclass(frozen=True)
class Config:
    """The base class for configuration defined by dataclasses by the developer
    and modified using yaml by the user."""

    @classmethod
    def load(cls, conf: str | dict) -> Self:
        if isinstance(conf, str):
            data = yaml.safe_load(conf)
        else:
            data = conf

        # This is a bit messy, and I garantee that this function will not work for
        # evert `config_cls` thrown at it. It will work for most that use only
        # simple type hints. It will not work for unions not dicts.
        # When it doesn't work because of unsupported config_cls, it will not
        # throw meaningful error messages, but if its `conf` input is invalid,
        # it does its best to throw a meaningful ValueError.

        # Convert to the correct types
        def convert(data, cls):
            try:
                # If Annotated, strip the annotation
                if isinstance(cls, AnnotatedType):
                    cls = cls.__origin__
                if isinstance(cls, TypeAliasType):
                    cls = cls.__value__

                if is_dataclass(cls):
                    return cls(
                        **{
                            field.name: convert(value, field.type)
                            for field, value in zip(fields(cls), data.values())
                        }
                    )
                elif get_origin(cls) is list:
                    assert isinstance(data, list)
                    return cls.__origin__(convert(d, cls.__args__[0]) for d in data)
                elif get_origin(cls) is tuple:
                    assert isinstance(data, (list, tuple))
                    return cls.__origin__(convert(d, typ) for d, typ in zip(data, cls.__args__))
                elif isinstance(data, cls):
                    return data
                elif cls in (str, int, float, Path):
                    return cls(data)
                else:
                    raise ValueError(f"Expected {cls}, got {data}")
            except TypeError as e:
                raise ValueError(f"Error converting {data} to {cls}") from e

        return convert(data, cls)

    @staticmethod
    def is_config(cls: type):
        return is_dataclass(cls) and issubclass(cls, Config)

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

            if is_dataclass(fld.type):
                assert issubclass(fld.type, Config)
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

    def merge(self, values: dict[str, Any]):
        """Merge the values using a flat dict. Dots (.) are use for nested updates."""

        data = asdict(self)

        for name, value in values.items():
            parts = name.split(".")
            obj = data
            for part in parts[:-1]:
                obj = data.setdefault(part, {})
            obj[parts[-1]] = value

        return self.load(data)

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
                help = typ.__args__[0]
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
                config = cls()
                print(kwargs)
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
