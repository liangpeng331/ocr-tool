import sys
import os
import subprocess
import pyperclip
from datetime import datetime
from Foundation import NSObject, NSData, NSPoint, NSSize
from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory,
    NSStatusBar, NSVariableStatusItemLength,
    NSImage, NSMakeSize, NSColor, NSFont, NSMenu, NSMenuItem,
    NSBitmapImageRep, NSWindow, NSView, NSBackingStoreBuffered,
    NSBorderlessWindowMask, NSNonactivatingPanelMask,
    NSTrackingMouseMoved, NSTrackingActiveAlways,
    NSTrackingArea, NSTrackingMouseEnteredAndExited,
    NSTrackingCursorUpdate,
    NSLeftMouseDown, NSLeftMouseUp, NSLeftMouseDragged,
    NSKeyDown, NSScreen, NSRunLoop, NSDefaultRunLoopMode,
    NSMakeRect, NSZeroRect, NSCursor, NSWindow,
)
import AppKit
import Quartz
import objc
from rapidocr_onnxruntime import RapidOCR

# 文件日志
LOG = "/tmp/ocr_debug.log"
def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    try:
        sys.stderr.write(f"[{ts}] {msg}\n")
        sys.stderr.flush()
    except (UnicodeEncodeError, OSError):
        pass

# ----------------- OCR 引擎 -----------------
try:
    ocr_engine = RapidOCR(
        use_angle_cls=False,   # 截图文字通常水平，跳过角度分类以提速
        min_height=15,         # 识别更小的文字（UI 小字等）
        text_score=0.4,        # 适当降低阈值提高召回率
    )
    log("OCR引擎就绪")
except Exception as e:
    log(f"OCR引擎失败: {e}")
    ocr_engine = None

# ----------------- 全屏截图（无需屏幕录制权限） -----------------
def capture_full_screen():
    """使用 CGDisplayCreateImage 捕获主显示器"""
    display_id = Quartz.CGMainDisplayID()
    cg_image = Quartz.CGDisplayCreateImage(display_id)
    if cg_image is None:
        return None

    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)

    bitmap = NSBitmapImageRep.alloc().initWithCGImage_(cg_image)
    png_data = bitmap.representationUsingType_properties_(4, None)  # NSPNGFileType

    temp_path = "/tmp/mac_ocr_fullscreen.png"
    png_data.writeToFile_atomically_(temp_path, True)

    return temp_path, width, height

# ----------------- 原生 NSStatusBar -----------------
def setup_statusbar(ocr_action):
    image = NSImage.alloc().initWithSize_(NSMakeSize(20, 20))
    image.lockFocus()
    path = objc.lookUpClass('NSBezierPath').bezierPathWithOvalInRect_(((2, 2), (16, 16)))
    NSColor.colorWithRed_green_blue_alpha_(0, 0.48, 1, 1).setFill()
    path.fill()

    font = NSFont.fontWithName_size_("PingFang SC", 10)
    color = NSColor.whiteColor()
    text_attr = objc.lookUpClass('NSMutableDictionary').dictionary()
    text_attr.setObject_forKey_(font, AppKit.NSFontAttributeName)
    text_attr.setObject_forKey_(color, AppKit.NSForegroundColorAttributeName)
    objc.lookUpClass('NSString').stringWithString_("字").drawAtPoint_withAttributes_((3, 2), text_attr)
    image.unlockFocus()

    status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    status_item.button().setImage_(image)
    status_item.button().setToolTip_("OCR 截图识别 - 按 Cmd+Shift+O 或点击图标")

    menu = NSMenu.alloc().init()

    # 手动触发菜单项
    ocr_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "截图识别 (Cmd+Shift+O)", "performOCR:", ""
    )
    menu.addItem_(ocr_item)

    menu.addItem_(NSMenuItem.separatorItem())
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("退出 OCR 工具", "terminate:", "q")
    menu.addItem_(quit_item)
    status_item.setMenu_(menu)

    # 点击状态栏图标也触发 OCR
    status_item.button().setAction_("performOCR:")
    status_item.button().setTarget_(ocr_action)

    return status_item

