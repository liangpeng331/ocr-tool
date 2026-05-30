import sys
import os
import subprocess
import ctypes
import ctypes.util
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
    NSLeftMouseDown, NSLeftMouseUp, NSLeftMouseDragged,
    NSKeyDown, NSScreen, NSRunLoop, NSDefaultRunLoopMode,
    NSMakeRect, NSZeroRect,
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
    ocr_engine = RapidOCR()
    log("OCR引擎就绪 (RapidOCR)")
except Exception as e:
    log(f"OCR引擎失败: {e}")
    ocr_engine = None

# ----------------- Vision OCR（macOS 原生，手写优化） -----------------
def ocr_vision(image_path):
    """使用 macOS Vision 框架识别文字（fast 模式，手写体友好）"""
    from Vision import VNRecognizeTextRequest, VNImageRequestHandler
    from AppKit import NSImage

    ns_img = NSImage.alloc().initWithContentsOfFile_(image_path)
    if ns_img is None:
        return None
    reps = ns_img.representations()
    if not reps:
        return None
    cg_img = reps[0].CGImage()
    if cg_img is None:
        return None

    req = VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en-US"])
    req.setRecognitionLevel_(0)  # 0=fast, 1=accurate。fast 模式对中文渲染文字更准确！
    req.setUsesLanguageCorrection_(True)

    handler = VNImageRequestHandler.alloc().initWithCGImage_options_(cg_img, None)
    success, error = handler.performRequests_error_([req], None)

    if not success or not req.results():
        return None

    # 转换为 RapidOCR 兼容格式: [(bbox, text, confidence), ...]
    results = []
    for obs in req.results():
        top = obs.topCandidates_(1)
        if top:
            text = str(top[0].string())
            confidence = top[0].confidence()
            # Vision 返回归一化坐标 [0,1]，转成像素坐标
            bb = obs.boundingBox()
            # boundingBox 是 (x, y, w, h)，左下角原点
            bbox = [[bb.origin.x, bb.origin.y],
                    [bb.origin.x + bb.size.width, bb.origin.y],
                    [bb.origin.x + bb.size.width, bb.origin.y + bb.size.height],
                    [bb.origin.x, bb.origin.y + bb.size.height]]
            results.append((bbox, text, confidence))
    return results

def ocr_with_fallback(image_path):
    """双引擎 OCR：RapidOCR 主力 + Vision 降级（手写体）"""
    import time

    # 第一步：RapidOCR（印刷体，快速准确）
    if ocr_engine:
        try:
            t0 = time.time()
            rapid_result, elapse = ocr_engine(image_path)
            t1 = time.time()
            if rapid_result:
                # 计算 RapidOCR 平均置信度
                rapid_confs = [item[2] for item in rapid_result if len(item) > 2 and item[2] is not None]
                avg_conf = sum(rapid_confs) / len(rapid_confs) if rapid_confs else 0.5
                log(f"RapidOCR: {len(rapid_result)} 块, 均置信度 {avg_conf:.2f}, 耗时 {t1-t0:.2f}s")
                if avg_conf >= 0.65:
                    return rapid_result  # 印刷体，直接用 RapidOCR 结果
        except Exception as e:
            log(f"RapidOCR 异常: {e}")

    # 第二步：Vision 降级（可能的手写体或 RapidOCR 失败）
    try:
        t0 = time.time()
        vision_result = ocr_vision(image_path)
        t1 = time.time()
        if vision_result:
            vision_confs = [item[2] for item in vision_result]
            avg_conf = sum(vision_confs) / len(vision_confs) if vision_confs else 0
            log(f"Vision: {len(vision_result)} 块, 均置信度 {avg_conf:.2f}, 耗时 {t1-t0:.2f}s")
            return vision_result
    except Exception as e:
        log(f"Vision 异常: {e}")

    return None

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

