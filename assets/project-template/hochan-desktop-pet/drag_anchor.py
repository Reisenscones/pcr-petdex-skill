"""Hand tracking and visible sprite centering for drag and drop."""


def hand_anchor(clip, frame_index, mirrored=False):
    x, y = clip.frames.specs[frame_index]['drag_anchor']
    if mirrored:
        # PIL flips pixel centres around x=319.5, then compose shifts by 180.
        x = 639 - x + 180
    return x, y


def window_at_hand(cursor, anchor, scale):
    return tuple(round(cursor[i] - anchor[i]*scale) for i in (0, 1))


def hand_lock_offset(frames, index, mirrored=False):
    """Move the animated palm onto frame zero before physical rasterization."""
    origin = frames.specs[0].get('drag_anchor')
    current = frames.specs[index].get('drag_anchor')
    if origin is None or current is None:
        return 0, 0
    return ((origin[0]-current[0]) * (-1 if mirrored else 1), origin[1]-current[1])


class DragFacing:
    """Confirm reversals by both distance and time, ignoring small hand tremors."""
    distance = 12  # Logical pixels, scaled with the pet and monitor DPI.
    settle_seconds = .06

    def __init__(self, x, direction):
        self.direction = direction
        self.extreme = x
        self.reverse_since = None

    def update(self, x, now, scale):
        progress = (x - self.extreme) * self.direction
        if progress >= 0:
            self.extreme = x
            self.reverse_since = None
        else:
            if self.reverse_since is None:
                self.reverse_since = now
            if -progress >= self.distance * scale and now - self.reverse_since >= self.settle_seconds:
                self.direction = -self.direction
                self.extreme = x
                self.reverse_since = None
        return self.direction


def visible_frame_center(frame, direction=-1):
    """Use the visible bounds plus the calibration for the last drag direction."""
    bounds = frame.getchannel('A').getbbox()
    if bounds is None:
        return frame.width / 2, frame.height / 2
    offset_x = 43 if direction < 0 else -43
    return (bounds[0] + bounds[2]) / 2 - offset_x, (bounds[1] + bounds[3]) / 2 - 30
