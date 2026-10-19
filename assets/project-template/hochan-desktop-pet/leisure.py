"""Idle routines with injectable monotonic time and randomness."""
import math
import random


class Leisure:
    def __init__(self, now, rng=None):
        self.rng = rng or random.Random()
        self.reset(now)

    def interval(self):
        while True:
            u = max(1e-12, min(1-1e-12, self.rng.random()))
            minutes = 10 + 2.965 * math.sqrt(-2*math.log(u))*math.cos(2*math.pi*self.rng.random())
            if 3 <= minutes <= 30:
                return minutes*60

    def reset(self, now, interval=None, choice=None):
        duration = self.interval() if interval is None else interval
        choice = self.rng.random() if choice is None else choice
        fractions = [2/3] if choice < .4 else [1/3] if choice < .8 else [1/3,2/3] if choice < .9 else []
        self.phase, self.began, self.deadline = 'awake', now, now+duration
        self.idle_actions = [now+duration*f for f in fractions]
        self.sleep_epoch, self.action_epoch = 0, now

    def tick(self, now, eligible):
        if self.phase != 'awake':
            return
        due = any(t <= now for t in self.idle_actions)
        self.idle_actions = [t for t in self.idle_actions if t > now]
        if eligible:
            if now >= self.deadline:
                self.enter(now)
            elif due:
                self.phase, self.action_epoch = 'bowing', now

    def enter(self, now):
        self.phase, self.action_epoch, self.idle_actions = 'entering', now, []

    def cancel(self):
        self.phase = 'awake'

    def click(self, now, wake=None):
        if self.phase not in ('entering','sleeping'):
            return False
        if wake is None:
            wake = self.rng.random() < .5
        if wake:
            self.phase, self.action_epoch = 'waking', now
        return True

    def position(self, clips, now):
        elapsed = now-self.action_epoch
        if self.phase == 'bowing':
            if elapsed >= clips['bow'].total_duration/1000:
                self.phase = 'awake'
            else:
                return 'bow', clips['bow'].frame(elapsed, True)
        if self.phase == 'entering':
            duration = clips['sleep_entry'].total_duration/1000
            if elapsed >= duration:
                self.phase, self.sleep_epoch = 'sleeping', self.action_epoch+duration
            else:
                return 'sleep_entry', clips['sleep_entry'].frame(elapsed, True)
        if self.phase == 'sleeping':
            return 'sleep_body', clips['sleep_body'].frame(now-self.sleep_epoch)
        if self.phase == 'waking':
            key = 'wake' if 'wake' in clips else 'left'
            duration = clips[key].total_duration/1000 * (1 if key == 'wake' else 2)
            if elapsed >= duration:
                self.reset(now)
            else:
                return key, clips[key].frame(elapsed, key == 'wake')
        return None
