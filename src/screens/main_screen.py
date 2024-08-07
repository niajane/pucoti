import re
from time import time

import pygame
import pygame.locals as pg
from luckypot import GFX

from .. import time_utils
from .. import pygame_utils
from .. import constants
from ..callback import CountdownCallback
from .base_screen import PucotiScreen, Context
from . import help_screen, purpose_history_screen


class MainScreen(PucotiScreen):
    def __init__(self, ctx: Context) -> None:
        super().__init__()

        self.initial_duration = time_utils.human_duration(ctx.config.initial_timer)
        self.start = round(time())
        self.timer_end = self.initial_duration
        self.last_rung = 0
        self.nb_rings = 0
        self.callbacks = [CountdownCallback(cfg) for cfg in ctx.config.run_at]

        self.hide_totals = False

        self.purpose_editor = PurposeEditor(ctx)

        ctx.set_purpose("")

    @property
    def purpose(self):
        return self.ctx.purpose_history[-1].text

    @property
    def purpose_start_time(self):
        return round(self.ctx.purpose_history[-1].timestamp)

    def on_exit(self):
        self.ctx.set_purpose("")

    def paused_logic(self):
        remaining = self.timer_end - (time() - self.start)
        if (
            remaining < 0
            and time() - self.last_rung > self.config.ring_every
            and self.nb_rings != self.config.ring_count
        ):
            self.last_rung = time()
            self.nb_rings += 1
            pygame_utils.play(self.config.bell)
            if self.config.restart:
                # self.timer_end = self.initial_duration + (round(time() + 0.5) - self.start)
                self.timer_end = time_utils.compute_timer_end(self.initial_duration, self.start)

        elif remaining > 0:
            self.nb_rings = 0
            self.last_rung = 0

        # And execute the callbacks.
        for callback in self.callbacks:
            callback.update(self.timer_end - (time() - self.start))

        return super().paused_logic()

    def logic(self):
        self.paused_logic()
        return super().logic()

    def handle_event(self, event) -> bool:
        if self.purpose_editor.handle_event(event):
            return True

        if event.type != pg.KEYDOWN:
            return super().handle_event(event)

        # We only handle keydown events from here on.
        match event.key:
            case pg.K_j:
                self.timer_end -= 60 * 5 if pygame_utils.shift_is_pressed(event) else 60
            case pg.K_k:
                self.timer_end += 60 * 5 if pygame_utils.shift_is_pressed(event) else 60
            case number if number in constants.NUMBER_KEYS:
                new_duration = 60 * pygame_utils.get_number_from_key(number)
                if pygame_utils.shift_is_pressed(event):
                    new_duration *= 10
                self.timer_end = time_utils.compute_timer_end(new_duration, self.start)
                self.initial_duration = new_duration
            case pg.K_r:
                self.timer_end = time_utils.compute_timer_end(self.initial_duration, self.start)
            case pg.K_t:
                self.hide_totals = not self.hide_totals
            case pg.K_h | pg.K_QUESTION:
                self.push_state(help_screen.HelpScreen())
            case pg.K_l:
                self.push_state(purpose_history_screen.PurposeHistoryScreen())
            case _:
                return super().handle_event(event)
        return True

    def layout(self):
        rect = self.available_rect()
        height = rect.height

        if self.purpose_editor.editing:
            if height < 60:
                layout = {"purpose": 1}
            elif height < 80:
                layout = {"purpose": 2, "time": 1}
            else:
                layout = {"purpose": 2, "time": 1, "totals": 0.5}
        else:
            if height < 60:
                layout = {"time": 1}
            elif height < 80:
                layout = {"purpose": 1, "time": 2}
            else:
                layout = {"purpose": 1, "time": 2, "totals": 1}

            if not self.purpose:
                layout["time"] += layout.pop("purpose", 0)

        if self.hide_totals:
            layout.pop("totals", None)

        rects = {
            k: rect
            for k, rect in zip(layout.keys(), pygame_utils.split_rect(rect, *layout.values()))
        }

        # Bottom has horizontal layout with [total_time | purpose_time]
        if total_time_rect := rects.pop("totals", None):
            rects["total_time"], _, rects["purpose_time"] = pygame_utils.split_rect(
                total_time_rect, 1, 0.2, 1, horizontal=True
            )

        return rects

    def draw(self, gfx: help_screen.GFX):
        super().draw(gfx)
        layout = self.layout()

        # Render time.
        remaining = self.timer_end - (time() - self.start)
        if time_rect := layout.get("time"):
            color = self.config.color.timer_up if remaining < 0 else self.config.color.timer
            t = self.config.font.big.render(
                time_utils.fmt_duration(abs(remaining)),
                time_rect.size,
                color,
                monospaced_time=True,
            )
            gfx.blit(t, center=time_rect.center)

        if total_time_rect := layout.get("total_time"):
            t = self.config.font.normal.render(
                time_utils.fmt_duration(time() - self.start),
                total_time_rect.size,
                self.config.color.total_time,
                monospaced_time=True,
            )
            gfx.blit(t, midleft=total_time_rect.midleft)

        if purpose_time_rect := layout.get("purpose_time"):
            t = self.config.font.normal.render(
                time_utils.fmt_duration(time() - self.purpose_start_time),
                purpose_time_rect.size,
                self.config.color.purpose,
                monospaced_time=True,
            )
            gfx.blit(t, midright=purpose_time_rect.midright)

        if purpose_rect := layout.get("purpose"):
            self.purpose_editor.draw(gfx, purpose_rect)


class PurposeEditor:
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        self.purpose = ctx.purpose_history[-1].text
        self.editing = False

    def handle_event(self, event) -> bool:
        if not self.editing:
            if event.type == pg.KEYDOWN and event.key == pg.K_RETURN:
                self.editing = True
                return True
            return False

        if event.type == pg.TEXTINPUT:
            self.purpose += event.text
            return True
        elif event.type == pg.KEYDOWN:
            if event.key == pg.K_BACKSPACE:
                if event.mod & pg.KMOD_CTRL:
                    self.purpose = re.sub(r"\S*\s*$", "", self.purpose)
                else:
                    self.purpose = self.purpose[:-1]
                return True
            elif event.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_ESCAPE):
                self.ctx.set_purpose(self.purpose)
                self.editing = False
                return True

        return False

    def draw(self, gfx: GFX, rect: pygame.Rect):
        t = self.ctx.config.font.normal.render(
            self.purpose, rect.size, self.ctx.config.color.purpose
        )
        r = gfx.blit(t, center=rect.center)
        if self.editing and (time() % 1) < 0.7:
            if r.height == 0:
                r.height = rect.height
            if r.right >= rect.right:
                r.right = rect.right - 3
            pygame.draw.line(gfx.surf, self.ctx.config.color.purpose, r.topright, r.bottomright, 2)