# ----------------- CGEventTap 全局热键 -----------------
def setup_cgevent_tap(callback):
    kVK_ANSI_O = 0x1F
    _state = {"cmd": False, "shift": False, "count": 0}
    _tap_ref = [None]

    def _cb(proxy, event_type, event, user_info):
        try:
            if event_type == Quartz.kCGEventTapDisabledByTimeout:
                log("CGEventTap 被系统禁用，正在重新启用...")
                if _tap_ref[0] is not None:
                    Quartz.CGEventTapEnable(_tap_ref[0], True)
                return event
            elif event_type == Quartz.kCGEventTapDisabledByUserInput:
                log("CGEventTap 被用户输入禁用，正在重新启用...")
                if _tap_ref[0] is not None:
                    Quartz.CGEventTapEnable(_tap_ref[0], True)
                return event

            if event_type == Quartz.kCGEventFlagsChanged:
                flags = Quartz.CGEventGetFlags(event)
                _state["cmd"] = bool(flags & Quartz.kCGEventFlagMaskCommand)
                _state["shift"] = bool(flags & Quartz.kCGEventFlagMaskShift)

            elif event_type == Quartz.kCGEventKeyDown:
                flags = Quartz.CGEventGetFlags(event)
                has_cmd = _state["cmd"] or bool(flags & Quartz.kCGEventFlagMaskCommand)
                has_shift = _state["shift"] or bool(flags & Quartz.kCGEventFlagMaskShift)
                if has_cmd and has_shift:
                    keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                    if keycode == kVK_ANSI_O:
                        _state["count"] += 1
                        _state["swallow_events"] = True
                        log(f"CGEventTap 热键触发 #{_state['count']}")
                        callback()
                        return None  # 吞掉事件，阻止传递到前台应用

            elif event_type == Quartz.kCGEventKeyUp:
                if _state.get("swallow_events"):
                    keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                    if keycode == kVK_ANSI_O:
                        _state["swallow_events"] = False
                        return None  # 同步吞掉对应的 key-up
        except Exception:
            pass
        return event

    mask = (Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) |
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged))

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionDefault,
        mask,
        _cb,
        None
    )

    if tap is None:
        log("CGEventTap 创建失败！请检查辅助功能权限")
        return None

    _tap_ref[0] = tap

    source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    run_loop = Quartz.CFRunLoopGetCurrent()
    Quartz.CFRunLoopAddSource(run_loop, source, Quartz.kCFRunLoopCommonModes)

    Quartz.CGEventTapEnable(tap, True)
    log("CGEventTap 热键监听已启动 (Cmd+Shift+O)")
    return tap

