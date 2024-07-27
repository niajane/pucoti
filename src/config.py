from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Annotated

import typer

import constants
from base_config import Config


@dataclass(frozen=True)
class RunAtConfig(Config):
    at: str = "-1m"
    cmd: str = "notify-send 'Time is up by one minute!'"
    every: str | None = None


@dataclass(frozen=True)
class FontConfig(Config):
    timer: Path = constants.BIG_FONT
    rest: Path = constants.FONT


Color = tuple[int, int, int]


@dataclass(frozen=True)
class ColorConfig(Config):
    """Colors can be both triplets of numbers or hexadecimal values"""

    timer: Color = (255, 224, 145)
    timer_up: Color = (255, 0, 0)
    purpose: Color = (183, 255, 183)
    total_time: Color = (183, 183, 255)


@dataclass(frozen=True)
class WindowConfig(Config):
    initial_position: tuple[int, int] = (-5, -5)
    initial_size: tuple[int, int] = (220, 80)


@dataclass(frozen=True)
class PucotiConfig(Config):
    """
    The main configuration for PUCOTI.

    This file should be placed at ~/.config/pucoti/config.yaml.
    You can have multiple presets, by separating the yaml documents with "---".
    """

    preset: str = "default"
    initial_timer: Annotated[str, "The initial timer duration"] = "5m"
    bell: Path = constants.BELL
    ring_every: int = 20
    ring_count: int = -1
    restart: bool = False
    run_at: list[RunAtConfig] = field(default_factory=list)
    history_file: Path = Path("~/.pucoti_history")
    font: FontConfig = FontConfig()
    color: ColorConfig = ColorConfig()
    window: WindowConfig = WindowConfig()


if __name__ == "__main__":
    conf_content = PucotiConfig.generate_default_config_yaml()
    # print(conf_content)

    data = PucotiConfig.load(conf_content)
    # print(data)
    # print(PucotiConfig())

    assert asdict(data) == asdict(PucotiConfig())

    @PucotiConfig.mk_typer_cli("initial_timer")
    def main(config):
        print(config)
        from pprint import pprint

        pprint(asdict(config))

    app = typer.Typer(add_completion=False)
    app.command()(main)

    app()
