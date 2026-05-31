# OCR 截图识别工具

macOS 菜单栏 OCR 工具，框选屏幕任意区域，文字自动复制到剪贴板。

## 功能

- 菜单栏常驻，点击图标或按 `Cmd+Shift+O` 启动截图识别
- 十字光标框选区域，松开即识别，文字自动复制
- 支持中英文混合识别
- 同行文字自动合并排版
- 支持 Mac Mouse Fix 等鼠标按键映射工具

## 安装

```bash
pip install rapidocr_onnxruntime pyperclip pillow pyobjc-framework-Cocoa pyobjc-framework-Quartz
python ocr_tool.py
```

或直接下载 [Releases](../../releases) 中的 `OCR Tool.app`，拖入应用程序文件夹。

## 使用

1. 启动后菜单栏出现蓝色圆形图标
2. 点击图标选择「截图识别」，或按 `Cmd+Shift+O`
3. 鼠标变为十字光标，拖拽框选需要识别的区域
4. 松开鼠标自动识别，文字复制到剪贴板
5. 按 `ESC` 取消选择

## 常见问题

### 截图识别到的是空白桌面

**原因**：App 没有屏幕录制权限。

**解决**：系统设置 → 隐私与安全性 → 屏幕录制 → 添加并开启 `OCR Tool.app`。

---

### Cmd+Shift+O 组合键不生效 / 提示辅助功能权限

**原因**：CGEventTap 全局热键需要辅助功能权限。

**解决**：系统设置 → 隐私与安全性 → 辅助功能 → 添加并开启 `OCR Tool.app`（或终端）。

---

### 执行一次 OCR 后程序崩溃（segmentation fault）

**原因**：macOS 上 `os.system` 的 `fork()` 调用在 PyObjC 程序中可能导致内存访问错误。

**解决**：已在新版本中将通知改为 `subprocess.Popen` 异步调用。如仍有问题，检查 Python 和 PyObjC 版本：

```bash
python3 --version  # 建议 3.12+
pip install --upgrade pyobjc-framework-Cocoa pyobjc-framework-Quartz
```

---

### 框选区域与实际识别区域上下相反

**原因**：AppKit 坐标（y=0 在底部）与 PIL 图片坐标（y=0 在顶部）存在差异，早期版本未做翻转。

**解决**：v1.1+ 已修复。如使用旧版本请更新。

---

### 鼠标后退键（Mac Mouse Fix）无法触发 OCR

**原因**：合成按键事件的修饰键标志在事件自身而非单独的 FlagsChanged 事件中。

**解决**：v1.1+ 已同时检查累积状态和事件标志位。如仍无效，请在 Mac Mouse Fix 中重新绑定。

---

### OCR 未识别出文字

- 确保框选区域包含清晰文字
- 避免选择纯图标或背景区域
- 适当扩大选择范围

## 依赖

- Python 3.12+
- [RapidOCR](https://github.com/RapidAI/RapidOCR)（ONNX Runtime 引擎）
- [PyObjC](https://pyobjc.readthedocs.io/)（macOS 原生 API 桥接）
- [Pillow](https://python-pillow.org/)（图像处理）
- [pyperclip](https://github.com/asweigart/pyperclip)（剪贴板操作）

## 构建 App

```bash
pip install pyinstaller
pyinstaller --windowed --name "OCR Tool" \
  --collect-submodules rapidocr_onnxruntime \
  --collect-data rapidocr_onnxruntime \
  --hidden-import rapidocr_onnxruntime \
  --hidden-import PIL.Image \
  --hidden-import pyperclip \
  --hidden-import cv2 \
  --hidden-import numpy \
  --osx-bundle-identifier com.ocr.tool \
  ocr_tool.py
```

## License

MIT