# ----------------- 选区叠加层（纯原生 Cocoa） -----------------
class SelectionView(NSView):
    """自定义 NSView：绘制截图暗色遮罩 + 选择框"""

    def init(self):
        self = objc.super(SelectionView, self).init()
        if self is None:
            return None
        self._origin = NSPoint(0, 0)
        self._current = NSPoint(0, 0)
        self._selecting = False
        self._overlay_color = NSColor.colorWithRed_green_blue_alpha_(0, 0, 0, 0.47)
        self._border_color = NSColor.colorWithRed_green_blue_alpha_(0, 0.59, 1.0, 0.86)
        self._image_path = None
        self._img_width = 1
        self._img_height = 1
        return self

    def setImage_width_height_(self, path, w, h):
        self._image_path = path
        self._img_width = w
        self._img_height = h

    @objc.python_method
    def _toImageRect(self, view_rect):
        """将 AppKit 视图坐标 (y=0 在底部) 转换为图片坐标 (y=0 在顶部)"""
        bw = self.bounds().size.width
        bh = self.bounds().size.height
        x_scale = self._img_width / bw if bw > 0 else 1
        y_scale = self._img_height / bh if bh > 0 else 1
        img_x = int(view_rect.origin.x * x_scale)
        img_y = int(self._img_height - (view_rect.origin.y + view_rect.size.height) * y_scale)
        img_w = max(1, int(view_rect.size.width * x_scale))
        img_h = max(1, int(view_rect.size.height * y_scale))
        return (img_x, img_y, img_w, img_h)

    def drawRect_(self, rect):
        # 绘制原始截图
        if self._image_path:
            img = NSImage.alloc().initWithContentsOfFile_(self._image_path)
            if img:
                img.drawInRect_(self.bounds())

        # 半透明遮罩
        self._overlay_color.setFill()
        AppKit.NSRectFill(self.bounds())

        # 挖空选择区域
        if self._selecting or (self._origin.x != self._current.x or self._origin.y != self._current.y):
            sel_rect = self._selectionRect()
            if sel_rect.size.width > 0 and sel_rect.size.height > 0:
                # 清除遮罩（绘制原始图像区域）
                if self._image_path:
                    img = NSImage.alloc().initWithContentsOfFile_(self._image_path)
                    if img:
                        # NSImage 坐标系与视图一致 (y=0 在底部)，直接映射，不需要翻转
                        bw = self.bounds().size.width
                        bh = self.bounds().size.height
                        x_scale = self._img_width / bw if bw > 0 else 1
                        y_scale = self._img_height / bh if bh > 0 else 1
                        src_x = int(sel_rect.origin.x * x_scale)
                        src_y = int(sel_rect.origin.y * y_scale)
                        src_w = max(1, int(sel_rect.size.width * x_scale))
                        src_h = max(1, int(sel_rect.size.height * y_scale))
                        src_rect = NSMakeRect(src_x, src_y, src_w, src_h)
                        img.drawInRect_fromRect_operation_fraction_(sel_rect, src_rect, AppKit.NSCompositingOperationSourceOver, 1.0)

                # 选择框边框
                self._border_color.setStroke()
                path = AppKit.NSBezierPath.bezierPathWithRect_(sel_rect)
                path.setLineWidth_(2.0)
                path.stroke()

    def _selectionRect(self):
        x = min(self._origin.x, self._current.x)
        y = min(self._origin.y, self._current.y)
        w = abs(self._current.x - self._origin.x)
        h = abs(self._current.y - self._origin.y)
        return NSMakeRect(x, y, w, h)

    def resetCursorRects(self):
        self.addCursorRect_cursor_(self.bounds(), crosshair_cursor())

    def cursorUpdate_(self, event):
        crosshair_cursor().set()

    def mouseDown_(self, event):
        self._origin = self.convertPoint_fromView_(event.locationInWindow(), None)
        self._current = self._origin
        self._selecting = True
        self.setNeedsDisplay_(True)

    def mouseDragged_(self, event):
        if self._selecting:
            self._current = self.convertPoint_fromView_(event.locationInWindow(), None)
            self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        if self._selecting:
            self._selecting = False
            self._current = self.convertPoint_fromView_(event.locationInWindow(), None)
            sel = self._selectionRect()
            if sel.size.width >= 10 and sel.size.height >= 10:
                self._selection_rect = self._toImageRect(sel)
            else:
                self._selection_rect = None
            self.window().orderOut_(None)  # 隐藏窗口（不触发 close 回调）

    def acceptsFirstResponder(self):
        return True

    def keyDown_(self, event):
        if event.keyCode() == 53:  # Escape
            self._selection_rect = None
            self.window().orderOut_(None)

    def hasSelection(self):
        return hasattr(self, '_selection_rect') and self._selection_rect is not None

    def selectionRect(self):
        return getattr(self, '_selection_rect', None)

class OverlayWindow(NSWindow):
    """自定义窗口：允许无边框窗口成为 key window，以支持光标追踪"""

    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True


