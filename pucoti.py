#!/usr/bin/env python

"""
PUCOTI - A Purposeful Countdown Timer
Copyright (C) 2024  Diego Dorn

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""


from dataclasses import dataclass
from functools import lru_cache
import json
import os
import subprocess
import sys
from time import time
from typing import Annotated
from pathlib import Path
import re
import typer
from typer import Argument, Option
from enum import Enum

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"
os.environ["SDL_VIDEODRIVER"] = "x11"

import pygame
from pygame.locals import *
import pygame._sdl2 as sdl2


BELL = Path(__file__).parent / "bell.mp3"
FONT = Path(__file__).parent / "Wellbutrin.ttf"
WINDOW_SCALE = 1.2
POSITIONS = [(-5, -5), (5, 5), (5, -5), (-5, 5)]
SHORTCUTS = """
J/K: -/+ 1 minute
R: reset timer
RETURN: enter purpose
L: list purpose history
P: reposition window
-/=: (in/de)crease window size
H/?: show this help
""".strip()
HELP = f"""
DTimer

{SHORTCUTS}

Press any key to dismiss this message.
""".strip()


def fmt_time(seconds):
    if seconds < 0:
        return "-" + fmt_time(-seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, seconds)
    else:
        return "%02d:%02d" % (minutes, seconds)


@lru_cache(maxsize=40)
def get_font(size: int):
    return pygame.font.Font(FONT, size)


@lru_cache(maxsize=100)
def text(
    text: str,
    size: int | tuple[int, int],
    color: tuple,
    monospaced_time: bool = False,
):
    if not isinstance(size, int):
        if monospaced_time:
            # Use the font size that fits a text equivalent to the time.
            # We use 0s to make sure the text is as wide as possible and doesn't jitter.
            size = auto_size(re.sub(r"\d", "0", text), size)
        else:
            size = auto_size(text, size)

    if not monospaced_time:
        return get_font(size).render(text, True, color)
    else:
        digits = "0123456789"
        # We render each char independently to make sure they are monospaced.
        chars = [get_font(size).render(c, True, color) for c in text]
        # Make each digit the size of a 0.
        width = get_font(size).size("0")[0]
        full_width = sum(s.get_width() if c not in digits else width for c, s in zip(text, chars))
        # Create a surface with the correct width.
        surf = pygame.Surface((full_width, chars[0].get_height()), SRCALPHA)
        # Blit each char at the correct position.
        x = 0
        for c, s in zip(text, chars):
            if c in digits:
                blit_x = x + (width - s.get_width()) // 2
            else:
                blit_x = x
            surf.blit(s, (blit_x, 0))
            x += s.get_width() if c not in digits else width
        return surf


def size_with_newlines(text: str, size: int):
    """Return the size of the text with newlines."""
    lines = text.split("\n")
    line_height = get_font(size).get_linesize()
    return (max(get_font(size).size(line)[0] for line in lines), len(lines) * line_height)


def auto_size(text: str, max_rect: tuple[int, int]):
    """Find the largest font size that will fit text in max_rect."""
    # Use dichotomy to find the largest font size that will fit text in max_rect.

    min_size = 1
    max_size = max_rect[1]
    while min_size < max_size:
        font_size = (min_size + max_size) // 2
        text_size = size_with_newlines(text, font_size)

        if text_size[0] <= max_rect[0] and text_size[1] <= max_rect[1]:
            min_size = font_size + 1
        else:
            max_size = font_size
    return min_size - 1


def place_window(window, x: int, y: int):
    """Place the window at the desired position using sway."""

    # size = subprocess.check_output("swaymsg -t get_outputs | jq '.[] | select(.active) | .current_mode.width, .current_mode.height'", shell=True)
    # size = tuple(map(int, size.split()))
    info = pygame.display.Info()
    size = info.current_w, info.current_h

    if x < 0:
        x = size[0] + x - window.size[0]
    if y < 0:
        y = size[1] + y - window.size[1]

    # Is there a way to know if this worked? It doesn't on sway.
    # It works on some platforms.
    window.position = (x, y)

    try:
        cmd = f'swaymsg "[title=\\"DTimer\\"] move absolute position {x} {y}"'
        subprocess.check_output(cmd, shell=True)
    except subprocess.CalledProcessError as e:
        print(e.output)


def play(sound):
    pygame.mixer.music.load(sound)
    pygame.mixer.music.play()


def vsplit(rect, *ratios):
    """Split a rect vertically in ratios."""
    total_ratio = sum(ratios)
    ratios = [r / total_ratio for r in ratios]
    cummulative_ratios = [0] + [sum(ratios[:i]) for i in range(1, len(ratios) + 1)]
    ys = [int(rect.height * r) for r in cummulative_ratios]
    return [
        pygame.Rect(rect.left, ys[i], rect.width, ys[i + 1] - ys[i]) for i in range(len(ratios))
    ]


def human_duration(duration: str) -> int:
    """Convert a human duration to seconds."""

    # Parse the duration.
    total = 0
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    for part in duration.split():
        try:
            total += int(part[:-1]) * multiplier[part[-1]]
        except (ValueError, KeyError):
            raise ValueError(f"Invalid duration part: {part}")

    return total


@dataclass
class Purpose:
    text: str
    timestamp: float


class Scene(Enum):
    MAIN = "main"
    HELP = "help"
    PURPOSE_HISTORY = "purpose_history"
    ENTERING_PURPOSE = "entering_purpose"

    def mk_layout(self, screen_size: tuple[int, int], has_purpose: bool) -> dict[str, pygame.Rect]:
        width, height = screen_size
        screen = pygame.Rect((0, 0), screen_size)

        if self == Scene.HELP:
            return {"help": screen}
        elif self == Scene.PURPOSE_HISTORY:
            return {"purpose_history": screen}
        elif self == Scene.ENTERING_PURPOSE:
            if height < 60:
                return {"purpose": screen}
            elif height < 120:
                purpose, time = vsplit(screen, 2, 1)
                return {"purpose": purpose, "time": time}
            else:
                purpose, time, bottom = vsplit(screen, 2, 1, 1)
                return {"purpose": purpose, "time": time, "total_time": bottom}
        elif self == Scene.MAIN:
            if height < 60:
                return {"time": screen}
            elif height < 120:
                if not has_purpose:
                    return {"time": screen}
                purpose, time = vsplit(screen, 1, 2)
                return {"purpose": purpose, "time": time}
            else:
                if not has_purpose:
                    time, bottom = vsplit(screen, 3, 1)
                    return {"time": time, "total_time": bottom}
                purpose, time, bottom = vsplit(screen, 1, 2, 1)
                return {"purpose": purpose, "time": time, "total_time": bottom}
        else:
            raise ValueError(f"Invalid scene: {self}")


app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    # fmt: off
    initial_timer: Annotated[str, Argument(help="The initial timer duration.")] = "5m",
    bell: Annotated[Path, Option(help="Path to the bell sound file.")] = BELL,
    ring_every: Annotated[int, Option(help="The time between rings, in seconds.")] = 20,
    ring_count: Annotated[int, Option(help="Number of rings played when the time is up.")] = -1,
    font: Annotated[Path, Option(help="Path to the font for all text.")] = FONT,
    background_color: tuple[int, int, int] = (0, 0, 0),
    timer_color: tuple[int, int, int] = (255, 224, 145),
    timer_up_color: tuple[int, int, int] = (255, 0, 0),
    purpose_color: tuple[int, int, int] = (183, 255, 183),
    total_time_color: tuple[int, int, int] = (183, 183, 255),
    window_position: tuple[int, int] = (-5, -5),
    window_size: tuple[int, int] = (180, 70),
    history_file: Annotated[Path, Option(help="Path to the file where the purpose history is stored.")] = Path("~/.pucoti_history"),
    # fmt: on
) -> None:
    """
    Stay on task with PUCOTI, a countdown timer built for simplicity and purpose.

    Help is available by pressing h or ?.
    """

    global FONT
    FONT = font
    history_file = history_file.expanduser()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    pygame.init()
    pygame.mixer.init()
    pygame.key.set_repeat(300, 20)

    pygame.print_debug_info()
    window = sdl2.Window("DTimer", window_size, borderless=True, always_on_top=True)
    window.get_surface().fill((0, 0, 0))
    window.flip()

    screen = window.get_surface()
    clock = pygame.time.Clock()

    position = 0
    place_window(window, *window_position)

    initial_duration = human_duration(initial_timer)
    start = time()
    timer = initial_duration
    last_rung = 0
    nb_rings = 0

    purpose = ""
    purpose_history = []

    last_scene = None
    scene = Scene.MAIN

    while True:
        last_scene = scene
        for event in pygame.event.get():
            if event.type == QUIT:
                sys.exit()
            elif event.type == KEYDOWN:
                if scene in (Scene.HELP, Scene.PURPOSE_HISTORY):
                    scene = Scene.MAIN
                if scene == Scene.ENTERING_PURPOSE:
                    if event.key == K_BACKSPACE:
                        purpose = purpose[:-1]
                    elif event.key in (K_RETURN, K_KP_ENTER, K_ESCAPE):
                        scene = Scene.MAIN
                    elif event.unicode:
                        purpose += event.unicode
                elif event.key == K_j:
                    timer -= 60
                elif event.key == K_k:
                    timer += 60
                elif event.key == K_r:
                    # +1 to more likely show visually round time -> more satisfying
                    timer = initial_duration + (time() - start) + 1
                elif event.key == K_MINUS:
                    window.size = (window.size[0] / WINDOW_SCALE, window.size[1] / WINDOW_SCALE)
                elif event.key == K_EQUALS:
                    window.size = (window.size[0] * WINDOW_SCALE, window.size[1] * WINDOW_SCALE)
                elif event.key == K_p:
                    position = (position + 1) % len(POSITIONS)
                    place_window(window, *POSITIONS[position])
                elif event.key in (K_RETURN, K_KP_ENTER):
                    scene = Scene.ENTERING_PURPOSE
                elif event.key in (K_h, K_QUESTION):
                    scene = Scene.HELP
                elif event.key == K_l:
                    scene = Scene.PURPOSE_HISTORY

        if last_scene == Scene.ENTERING_PURPOSE and scene != last_scene:
            if purpose and (not purpose_history or purpose != purpose_history[-1].text):
                purpose_history.append(Purpose(purpose, time()))
                with history_file.open("a") as f:
                    f.write(json.dumps(purpose_history[-1].__dict__) + "\n")

        layout = scene.mk_layout(window.size, bool(purpose))

        screen.fill(background_color)

        # Render purpose, if there is space.
        if purpose_rect := layout.get("purpose"):
            t = text(purpose, purpose_rect.size, purpose_color)
            r = screen.blit(t, t.get_rect(center=purpose_rect.center))
            if scene == Scene.ENTERING_PURPOSE and (time() % 1) < 0.7:
                if r.height == 0:
                    r.height = purpose_rect.height
                if r.right >= purpose_rect.right:
                    r.right = purpose_rect.right - 3
                pygame.draw.line(screen, purpose_color, r.topright, r.bottomright, 2)

        # Render time.
        if time_rect := layout.get("time"):
            remaining = timer - (time() - start)
            color = timer_up_color if remaining < 0 else timer_color
            t = text(fmt_time(abs(remaining)), time_rect.size, color, monospaced_time=True)
            screen.blit(t, t.get_rect(center=time_rect.center))

        if total_time_rect := layout.get("total_time"):
            t = text(
                fmt_time(time() - start),
                total_time_rect.size,
                total_time_color,
                monospaced_time=True,
            )
            screen.blit(t, t.get_rect(center=total_time_rect.center))

        if help_rect := layout.get("help"):
            screen.fill(background_color)
            t = text(HELP, help_rect.size, timer_color)
            screen.blit(t, t.get_rect(center=help_rect.center))

        if purpose_history_rect := layout.get("purpose_history"):
            screen.fill(background_color)
            t = "\n".join(f"({fmt_time(p.timestamp - start)}) {p.text}" for p in purpose_history)
            t = text("HISTORY\n" + t, purpose_history_rect.size, purpose_color)
            screen.blit(t, t.get_rect(center=purpose_history_rect.center))

        # Ring the bell if the time is up.
        if remaining < 0 and time() - last_rung > ring_every and nb_rings != ring_count:
            play(bell)
            last_rung = time()
            nb_rings += 1
        elif remaining > 0:
            nb_rings = 0

        window.flip()
        clock.tick(60)


if __name__ == "__main__":
    app()