# ----------------- Carbon 系统热键（主力方案，兼容软件模拟按键） -----------------
def setup_carbon_hotkey(callback):
    """使用 Carbon RegisterEventHotKey 注册系统级全局热键 Cmd+Shift+O。

    CGEventTap 无法捕获 Mac Mouse Fix 等软件通过 Accessibility API 模拟的按键事件，
    而 Carbon 热键注册在系统层面生效，无论按键来自真实键盘还是软件模拟都能触发。
    """
    carbon_path = ctypes.util.find_library('Carbon')
    if not carbon_path:
        log("找不到 Carbon 框架")
        return None

    carbon = ctypes.cdll.LoadLibrary(carbon_path)

    kEventClassKeyboard = 0x6B657962       # 'keyb'
    kEventHotKeyPressed  = 5
    kEventHotKeyReleased = 6
    cmdKey   = 0x0100
    shiftKey = 0x0200
    kVK_ANSI_O = 0x1F

    # Carbon 回调: OSStatus (*)(EventHandlerCallRef, EventRef, void*)
    EventHandlerProcPtr = ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
    )

    class EventTypeSpec(ctypes.Structure):
        _fields_ = [('eventClass', ctypes.c_uint32),
                    ('eventKind',  ctypes.c_uint32)]

    class EventHotKeyID(ctypes.Structure):
        _fields_ = [('signature', ctypes.c_uint32),
                    ('id',        ctypes.c_uint32)]

    _count = [0]

    def _handler(next_handler, event, user_data):
        _count[0] += 1
        log(f"Carbon 热键触发 #{_count[0]}")
        callback()
        return 0  # noErr

    # 保持 Python 引用，防止被 GC 回收导致 C 回调崩溃
    handler_proc = EventHandlerProcPtr(_handler)

    # 获取当前进程的 Carbon 事件目标
    carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
    target = carbon.GetApplicationEventTarget()

    # InstallEventHandler 函数签名
    carbon.InstallEventHandler.argtypes = [
        ctypes.c_void_p,        # EventTargetRef
        EventHandlerProcPtr,    # EventHandlerUPP
        ctypes.c_uint32,        # UInt32 numTypes
        ctypes.c_void_p,        # const EventTypeSpec *
        ctypes.c_void_p,        # void *userData
        ctypes.c_void_p,        # EventHandlerRef *
    ]
    carbon.InstallEventHandler.restype = ctypes.c_int32

    event_types = (EventTypeSpec * 2)()
    event_types[0] = (kEventClassKeyboard, kEventHotKeyPressed)
    event_types[1] = (kEventClassKeyboard, kEventHotKeyReleased)

    handler_ref = ctypes.c_void_p()
    status = carbon.InstallEventHandler(
        target, handler_proc, 2, event_types, None, ctypes.byref(handler_ref)
    )
    if status != 0:
        log(f"Carbon InstallEventHandler 失败 (错误码 {status})")
        return None

    # RegisterEventHotKey 函数签名（注意第三个参数是结构体传值）
    carbon.RegisterEventHotKey.argtypes = [
        ctypes.c_uint32,        # UInt32 inHotKeyCode
        ctypes.c_uint32,        # UInt32 inHotKeyModifiers
        EventHotKeyID,          # EventHotKeyID inHotKeyID (按值传递)
        ctypes.c_void_p,        # EventTargetRef inTarget
        ctypes.c_uint32,        # OptionBits inOptions
        ctypes.c_void_p,        # EventHotKeyRef *outRef
    ]
    carbon.RegisterEventHotKey.restype = ctypes.c_int32

    hotkey_id = EventHotKeyID(1, 1)
    hotkey_ref = ctypes.c_void_p()
    status = carbon.RegisterEventHotKey(
        kVK_ANSI_O,
        cmdKey | shiftKey,
        hotkey_id,
        target,
        0,
        ctypes.byref(hotkey_ref)
    )
    if status != 0:
        log(f"Carbon RegisterEventHotKey 失败 (错误码 {status})，可能被其他程序占用")
        return None

    log("Carbon 系统热键注册成功 (Cmd+Shift+O)")
    return (hotkey_ref, handler_proc)  # 返回引用保持存活