def _make_crosshair_cursor():
    """创建一个细十字光标，类似截图工具的风格"""
    size = 24
    image = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    image.lockFocus()

    # 细十字线
    NSColor.blackColor().colorWithAlphaComponent_(0.8).setStroke()
    path = AppKit.NSBezierPath.bezierPath()
    path.setLineWidth_(1.0)

    mid = size / 2.0
    gap = 4.0
    # 上
    path.moveToPoint_((mid, size))
    path.lineToPoint_((mid, mid + gap))
    # 下
    path.moveToPoint_((mid, 0))
    path.lineToPoint_((mid, mid - gap))
    # 左
    path.moveToPoint_((0, mid))
    path.lineToPoint_((mid - gap, mid))
    # 右
    path.moveToPoint_((size, mid))
    path.lineToPoint_((mid + gap, mid))
    path.stroke()

    # 中心小圆点
    dot = AppKit.NSBezierPath.bezierPathWithOvalInRect_(((mid - 1.5, mid - 1.5), (3, 3)))
    NSColor.blackColor().colorWithAlphaComponent_(0.9).setFill()
    dot.fill()

    # 白色描边让光标在深色背景上也可见
    NSColor.whiteColor().colorWithAlphaComponent_(0.6).setStroke()
    path2 = AppKit.NSBezierPath.bezierPath()
    path2.setLineWidth_(1.0)
    # 偏移 1px 的白色外层
    for (x1, y1), (x2, y2) in [
        ((mid + 1, size), (mid + 1, mid + gap)),
        ((mid + 1, 0), (mid + 1, mid - gap)),
        ((0, mid + 1), (mid - gap, mid + 1)),
        ((size, mid + 1), (mid + gap, mid + 1)),
    ]:
        path2.moveToPoint_((x1, y1))
        path2.lineToPoint_((x2, y2))
    path2.stroke()

    image.unlockFocus()
    return NSCursor.alloc().initWithImage_hotSpot_(image, (mid, mid))

_crosshair_cursor = None

def crosshair_cursor():
    global _crosshair_cursor
    if _crosshair_cursor is None:
        _crosshair_cursor = _make_crosshair_cursor()
    return _crosshair_cursor


def show_overlay(image_path, img_w, img_h):
    """显示原生全屏叠加层，返回选区 (x, y, w, h) 或 None"""
    screen = NSScreen.mainScreen()
    screen_frame = screen.frame()

    # 创建无边框全屏窗口（使用自定义子类以支持 key window 和光标追踪）
    window = OverlayWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        screen_frame,
        NSBorderlessWindowMask | NSNonactivatingPanelMask,
        NSBackingStoreBuffered,
        False
    )
    window.setLevel_(Quartz.kCGScreenSaverWindowLevel)
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.clearColor())
    window.setHasShadow_(False)
    window.setIgnoresMouseEvents_(False)
    window.setAcceptsMouseMovedEvents_(True)
    window.makeKeyAndOrderFront_(None)

    # 设置自定义视图 + 光标追踪区域
    view = SelectionView.alloc().init()
    view.setImage_width_height_(image_path, img_w, img_h)
    window.setContentView_(view)
    window.makeFirstResponder_(view)

    tracking_opts = NSTrackingCursorUpdate | NSTrackingActiveAlways | NSTrackingMouseMoved
    tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
        view.bounds(), tracking_opts, view, None
    )
    view.addTrackingArea_(tracking_area)

    # 运行本地事件循环，直到窗口隐藏或 ESC
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    crosshair_cursor().set()

    try:
        while window.isVisible():
            event = NSApplication.sharedApplication().nextEventMatchingMask_untilDate_inMode_dequeue_(
                0xFFFFFFFFFFFFFFFF,  # NSAnyEventMask
                AppKit.NSDate.distantFuture(),
                NSDefaultRunLoopMode,
                True
            )
            if event is None:
                continue
            try:
                if event.window() == window:
                    window.sendEvent_(event)
                else:
                    NSApplication.sharedApplication().sendEvent_(event)
            except Exception:
                pass

            # 每次处理后检查选择是否完成
            if hasattr(view, '_selection_rect'):
                break
    finally:
        pass

    result = view.selectionRect()
    window.orderOut_(None)
    # 不调用 window.close()，将窗口引用暂存以防止 ObjC 对象被提前释放导致 segfault
    _overlay_cache.append((window, view))
    if len(_overlay_cache) > 2:
        _overlay_cache.pop(0)
    return result

# 防止 overlay 窗口被 GC 提前回收
_overlay_cache = []

