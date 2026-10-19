"""Two reusable, GUI-owned DIB surfaces for atomic layered-window uploads."""
import ctypes

import numpy as np

import win32_api as api
from frame_renderer import PreparedFrame


class LayeredBuffers:
    def __init__(self):
        self.surfaces = []
        self.size = None
        self.back = 0

    def close(self):
        for memory_dc, bitmap, previous, bits in self.surfaces:
            api.gdi32.SelectObject(memory_dc, previous)
            api.gdi32.DeleteObject(bitmap)
            api.gdi32.DeleteDC(memory_dc)
        self.surfaces.clear()
        self.size = None

    def _allocate(self, width, height, screen_dc):
        self.close()
        info = api.BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(api.BITMAPINFOHEADER)
        info.bmiHeader.biWidth, info.bmiHeader.biHeight = width, -height
        info.bmiHeader.biPlanes, info.bmiHeader.biBitCount = 1, 32
        info.bmiHeader.biCompression = api.BI_RGB
        try:
            for _ in range(2):
                dc = api.gdi32.CreateCompatibleDC(screen_dc)
                if not dc:
                    raise ctypes.WinError()
                bits = ctypes.c_void_p()
                bitmap = api.gdi32.CreateDIBSection(dc, ctypes.byref(info), api.DIB_RGB_COLORS,
                                                   ctypes.byref(bits), None, 0)
                if not bitmap:
                    api.gdi32.DeleteDC(dc)
                    raise ctypes.WinError()
                previous = api.gdi32.SelectObject(dc, bitmap)
                self.surfaces.append((dc, bitmap, previous, bits))
        except Exception:
            self.close()
            raise
        self.size, self.back = (width, height), 0

    def _submit(self, hwnd, screen_dc, dc, origin):
        if origin is None:
            rect = api.RECT()
            if not api.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return False
            origin = rect.left, rect.top
        destination = api.POINT(*origin)
        source = api.POINT(0, 0)
        size = api.SIZE(*self.size)
        blend = api.BLENDFUNCTION(api.AC_SRC_OVER, 0, 255, api.AC_SRC_ALPHA)
        if not api.user32.UpdateLayeredWindow(hwnd, screen_dc, ctypes.byref(destination), ctypes.byref(size),
                dc, ctypes.byref(source), 0, ctypes.byref(blend), api.ULW_ALPHA):
            raise ctypes.WinError()
        return True

    def move(self, hwnd, origin):
        """Submit the displayed surface and its new origin together."""
        if not self.surfaces:
            return False
        screen_dc = api.user32.GetDC(None)
        try:
            # Keep the front DIB: a newly prepared animation frame has not yet
            # been displayed and must not participate in this pointer event.
            dc = self.surfaces[1-self.back][0]
            return self._submit(hwnd, screen_dc, dc, origin)
        finally:
            api.user32.ReleaseDC(None, screen_dc)

    def present(self, hwnd, pixels, width, height, origin=None):
        screen_dc = api.user32.GetDC(None)
        try:
            if self.size != (width, height):
                self._allocate(width, height, screen_dc)
            dc, bitmap, previous, bits = self.surfaces[self.back]
            length = width*height*4
            if isinstance(pixels, PreparedFrame):
                ctypes.memset(bits, 0, length)
                left, top = pixels.origin
                sw, sh = pixels.size
                x0, y0 = max(0, left), max(0, top)
                x1, y1 = min(width, left+sw), min(height, top+sh)
                if x1 > x0 and y1 > y0:
                    target = np.ctypeslib.as_array((ctypes.c_ubyte*length).from_address(bits.value)).reshape(height,width,4)
                    source = np.frombuffer(pixels.pixels, dtype=np.uint8).reshape(sh,sw,4)
                    target[y0:y1,x0:x1] = source[y0-top:y1-top,x0-left:x1-left]
            else:
                if len(pixels) != length:
                    raise ValueError('Pixel buffer dimensions do not match the DIB')
                ctypes.memmove(bits, pixels, length)
            if self._submit(hwnd, screen_dc, dc, origin):
                self.back = 1-self.back
        finally:
            api.user32.ReleaseDC(None, screen_dc)