# ----------------- CGEventTap 全局热键（备用方案，仅监听真实键盘） -----------------
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
                if _state["cmd"] and _state["shift"]:
                    keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                    if keycode == kVK_ANSI_O:
                        _state["count"] += 1
                        log(f"CGEventTap 热键触发 #{_state['count']}")
                        callback()
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
                        # 计算源图像中对应的区域
                        bw = self.bounds().size.width
                        bh = self.bounds().size.height
                        x_scale = self._img_width / bw if bw > 0 else 1
                        y_scale = self._img_height / bh if bh > 0 else 1
                        src_rect = NSMakeRect(
                            sel_rect.origin.x * x_scale,
                            sel_rect.origin.y * y_scale,
                            max(1, sel_rect.size.width * x_scale),
                            max(1, sel_rect.size.height * y_scale)
                        )
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
            bw = self.bounds().size.width
            bh = self.bounds().size.height
            x_scale = self._img_width / bw if bw > 0 else 1
            y_scale = self._img_height / bh if bh > 0 else 1
            if sel.size.width >= 10 and sel.size.height >= 10:
                self._selection_rect = (
                    int(sel.origin.x * x_scale),
                    int(sel.origin.y * y_scale),
                    max(1, int(sel.size.width * x_scale)),
                    max(1, int(sel.size.height * y_scale))
                )
            else:
                self._selection_rect = None
            self.window().orderOut_(None)  # 隐藏窗口（不触发 close 回调）

    def keyDown_(self, event):
        if event.keyCode() == 53:  # Escape
            self._selection_rect = None
            self.window().orderOut_(None)

    def hasSelection(self):
        return hasattr(self, '_selection_rect') and self._selection_rect is not None

    def selectionRect(self):
        return getattr(self, '_selection_rect', None)

def show_overlay(image_path, img_w, img_h):
    """显示原生全屏叠加层，返回选区 (x, y, w, h) 或 None"""
    screen = NSScreen.mainScreen()
    screen_frame = screen.frame()

    # 创建无边框全屏窗口
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        screen_frame,
        NSBorderlessWindowMask | NSNonactivatingPanelMask,
        NSBackingStoreBuffered,
        False
    )
    window.setLevel_(Quartz.CGShieldingWindowLevel())
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.clearColor())
    window.setHasShadow_(False)
    window.setIgnoresMouseEvents_(False)
    window.setAcceptsMouseMovedEvents_(True)
    window.makeKeyAndOrderFront_(None)

    # 设置自定义视图
    view = SelectionView.alloc().init()
    view.setImage_width_height_(image_path, img_w, img_h)
    window.setContentView_(view)

    # 运行本地事件循环，直到窗口隐藏或 ESC
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    while window.isVisible():
        event = NSApplication.sharedApplication().nextEventMatchingMask_untilDate_inMode_dequeue_(
            0xFFFFFFFFFFFFFFFF,  # NSAnyEventMask
            AppKit.NSDate.distantFuture(),
            NSDefaultRunLoopMode,
            True
        )
        if event is None:
            continue
        # 如果事件目标是 overlay 窗口，发给它
        try:
            if event.window() == window:
                window.sendEvent_(event)
            else:
                # 传给 NSApp 常规处理
                NSApplication.sharedApplication().sendEvent_(event)
        except Exception:
            pass

        # 每次处理后检查选择是否完成
        if hasattr(view, '_selection_rect'):
            break

    result = view.selectionRect()
    window.orderOut_(None)
    window.close()
    return result