# ----------------- 同行合并 -----------------
def merge_lines(ocr_result):
    if not ocr_result:
        return ""

    heights = []
    for item in ocr_result:
        bbox = item[0]
        if bbox and len(bbox) >= 4:
            h = abs(bbox[0][1] - bbox[3][1])
            if h > 0:
                heights.append(h)

    if not heights:
        return "\n".join(item[1] for item in ocr_result)

    heights.sort()
    line_height = heights[len(heights) // 2]
    threshold = line_height * 0.6

    blocks = []
    for item in ocr_result:
        bbox = item[0]
        text = item[1]
        if bbox and len(bbox) >= 4:
            center_y = (bbox[0][1] + bbox[3][1]) / 2
            left_x = bbox[0][0]
            blocks.append((center_y, left_x, text))

    blocks.sort(key=lambda b: b[0])

    lines = []
    current_line = [blocks[0]]
    for block in blocks[1:]:
        if abs(block[0] - current_line[-1][0]) < threshold:
            current_line.append(block)
        else:
            lines.append(current_line)
            current_line = [block]
    lines.append(current_line)

    merged = []
    for line in lines:
        line.sort(key=lambda b: b[1])
        merged.append(" ".join(b[2] for b in line))

    return "\n".join(merged)

# ----------------- 主程序 -----------------
class OCRApp(NSObject):
    def init(self):
        self = objc.super(OCRApp, self).init()
        if self is None:
            return None
        self._event_tap = None
        self._status_item = None
        return self

    def applicationDidFinishLaunching_(self, notification):
        self._status_item = setup_statusbar(self)
        self._event_tap = setup_cgevent_tap(self._on_hotkey)
        if self._event_tap is None:
            log("全局热键不可用，请点击菜单栏图标触发 OCR")
        else:
            log("程序就绪 - 按 Cmd+Shift+O 或点击菜单栏图标开始截图识别")

    def performOCR_(self, sender):
        self._trigger_selection()

    @objc.python_method
    def _on_hotkey(self):
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "performOCR:", None, False
        )

    def _trigger_selection(self):
        log("trigger_selection 开始")
        fullscreen_path = None
        crop_path = None
        try:
            # 重新启用 event tap
            if self._event_tap is not None:
                Quartz.CGEventTapEnable(self._event_tap, True)

            # 步骤1: 捕获全屏
            result = capture_full_screen()
            if result is None:
                log("全屏截图失败")
                return
            fullscreen_path, img_w, img_h = result
            log(f"全屏截图: {img_w}x{img_h}")

            # 步骤2: 显示原生叠加层，等待用户选择
            selection = show_overlay(fullscreen_path, img_w, img_h)
            if selection is None:
                log("用户取消选择")
                return
            x, y, w, h = selection
            log(f"选中区域: ({x}, {y}, {w}x{h})")

            # 步骤3: 裁剪选中区域
            from PIL import Image
            img = Image.open(fullscreen_path)
            cropped = img.crop((x, y, x + w, y + h))
            crop_path = "/tmp/mac_ocr_crop.png"
            cropped.save(crop_path, "PNG")
            img.close()

            # 步骤4: OCR 识别
            if ocr_engine:
                try:
                    ocr_result, elapse = ocr_engine(crop_path)
                    if ocr_result:
                        merged_text = merge_lines(ocr_result)
                        pyperclip.copy(merged_text)
                        self._show_notification("OCR 识别成功", "文本已复制到剪贴板！")
                        total_time = sum(elapse) if isinstance(elapse, list) else (elapse or 0)
                        log(f"OCR 成功: {merged_text.count(chr(10)) + 1} 行, 耗时 {total_time:.2f}s")
                    else:
                        self._show_notification("OCR 提示", "未在该区域识别出文字")
                        log("OCR: 未识别出文字")
                except Exception as e:
                    self._show_notification("OCR 错误", f"识别过程出错: {e}")
                    log(f"OCR 错误: {e}")
            else:
                self._show_notification("错误", "OCR 引擎未准备就绪")

        except Exception as e:
            import traceback
            log(f"ERROR: {e}")
            traceback.print_exc()
        finally:
            for p in [fullscreen_path, crop_path]:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        log("trigger_selection 结束")

    def _show_notification(self, title, message):
        try:
            subprocess.Popen(
                ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

# ----------------- 入口 -----------------
if __name__ == "__main__":
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    ocr_app = OCRApp.alloc().init()
    app.setDelegate_(ocr_app)

    app.run()
    log(">>> NSApp.run() 返回了，程序即将退出 <<<")
