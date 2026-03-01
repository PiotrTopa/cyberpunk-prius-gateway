import time
import math


# --- Easing Functions ---
# All take t in [0.0, 1.0] and return value in [0.0, 1.0]

def linear(t):
    return t


def ease_in(t):
    """Quadratic ease-in: slow start, fast end."""
    return t * t


def ease_out(t):
    """Quadratic ease-out: fast start, slow end."""
    return t * (2.0 - t)


def ease_in_out(t):
    """Quadratic ease-in-out: smooth start and end."""
    if t < 0.5:
        return 2.0 * t * t
    else:
        return -1.0 + (4.0 - 2.0 * t) * t


def ease_in_cubic(t):
    """Cubic ease-in."""
    return t * t * t


def ease_out_cubic(t):
    """Cubic ease-out."""
    t1 = t - 1.0
    return t1 * t1 * t1 + 1.0


def ease_in_out_cubic(t):
    """Cubic ease-in-out."""
    if t < 0.5:
        return 4.0 * t * t * t
    else:
        t1 = 2.0 * t - 2.0
        return 0.5 * t1 * t1 * t1 + 1.0


# Lookup table for easing function selection
EASING_FUNCTIONS = {
    "linear": linear,
    "in": ease_in,
    "out": ease_out,
    "in_out": ease_in_out,
    "in_cubic": ease_in_cubic,
    "out_cubic": ease_out_cubic,
    "in_out_cubic": ease_in_out_cubic,
}


class Transition:
    """Represents a single value transition with easing."""

    __slots__ = (
        "start_val",
        "end_val",
        "start_ms",
        "duration_ms",
        "easing_fn",
        "done",
    )

    def __init__(self, start_val, end_val, duration_ms, easing_name="linear"):
        self.start_val = float(start_val)
        self.end_val = float(end_val)
        self.start_ms = time.ticks_ms()
        self.duration_ms = max(1, duration_ms)
        self.easing_fn = EASING_FUNCTIONS.get(easing_name, linear)
        self.done = False

    def value(self):
        """
        Calculate current value based on elapsed time and easing.
        Returns (current_value, is_done).
        """
        if self.done:
            return self.end_val, True

        elapsed = time.ticks_diff(time.ticks_ms(), self.start_ms)

        if elapsed >= self.duration_ms:
            self.done = True
            return self.end_val, True

        # Normalized progress [0.0 .. 1.0]
        t = elapsed / self.duration_ms

        # Apply easing
        eased = self.easing_fn(t)

        # Interpolate between start and end
        val = self.start_val + (self.end_val - self.start_val) * eased
        return val, False


class EasingEngine:
    """
    Manages multiple concurrent transitions for PWM channels.
    Each channel can have at most one active transition.
    """

    def __init__(self, num_channels=2):
        self.transitions = [None] * num_channels

    def start(self, channel, current_val, target_val, duration_ms, easing_name="linear"):
        """
        Start a new transition on a channel.
        Replaces any active transition on that channel.

        Args:
            channel: Channel index (0 or 1)
            current_val: Current duty value (0-65535)
            target_val: Target duty value (0-65535)
            duration_ms: Duration of the transition in milliseconds
            easing_name: One of: linear, in, out, in_out, in_cubic, out_cubic, in_out_cubic
        """
        if 0 <= channel < len(self.transitions):
            self.transitions[channel] = Transition(
                current_val, target_val, duration_ms, easing_name
            )

    def cancel(self, channel):
        """Cancel active transition on a channel."""
        if 0 <= channel < len(self.transitions):
            self.transitions[channel] = None

    def cancel_all(self):
        """Cancel all active transitions."""
        for i in range(len(self.transitions)):
            self.transitions[i] = None

    def is_active(self, channel):
        """Check if a channel has an active (non-done) transition."""
        if 0 <= channel < len(self.transitions):
            t = self.transitions[channel]
            return t is not None and not t.done
        return False

    def any_active(self):
        """Check if any channel has an active transition."""
        for t in self.transitions:
            if t is not None and not t.done:
                return True
        return False

    def tick(self):
        """
        Update all active transitions.
        Returns list of (channel, value, is_done) for channels with active transitions.
        """
        results = []
        for i, t in enumerate(self.transitions):
            if t is not None and not t.done:
                val, done = t.value()
                results.append((i, int(val), done))
                if done:
                    # Clean up completed transition
                    self.transitions[i] = None
        return results