# ----------------- 受鼠标后退键影响的应用 -----------------
# 这些应用的鼠标后退键会触发导航，Mac Mouse Fix 映射鼠标后退为热键后，
# 原始鼠标事件可能仍被 App 接收导致意外后退，需在 OCR 完成后前进恢复。
NAVIGATION_APPS = {
    "com.apple.finder",        # 访达
    "com.apple.Safari",        # Safari
    "com.google.Chrome",       # Chrome
    "com.microsoft.edgemac",   # Edge
    "org.mozilla.firefox",     # Firefox
    "com.apple.systempreferences",  # 系统设置
    "com.apple.AppStore",      # App Store
    "com.brave.Browser",       # Brave
    "com.operasoftware.Opera", # Opera
    "com.arc.Arc",             # Arc Browser
}


def _send_forward_navigation(bundle_id):
    """发送 Cmd+]（前进），抵消鼠标后退键在导航类 App 中的意外后退。

    先短暂延迟确保焦点已归还原 App，再通过 System Events 发送按键。
    """
    import time
    time.sleep(0.15)
    # 先激活目标 App，确保按键发送到正确进程
    subprocess.run(["open", "-b", bundle_id], capture_output=True)
    time.sleep(0.1)
    subprocess.run([
        "osascript", "-e",
        'tell application "System Events" to keystroke "]" using command down'
    ], capture_output=True)


def _frontmost_bundle_id():
    """获取当前前台应用的 Bundle ID"""
    from AppKit import NSWorkspace
    return str(NSWorkspace.sharedWorkspace().frontmostApplication().bundleIdentifier())


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
        self._carbon_hotkey = None
        self._event_tap = None
        self._status_item = None
        return self

    def applicationDidFinishLaunching_(self, notification):
        self._status_item = setup_statusbar(self)

        # 优先使用 Carbon 系统热键（兼容鼠标软件模拟按键）
        self._carbon_hotkey = setup_carbon_hotkey(self._on_hotkey)
        if self._carbon_hotkey is not None:
            log("程序就绪 - 按 Cmd+Shift+O (Carbon 系统热键) 或点击菜单栏图标")
        else:
            # 降级到 CGEventTap（仅支持真实键盘）
            self._event_tap = setup_cgevent_tap(self._on_hotkey)
            if self._event_tap is None:
                log("全局热键不可用，请点击菜单栏图标触发 OCR")
            else:
                log("程序就绪 - 按 Cmd+Shift+O (CGEventTap) 或点击菜单栏图标")

    def performOCR_(self, sender):
        self._trigger_selection()

    def _on_hotkey(self):
        # 在主线程执行截图流程
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            self._trigger_selection, None, False
        )

    def _trigger_selection(self):
        log("trigger_selection 开始")
        # 记录触发前的活跃 App，用于完成后抵消鼠标后退键的意外导航
        frontmost_bid = _frontmost_bundle_id()
        undo_back = frontmost_bid in NAVIGATION_APPS
        if undo_back:
            log(f"前台 App ({frontmost_bid}) 在导航恢复列表中，完成后将发送 Cmd+]")
        fullscreen_path = None
        crop_path = None
        try:
            # 如果使用 CGEventTap，重新启用（Carbon 热键无需此操作）
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

            # 步骤4: 双引擎 OCR 识别
            ocr_result = ocr_with_fallback(crop_path)
            if ocr_result:
                merged_text = merge_lines(ocr_result)
                pyperclip.copy(merged_text)
                self._show_notification("OCR 识别成功", "文本已复制到剪贴板！")
                log(f"OCR 成功: {merged_text.count(chr(10)) + 1} 行")
            else:
                self._show_notification("OCR 提示", "未在该区域识别出文字")
                log("OCR: 未识别出文字")

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
            # 抵消鼠标后退键在导航类 App 中触发的意外后退
            if undo_back:
                _send_forward_navigation(frontmost_bid)
                log(f"已对 {frontmost_bid} 发送 Cmd+] 前进恢复")

    def _show_notification(self, title, message):
        os.system(f"""osascript -e 'display notification "{message}" with title "{title}"'""")

# ----------------- 入口 -----------------
if __name__ == "__main__":
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    ocr_app = OCRApp.alloc().init()
    app.setDelegate_(ocr_app)

    app.run()
